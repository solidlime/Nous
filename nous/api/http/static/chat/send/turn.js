/* =================================================================
   CHAT SEND TURN — turn hub engine: session state, SSE chat-events
   stream, hub dispatch, connectSSE persona funnel
   Chunk 3/5 of chat-send.js. Namespace: N.Chat._send.* (internal) +
   N.Chat.introspectionTool. Per-event rendering (_handleChatEvent /
   _finalizeTurn) lives in send/turn-events.js and is reached via
   N.Chat._send.handleEvent.
   Depends on: send/render.js (N.Chat.ui + N.Chat._send),
   send/pending.js (N.Chat._send.clearPending/flushPending),
   send/monologue.js (N.Chat.monologue.connect).
   ================================================================= */
;(function(N) {
var C = N.Core;
var api = C.api, esc = C.esc, toast = C.toast, safeSetHTML = C.safeSetHTML;
var showConfirm = C.showConfirm, showAlert = C.showAlert;
var truncate = C.truncate, relativeTime = C.relativeTime, fmtDate = C.fmtDate;
var fmtStamp = C.fmtStamp;
"use strict";
var S = window.S;

var CHAT = N.Chat.state;

// Per-turn rendering state lives in _turn so hub handlers — possibly
// resumed mid-turn after a reconnect replay — share one session.
// ------------------------------------------------------------------
var _chatLastSeq = 0;        // last hub event seq applied (EventSource id:)
var _chatEventsPersona = null;
var _turn = null;            // active turn rendering session
// SSE carries no snapshot/live boundary marker, so the connect-time
// backlog burst (snapshot_after replays the whole ring buffer on every
// connect) is swallowed via this flag: set on open while idle, cleared
// at the burst's first terminal event (done/error). A live turn that
// starts inside the burst window recovers at its done via history
// reload — transient, never permanent.
var _hubSkipMode = false;

function _els() {
  return {
    sendBtn: document.getElementById("chat-send-btn"),
    cancelBtn: document.getElementById("chat-cancel-btn"),
    statusEl: document.getElementById("chat-status"),
  };
}

function _beginTurnSession(localMessage) {
  _turn = {
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
  var els = _els();
  if (els.sendBtn) els.sendBtn.style.display = "none";
  if (els.cancelBtn) els.cancelBtn.style.display = "";
  if (els.statusEl) els.statusEl.textContent = "記憶処理中...";
  if (_turn.chatMessages) {
    _turn.scrollListener = function _onChatScroll() {
      if (!_turn) return;
      var threshold = 80;
      CHAT._userScrolledUp = _turn.chatMessages.scrollHeight - _turn.chatMessages.scrollTop - _turn.chatMessages.clientHeight > threshold;
    };
    _turn.chatMessages.addEventListener("scroll", _turn.scrollListener, { passive: true });
  }
}

function _endTurnSession() {
  var t = _turn;
  _turn = null;
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
  } catch (_e) { /* best-effort */ }
}


function _handleHubMessage(e) {
  var seq = parseInt(e.lastEventId, 10);
  if (isFinite(seq) && seq > 0) {
    if (seq <= _chatLastSeq) return; // replayed duplicate
    _chatLastSeq = seq;
  }
  var evt;
  try {
    evt = JSON.parse(e.data);
  } catch (err) {
    console.warn("[chat hub parse]:", err.message);
    return;
  }
  if (!evt || !evt.type) return;

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

// tool.called (source="introspection"): 内省 curiosity 探索のツール実行を
// チャットログに流す (spec C)。メイン対話の tool_call SSE と二重表示しない
// よう introspection 由来のみ描画する。data は JSON 文字列/オブジェクト両対応。
function handleToolCalledEvent(data) {
  try {
    var d = typeof data === "string" ? JSON.parse(data || "{}") : (data || {});
    if (d && d.tool_name && d.source === "introspection" &&
        N.Chat.tools && typeof N.Chat.tools.appendIntrospectionCall === "function") {
      N.Chat.tools.appendIntrospectionCall(d);
    }
  } catch (_e) { /* best-effort */ }
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
  N.Core.connectStream("chat-events", {
    url: function () {
      return _chatEventsPersona
        ? "/api/chat/" + encodeURIComponent(_chatEventsPersona) + "/events?last_seq=" + _chatLastSeq
        : null;
    },
    handlers: {
      message: function (e) { _handleHubMessage(e); },
      tool_called: function (e) { handleToolCalledEvent(e.data); },
    },
    onOpen: function () {
      // Connect-time snapshot burst (the endpoint replays its whole ring
      // buffer on every connect): while idle, swallow it until the first
      // terminal event. A mid-turn reconnect (session active) must NOT
      // skip — the replayed deltas are the live turn's missing tail.
      if (!_turn) _hubSkipMode = true;
    },
  });
}

// ------------------------------------------------------------------
// REM monologue — display-only whisper fed by the wiring stream
// (kind=monologue, meta={persona,text}). Lives in the DOM only: no
// chat history array, no session-save call, vanishes on reload.
// Class is deliberately separate from .chat-thinking-bubble —
// thinking belongs to the chat stream, this to the wiring stream.
// Persona select (init + change) funnels through N.Core.connectSSE —
// mirror it so the monologue AND chat-events streams always follow the
// active persona (wraps once, even under script double-load).
if (typeof N.Core.connectSSE === "function" && !N.Core._monologueConnectWrapped) {
  N.Core._monologueConnectWrapped = true;
  (function () {
    var _origConnect = N.Core.connectSSE;
    N.Core.connectSSE = function (persona) {
      var r = _origConnect.apply(this, arguments);
      try { N.Chat.monologue.connect(persona); } catch (_e) {}
      try { connectChatEvents(persona); } catch (_e) {}
      return r;
    };
  })();
}

// ------------------------------------------------------------------
// ------------------------------------------------------------------
// Expose on N.Chat (chunk 3/5 — turn session hooks + introspection)
// ------------------------------------------------------------------
N.Chat._send = N.Chat._send || {};
N.Chat._send.els = _els;
N.Chat._send.turn = function () { return _turn; };
N.Chat._send.beginTurnSession = _beginTurnSession;
N.Chat._send.endTurnSession = _endTurnSession;
N.Chat._send.closeTextBubble = _closeTextBubble;
N.Chat._send.emitChatSSE = _emitChatSSE;
// tool.called (source=introspection) ハンドラ — connectChatEvents が参照し、
// テストからも直接検証できるよう公開する。
N.Chat.introspectionTool = { handle: handleToolCalledEvent };
})(window.Nous);
