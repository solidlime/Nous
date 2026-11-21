/* =================================================================
   CHAT SEND TURN — turn hub engine: session state, SSE chat-events
   stream, hub dispatch, connectSSE persona funnel
   Chunk 3/5 of chat-send.js. Namespace: N.Chat._send.* (internal).
   Per-event rendering (_handleChatEvent / _finalizeTurn) lives in
   send/turn-events.js and is reached via N.Chat._send.handleEvent.
   Depends on: send/render.js (N.Chat.ui + N.Chat._send),
   send/pending.js (N.Chat._send.clearPending/flushPending).
   ================================================================= */
;(function(N) {
var C = N.Core;
var api = C.api, toast = C.toast;
var showConfirm = C.showConfirm;
"use strict";

var CHAT = N.Chat.state;

// Per-turn rendering state lives in _turn so hub handlers — possibly
// resumed mid-turn after a reconnect replay — share one session.
// ------------------------------------------------------------------
var _chatLastSeq = 0;        // last hub event seq applied (EventSource id:)
var _chatEpoch = null;       // hub epoch from id "<epoch>:<seq>" — サーバー再起動で変わる
var _sawDrop = false;        // SSE onError since last open (drop→open の対で再接続とみなす)
var _reconnectedAt = 0;      // 再接続完了時刻（再起動を跨いだ turn の判定基準）
var _lastEventAt = 0;        // ゲート通過した直近の hub イベント時刻 (watchdog 用)
var _watchdogTimer = null;   // 無進捗 watchdog（誰も terminal event を出さないケースの保険）
var _WATCHDOG_TIMEOUT_MS = 600000; // 10分 — ツール実行の長い静寂を超える値（未知の freeze 用の最後の保険）
var _chatEventsPersona = null;
var _turn = null;            // active turn rendering session
// SSE carries no snapshot/live boundary marker, so the connect-time
// backlog burst (snapshot_after replays the whole ring buffer on every
// connect) is swallowed via this flag: set on open while idle, cleared
// at the burst's first terminal event (done/error). A live turn that
// starts inside the burst window recovers at its done via history
// reload — transient, never permanent.
var _hubSkipMode = false;
// 承認 ID の重複排除。バックログ再生や再送で同じモーダルが二重に出るのを
// 止める手段はこれだけ（_hubSkipMode で捨てるとライブの承認まで落ちる）。
// 上限 32 を超えたら最古の ID から捨てる — Set は挿入順を保つ。
var _seenApprovalIds = new Set();

function _isNewApprovalId(id) {
  if (!id || _seenApprovalIds.has(id)) return false;
  _seenApprovalIds.add(id);
  if (_seenApprovalIds.size > 32) {
    _seenApprovalIds.delete(_seenApprovalIds.values().next().value);
  }
  return true;
}

function _els() {
  return {
    sendBtn: document.getElementById("chat-send-btn"),
    cancelBtn: document.getElementById("chat-cancel-btn"),
    statusEl: document.getElementById("chat-status"),
  };
}

function _beginTurnSession(localMessage) {
  _turn = {
    startedAt: Date.now(),
    // Raw posted message — matches turn_started.user_message so the
    // hub echo dedupes against the locally rendered user bubble.
    localMessage: localMessage || null,
    isLocal: !!localMessage,
    pendingEcho: !!localMessage,
    contentParts: [],
    assistantDiv: null,
    currentTextBubble: null,
    currentTextContent: "",
    thinkingDetails: null,
    thinkingContent: "",
    rafPending: false,
    thinkingRafPending: false,
    scrollListener: null,
    chatMessages: document.getElementById("chat-messages"),
  };
  // A session — local or remote — is live traffic by definition.
  _hubSkipMode = false;
  CHAT.streaming = true;
  CHAT._streamingSince = Date.now();
  CHAT._firstContent = true;
  CHAT._userScrolledUp = false;
  _startWatchdog();
  var els = _els();
  if (els.sendBtn) els.sendBtn.style.display = "none";
  if (els.cancelBtn) els.cancelBtn.style.display = "";
  if (els.statusEl) els.statusEl.textContent = "記憶処理中...";
  if (_turn.chatMessages) {
    _turn.scrollListener = function _onChatScroll() {
      if (!_turn) return;
      /* 最下部付近とみなす距離 — 単一の正は base.js の N.Core.UI。
         base.js を読まないハーネス向けの保険として 100。 */
      var threshold = (C.UI && C.UI.SCROLL_BOTTOM_PX) || 100;
      CHAT._userScrolledUp = _turn.chatMessages.scrollHeight - _turn.chatMessages.scrollTop - _turn.chatMessages.clientHeight > threshold;
    };
    _turn.chatMessages.addEventListener("scroll", _turn.scrollListener, { passive: true });
  }
}

function _endTurnSession() {
  var t = _turn;
  _turn = null;
  _stopWatchdog();
  if (t && t.scrollListener && t.chatMessages) {
    t.chatMessages.removeEventListener("scroll", t.scrollListener);
  }
  CHAT.streaming = false;
  CHAT._streamingSince = null;
  CHAT._userScrolledUp = false;
  CHAT._firstContent = false;
  var els = _els();
  if (els.sendBtn) els.sendBtn.style.display = "";
  if (els.cancelBtn) els.cancelBtn.style.display = "none";
  var inputEl = document.getElementById("chat-input");
  if (inputEl) inputEl.focus();
}

// F3: close the active text bubble before the next content part (tool
// call / result) takes over. The rAF batch reads the bubble at fire
// time, so a bubble closed before its frame was never written — flush
// pending text into it synchronously; drop whitespace-only bubbles
// (they render empty) so nothing lingers under the tool chip.
function _closeTextBubble() {
  var t = _turn;
  if (!t || !t.currentTextBubble) return;
  if ((t.currentTextContent || "").trim()) {
    t.currentTextBubble.textContent = t.currentTextContent;
  } else {
    t.currentTextBubble.remove();
    // Drop the trailing whitespace-only part so the next text_delta
    // starts a fresh bubble instead of writing into the removed one.
    var last = t.contentParts[t.contentParts.length - 1];
    if (last && last.type === "text" && last.bubble === t.currentTextBubble) {
      t.contentParts.pop();
    }
  }
  t.currentTextBubble = null;
  t.currentTextContent = "";
}

function _syncAfterForeignDone() {
  var els = _els();
  if (els.statusEl) els.statusEl.textContent = "";
  // A turn this tab did not render (other client / page-load backlog /
  // post-cancel) completed — pull the canonical history instead of
  // replaying deltas.
  if (N.Chat.history && typeof N.Chat.history.restore === "function") {
    N.Chat.history.restore(false);
  }
  // A foreign turn ended — a held (409) message can go now.
  N.Chat._send.flushPending();
}

// nous:chat-sse CustomEvent — 外部連携（拡張/デバッグUI）向けのイベント横流し。
// 最低限 text_delta / done / error / response_replaced を通知する。
// CustomEvent 未対応環境でも壊さないよう try/catch で囲む。
function _emitChatSSE(evt) {
  var relayed = { text_delta: 1, done: 1, error: 1, response_replaced: 1 };
  if (!evt || !relayed[evt.type]) return;
  try {
    document.dispatchEvent(new CustomEvent("nous:chat-sse", { detail: { type: evt.type, data: evt } }));
  } catch { /* best-effort */ }
}


// 承認待ち。サーバー側は 120 秒で deny に落ちるので、返答が遅れても
// ターンは止まらない。ターン状態に依存させない（別タブでも答える）。
function _askApproval(evt) {
  var persona = _chatEventsPersona || (window.S && window.S.persona);
  if (!persona || !evt.approval_id) return;
  if (!_isNewApprovalId(evt.approval_id)) return; // replay/retransmit
  var toolLabels = { bash: "シェル", sandbox: "隔離シェル" };
  var who = toolLabels[evt.tool_name] || "ファイル操作";
  var detail = String(evt.detail || "").trim() || "(内容なし)";
  Promise.resolve(showConfirm(who + "を実行していい？\n\n" + detail)).then(function (ok) {
    return api("/api/chat/" + encodeURIComponent(persona) + "/approval", {
      method: "POST",
      body: JSON.stringify({ approval_id: evt.approval_id, decision: ok ? "allow" : "deny" }),
      // 404（期限切れ）は想定内 — 汎用の api:error トーストは出さない
      suppressErrorToast: true,
    });
  }).catch(function (err) {
    if (!toast) return;
    if (err && err.status === 404) {
      toast("承認の期限が切れました", "error");
      return;
    }
    toast("承認の送信に失敗: " + ((err && err.message) || err), "error");
  });
}

function _handleHubMessage(e) {
  // id 形式は2種類: "<epoch>:<seq>"（現行）と bare "<seq>"（旧形式）。
  var _parts = String(e.lastEventId || "").split(":");
  var seq = 0, epoch = null;
  if (_parts.length === 2) {
    epoch = _parts[0];
    seq = parseInt(_parts[1], 10);
  } else {
    seq = parseInt(e.lastEventId, 10);
  }
  if (isFinite(seq) && seq > 0) {
    // サーバー再起動で seq は 1 に戻る。epoch 付き id で基線が変わったら
    // seq 基線をリセットする。進行中の自 turn は再起動で消えた孤児なので
    // 回復処理へ回す — ただし自 turn の echo（再起動後の再送信）だけは
    // 健在な新 turn なので例外とする。
    if (epoch && epoch !== _chatEpoch) {
      var _prevEpoch = _chatEpoch;
      _chatEpoch = epoch;
      _chatLastSeq = 0;
      if (_prevEpoch && _turn) {
        var _ownEcho = false;
        if (String(e.data || "").includes('"turn_started"')) {
          try {
            var _pe = JSON.parse(e.data);
            _ownEcho = Boolean(_pe && _pe.type === "turn_started" &&
              _turn.pendingEcho === true &&
              String(_pe.user_message || "") === String(_turn.localMessage || ""));
          } catch {}
        }
        if (!_ownEcho) {
          _recoverOrphanedTurn("サーバーが再起動されたため応答が途切れました");
          return;
        }
      }
    }
    if (seq <= _chatLastSeq) return; // replayed duplicate
    _chatLastSeq = seq;
  }
  _lastEventAt = Date.now();
  var evt;
  try {
    evt = JSON.parse(e.data);
  } catch (err) {
    console.warn("[chat hub parse]:", err.message);
    return;
  }
  if (!evt || !evt.type) return;

  if (evt.type === "approval_requested") {
    // リプレイ分も出す（既に答えた ID は _askApproval が弾く）。期限切れの
    // 古い ID を踏んだら POST が 404 になり「期限切れ」で閉じる。
    _askApproval(evt);
    return;
  }

  if (evt.type === "turn_started") {
    N.Chat.ui.removeTyping();
    if (_turn) {
      // Sender echo — the user bubble was already rendered before the
      // POST landed. Consume the echo exactly once; any later
      // turn_started with the same text is a genuinely new turn.
      if (_turn.pendingEcho &&
          String(_turn.localMessage) === String(evt.user_message || "")) {
        _turn.pendingEcho = false;
      }
      return; // one turn per persona — a stray ts never steals the session
    }
    if (_hubSkipMode) return; // connect-time backlog burst
    // Another client started a turn — render it live here.
    N.Chat._send.beginTurnSession(null);
    N.Chat.ui.append("user", evt.user_message || "");
    return;
  }
  if (!_turn) {
    // キャラ修復は done 後に届く。turn はもう閉じているので msg_id で直接差し替える。
    if (evt.type === "response_replaced") {
      if (N.Chat._send.applyReplaceAfterTurn) N.Chat._send.applyReplaceAfterTurn(evt);
      return;
    }
    if (_hubSkipMode) {
      // Swallow the burst until its first terminal event marks the end.
      if (evt.type === "done" || evt.type === "error") _hubSkipMode = false;
      if (evt.type === "done") _syncAfterForeignDone();
      return;
    }
    if (evt.type === "done") {
      _syncAfterForeignDone();
      return;
    }
    // Panel-level updates ride past the session; every other event is
    // turn-scoped and belongs to backlog/post-cancel — drop it.
    if (evt.type === "memory_activity" || evt.type === "inventory_update" ||
        evt.type === "context_update" || evt.type === "session_summarized" ||
        evt.type === "context_compressed") {
      N.Chat._send.handleEvent(evt);
    }
    return;
  }
  N.Chat._send.handleEvent(evt);
}

// ------------------------------------------------------------------
// 復旧と watchdog — freeze の保険。turn が生きているのに terminal event
// が永遠に来ないケース（サーバー再起動で id 基線が巻き戻った等）を回収する。
// ------------------------------------------------------------------
function _recoverOrphanedTurn(message) {
  N.Chat._send.endTurnSession();
  var els = _els();
  if (els.statusEl) els.statusEl.textContent = "";
  if (toast) toast(message, "error");
  if (N.Chat.history && typeof N.Chat.history.restore === "function") {
    N.Chat.history.restore(false);
  }
  N.Chat._send.flushPending();
}

function _startWatchdog() {
  _stopWatchdog();
  _lastEventAt = Date.now();
  _watchdogTimer = setInterval(function () {
    if (!_turn) { _stopWatchdog(); return; }
    if (Date.now() - _lastEventAt > _WATCHDOG_TIMEOUT_MS) {
      _recoverOrphanedTurn("応答が途切れたため、このターンを打ち切り履歴を再取得しました");
    }
  }, 5000);
}

function _stopWatchdog() {
  if (_watchdogTimer) { clearInterval(_watchdogTimer); _watchdogTimer = null; }
}

function connectChatEvents(persona) {
  _chatEventsPersona = persona || (window.S && window.S.persona) || null;
  // Persona switch voids any in-flight rendering (the container is
  // wiped by the history restore that follows) and restarts the seq
  // baseline — the fresh snapshot is swallowed by the idle rules.
  N.Chat._send.endTurnSession();
  // A queued send belongs to the previous persona — drop it on switch.
  N.Chat._send.clearPending();
  _chatLastSeq = 0;
  _chatEpoch = null; // persona 切替は snapshot 再生から始まる — epoch 基線もリセット
  _sawDrop = false;
  N.Core.connectStream("chat-events", {
    url: function () {
      // epoch を握っているなら "<epoch>:<seq>" で渡す。サーバー再起動後の再接続で
      // epoch が不一致なら全量 replay になり、最初の event で基線を作り直せる。
      // bare seq のままだとサーバ側の純数値ゲート（seq <= last）に新 epoch の
      // event を捨てられ続け、UI が永久に固まる（2026-11-21 事故の主因）。
      return _chatEventsPersona
        ? "/api/chat/" +
            encodeURIComponent(_chatEventsPersona) +
            "/events?last_seq=" +
            (_chatEpoch ? _chatEpoch + ":" + _chatLastSeq : _chatLastSeq)
        : null;
    },
    handlers: {
      message: function (e) { _handleHubMessage(e); },
    },
    onError: function () {
      _sawDrop = true; // drop→open の対でのみ再接続とみなす
    },
    onOpen: function () {
      if (_sawDrop) {
        _sawDrop = false;
        _reconnectedAt = Date.now();
        // 再接続後も生きている turn があり、接続断の間にサーバーが再起動
        // （= id 基線が巻き戻り）していたなら、イベントは二度と届かない。
        // epoch を probe して変わっていれば即座に回復する。
        if (_turn && _chatEpoch && _chatEventsPersona) {
          api("/api/chat/" + encodeURIComponent(_chatEventsPersona) + "/events/epoch", { suppressErrorToast: true })
            .then(function (d) {
              if (d && d.epoch && d.epoch !== _chatEpoch) {
                // in-band 経路（_handleHubMessage）と同じ両輪: epoch 採用と同時に
                // seq 基線もリセットする。再起動直後の ring は空で SSE が沈黙する
                // ため、probe が唯一の epoch 変化信号になる——ここで基線を残すと
                // 旧 seq 基線が新 epoch の全 event を握り潰す（#136 の再生産）。
                _chatEpoch = d.epoch;
                _chatLastSeq = 0;
                if (N.Chat._send.turn() && N.Chat._send.turn().startedAt < _reconnectedAt) {
                  _recoverOrphanedTurn("サーバーが再起動されたため応答が途切れました");
                }
              }
            })
            .catch(function () { /* probe 失敗は本命のイベント経路に任せる */ });
        }
      }
      // Connect-time snapshot burst (the endpoint replays its whole ring
      // buffer on every connect): while idle, swallow it until the first
      // terminal event. A mid-turn reconnect (session active) must NOT
      // skip — the replayed deltas are the live turn's missing tail.
      if (!_turn) _hubSkipMode = true;
    },
  });
}

// ------------------------------------------------------------------
// Persona select (init + change) funnels through N.Core.connectSSE —
// mirror it so the chat-events stream follows the active persona
// (wraps once, even under script double-load).
if (typeof N.Core.connectSSE === "function" && !N.Core._chatEventsConnectWrapped) {
  N.Core._chatEventsConnectWrapped = true;
  (function () {
    var _origConnect = N.Core.connectSSE;
    N.Core.connectSSE = function (persona) {
      var r = _origConnect.apply(this, arguments);
      try { connectChatEvents(persona); } catch {}
      return r;
    };
  })();
}

// ------------------------------------------------------------------
// Expose on N.Chat (chunk 3/5 — turn session hooks)
// ------------------------------------------------------------------
N.Chat._send = N.Chat._send || {};
N.Chat._send.els = _els;
N.Chat._send.turn = function () { return _turn; };
N.Chat._send.beginTurnSession = _beginTurnSession;
N.Chat._send.endTurnSession = _endTurnSession;
N.Chat._send.closeTextBubble = _closeTextBubble;
N.Chat._send.emitChatSSE = _emitChatSSE;
})(window.Nous);
