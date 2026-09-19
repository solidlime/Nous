/* =================================================================
   CHAT HISTORY RESTORE — page-load restore, lazy older-load, export,
   monologue restore, lazy-load triggers + CSP welcome delegation
   Chunk 3/3 of chat-history.js. Namespace: N.Chat.history.restore /
   export. Depends on: history/render.js (N.Chat._history.renderMessages),
   history/session.js (N.Chat.history.reset/getSessionId),
   send/monologue.js (N.Chat.monologue).
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
var _historyGen = 0;
var _restoreLock = false;
var _loadedCount = 0;       // 表示済みメッセージ件数（初期ロード + 追加分）
var _historyComplete = false; // total 取得済み（追加ロード不要）
var _loadingOlder = false;    // 追加ロード中の多重実行防止
var _historyRestorePending = false; // restore 未完了（バックグラウンド復帰時の再実行判定）

async function restoreChatHistory(showSkeleton) {
  if (showSkeleton === undefined) showSkeleton = true;
  if (!S.persona) return;
  if (CHAT._justReset) {
    CHAT._justReset = false;
    return; // リセット直後は履歴を再取得しない
  }
  // Generation counter — prevent stale response from overwriting newer data.
  // Bump AFTER the lock check: a call rejected by the lock must not bump
  // the generation, or the in-flight restore's response fails the
  // freshness check below and is silently discarded (page-load backlog:
  // loadChat's restore races the chat-events hub replay's restore).
  if (_restoreLock) return;
  var myGen = ++_historyGen;
  _restoreLock = true;
  _historyRestorePending = true; // バックグラウンド復帰時の再実行判定用
  try {
  const sid = N.Chat.history.getSessionId();
  const container = document.getElementById("chat-messages");
  const maxMsgs = 50; // 遅延ロード: 初期・追加ロードとも固定50件ずつ
  // Show loading skeleton while fetching history (Bug B3 fix: don't reset DOM before fetch)
  if (showSkeleton) {
    const skeletonHtml =
      '<div class="chat-msg assistant"><div class="chat-bubble" style="opacity:0.5"><div class="skeleton skeleton-text" style="width:80%;height:14px;margin-bottom:8px"></div><div class="skeleton skeleton-text" style="width:60%;height:14px;margin-bottom:8px"></div><div class="skeleton skeleton-text" style="width:40%;height:14px"></div></div></div>' +
      '<div class="chat-msg user" style="align-self:flex-end"><div class="chat-bubble" style="opacity:0.5"><div class="skeleton skeleton-text" style="width:70%;height:14px;margin-bottom:8px"></div><div class="skeleton skeleton-text" style="width:50%;height:14px"></div></div></div>';
    const skeletonDiv = document.createElement("div");
    skeletonDiv.id = "chat-history-skeleton";
    safeSetHTML(skeletonDiv, skeletonHtml);
    container.appendChild(skeletonDiv);
  }
  try {
    const data = await api(
      "/api/chat/" +
        encodeURIComponent(S.persona) +
        "/sessions/" +
        encodeURIComponent(sid) +
        "?limit=" + maxMsgs + "&offset=0",
    );
    // Remove skeleton
    const skel = document.getElementById("chat-history-skeleton");
    if (skel) skel.remove();
    if (myGen !== _historyGen) return; // 新しい呼び出しに敗退
    if (!data || !data.messages) {
      console.warn("[restoreChatHistory] unexpected response — data or messages missing:", data);
      S.historyLoadFailed = true;
      return;
    }
    _loadedCount = data.messages.length;
    // total が全件数 — 取得済みなら「さらに古いメッセージなし」
    _historyComplete = typeof data.total === "number"
      ? data.total <= _loadedCount
      : data.messages.length < maxMsgs;
    if (data.messages.length === 0) {
      // No history, show welcome
      console.info("[restoreChatHistory] no messages, fresh start");
      CHAT.messages = [];
      _historyComplete = true;
      N.Chat.history.reset();
      // No chat history either way — monologue whispers still restore
      restoreMonologueBubbles();
      return;
    }
    // Successful fetch — now safe to reset DOM (Bug B3 fix: only reset after fetch succeeds)
    CHAT.messages = [];
    container.textContent = "";
    N.Chat._history.renderMessages(data.messages, { prepend: false });
    N.Core.refreshIcons();
    // REM monologue bubbles ride on top of the restored history
    // (display-only; every restore re-fetches, so persona switches
    // get a fresh set after the container wipe).
    restoreMonologueBubbles();
  } catch (e) {
    console.error("[restoreChatHistory] failed:", e);
    toast("チャット履歴復元失敗: " + e.message, "error");
    // Session not found or API unavailable — start fresh
    const skel = document.getElementById("chat-history-skeleton");
    if (skel) skel.remove();
  }
  // 最下部にスクロール
  const c = document.getElementById("chat-messages");
  if (c) {
    requestAnimationFrame(function() {
      c.scrollTop = c.scrollHeight;
      // Final pass after the last restored chunk: scroll-save handlers fire
      // mid-restore, so re-assert bottom one frame after the layout settles
      requestAnimationFrame(function() { c.scrollTop = c.scrollHeight; });
    });
  }
  } finally {
    _restoreLock = false;
    _historyRestorePending = false;
  }
}

// ------------------------------------------------------------------
async function loadOlderMessages() {
  if (!S.persona || _loadingOlder || _historyComplete || _restoreLock) return;
  _loadingOlder = true;
  var container = document.getElementById("chat-messages");
  // appendChatMessage が scrollTop を末尾へリセットするため、事前に捕捉しておく
  var prevScrollTop = container ? container.scrollTop : 0;
  var prevScrollHeight = container ? container.scrollHeight : 0;
  try {
    const maxMsgs = 50;
    const data = await api(
      "/api/chat/" +
        encodeURIComponent(S.persona) +
        "/sessions/" +
        encodeURIComponent(N.Chat.history.getSessionId()) +
        "?limit=" + maxMsgs + "&offset=" + _loadedCount,
    );
    if (!data || !data.messages) {
      console.warn("[loadOlderMessages] unexpected response:", data);
      _historyComplete = true; // 再試行ループ回避
      return;
    }
    if (data.messages.length === 0) {
      _historyComplete = true;
      return;
    }
    // 既存メッセージの前に挿入（コンテナは空にしない）
    N.Chat._history.renderMessages(data.messages, { prepend: true });
    _loadedCount += data.messages.length;
    if (typeof data.total === "number" && data.total <= _loadedCount) {
      _historyComplete = true;
    }
    // 追加ロードで古いメッセージが先頭に来たので、既存の独り言バブルを
    // 正しい時系列位置へ再挿入（スロット決め直し）
    if (N.Chat.monologue && typeof N.Chat.monologue.reslot === "function") {
      N.Chat.monologue.reslot();
    }
    // 挿入差分ぶんスクロール位置を補正して表示位置を維持
    if (container) {
      container.scrollTop = prevScrollTop + (container.scrollHeight - prevScrollHeight);
    }
    N.Core.refreshIcons();
  } catch (e) {
    console.error("[loadOlderMessages] failed:", e);
    toast("過去のメッセージ取得失敗: " + e.message, "error");
  } finally {
    _loadingOlder = false;
  }
}

// ------------------------------------------------------------------
function exportChatHistory() {
  const container = document.getElementById("chat-messages");
  if (!container) return;
  const bubbles = container.querySelectorAll(".chat-msg");
  if (bubbles.length === 0) {
    toast("エクスポートする会話がありません", "error");
    return;
  }
  const lines = [];
  const persona = S.persona;
  lines.push("# 会話ログ - " + persona);
  lines.push("> エクスポート日時: " + new Date().toISOString());
  lines.push("");
  bubbles.forEach((msg) => {
    const role = msg.classList.contains("user")
      ? '**ユーザー**'
      : '**アシスタント**';
    const bubble = msg.querySelector(".chat-bubble");
    const time = msg.querySelector(".chat-time")?.textContent || "";
    const content = bubble ? bubble.textContent : "";
    lines.push("### " + role + " _" + time + "_");
    lines.push("");
    lines.push(content);
    lines.push("");
  });
  const blob = new Blob([lines.join("\n")], {
    type: "text/markdown;charset=utf-8",
  });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download =
    "chat-" + persona + "-" + new Date().toISOString().slice(0, 10) + ".md";
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
  toast("会話をエクスポートしました", "success");
}

// ------------------------------------------------------------------
async function restoreMonologueBubbles() {
  if (!S.persona) return;
  var monologue = N.Chat.monologue;
  if (!monologue || typeof monologue.append !== "function") return;
  var personaAtRequest = S.persona;
  try {
    var data = await api(
      "/api/session-events/" + encodeURIComponent(personaAtRequest) +
      "?event_type=brain.monologue&limit=100&order=desc",
    );
    // A response that lands after the persona moved on is stale — drop it
    if (S.persona !== personaAtRequest) return;
    var events = (data && data.events) || [];
    // API returns newest-first; render chronologically so the whisper
    // trail reads the way it happened. Each whisper slots between the
    // messages by its full ISO timestamp (epoch comparison inside
    // monologue.append). limit=100: page load shows only 50 messages,
    // but whispers older than the visible window still belong on screen.
    for (var i = events.length - 1; i >= 0; i--) {
      var ev = events[i];
      if (ev && ev.summary) {
        // metadata.kind="exploration" の探索要約は 🔍 ラベルで復元 (spec C/G)。
        monologue.append(ev.summary, String(ev.timestamp || ""), ev.metadata && ev.metadata.kind);
      }
    }
  } catch (e) {
    console.warn("[monologue restore]:", e.message);
  }
}

// ------------------------------------------------------------------
// Lazy-load triggers — registered once at init
var _historyListenersBound = false;
function bindHistoryLazyLoadListeners() {
  if (_historyListenersBound) return; // 二重登録防止
  _historyListenersBound = true;
  var container = document.getElementById("chat-messages");
  if (container) {
    container.addEventListener("scroll", function _onHistoryScroll() {
      if (container.scrollTop <= 30 && !_historyComplete && !_loadingOlder) {
        loadOlderMessages();
      }
    }, { passive: true });
  }
  document.addEventListener("visibilitychange", function _onVisibility() {
    if (document.visibilityState === "visible" && _historyRestorePending) {
      restoreChatHistory(true);
    }
  });
  window.addEventListener("pageshow", function _onPageShow(e) {
    if (e.persisted && _historyRestorePending) {
      restoreChatHistory(true);
    }
  });
}
bindHistoryLazyLoadListeners();

/* CSP-safe delegation: welcome settings link (no inline onclick) */
if (typeof document !== "undefined" && !N.Chat.history.reset._delegated) {
  N.Chat.history.reset._delegated = true;
  document.addEventListener("click", function (e) {
    var a = e.target && e.target.closest ? e.target.closest("[data-chat-welcome-settings]") : null;
    if (!a) return;
    e.preventDefault();
    if (N.Chat.core && typeof N.Chat.core.toggleSettings === "function") N.Chat.core.toggleSettings();
  });
}
// ------------------------------------------------------------------
// Expose on N.Chat (chunk 3/3 — restore/export)
// ------------------------------------------------------------------
N.Chat.history = N.Chat.history || {};
N.Chat.history.restore = restoreChatHistory;
N.Chat.history.export = exportChatHistory;
// Wire the restore hook into the monologue API (send/monologue.js owns
// the bubble renderer; the fetch-and-replay flow lives here).
if (N.Chat.monologue) N.Chat.monologue.restore = restoreMonologueBubbles;
})(window.Nous);
