/* =================================================================
   CHAT SEND PENDING — send payload build, pending queue, cancel
   Chunk 2/5 of chat-send.js. Namespace: N.Chat.send / N.Chat.cancel
   + N.Chat._send.clearPending / flushPending.
   Depends on: send/render.js (N.Chat.ui + N.Chat._send),
   send/turn.js (N.Chat._send.begin/endTurnSession + els).
   ================================================================= */
;(function(N) {
var C = N.Core;
var api = C.api, esc = C.esc, toast = C.toast, safeSetHTML = C.safeSetHTML;
var showConfirm = C.showConfirm, showAlert = C.showAlert;
var truncate = C.truncate, relativeTime = C.relativeTime, fmtDate = C.fmtDate;
var fmtStamp = C.fmtStamp;
var safeMarkdown = N.Chat.markdown && N.Chat.markdown.render;
"use strict";
var S = window.S;

var CHAT = N.Chat.state;

function chatCancel() {
  // The turn keeps running server-side (no cancel endpoint) — cancel
  // stops local rendering only; the hub's done re-syncs history.
  N.Chat.ui.removeTyping();
  N.Chat._send.endTurnSession();
  const statusEl = document.getElementById("chat-status");
  if (statusEl) statusEl.textContent = "中断しました";
}

// ------------------------------------------------------------------
// Pending send — the server is still finishing a turn (HTTP 409
// "turn already running", or this tab is streaming): hold the message
// and auto-send once the turn ends instead of failing. Single slot,
// latest message wins. Driven by the existing turn hub terminal
// events, with a bounded backoff as fallback for a stale lock.
// ------------------------------------------------------------------
var PENDING_BACKOFF = [2000, 4000, 8000, 15000];
var PENDING_MAX = 10;
var _pending = null;        // {message, images, rawInput, display}
var _pendingTimer = null;
var _pendingAttempts = 0;

function _clearPending() {
  _pending = null;
  _pendingAttempts = 0;
  if (_pendingTimer) { clearTimeout(_pendingTimer); _pendingTimer = null; }
}

// A turn session can go stale (no terminal event ever arrives) if the
// stream drops — recover it once it's been open >60s so a held send can
// proceed instead of re-queueing forever.
function _resetStaleTurn() {
  if ((N.Chat._send.turn() || CHAT.streaming) && CHAT._streamingSince &&
      Date.now() - CHAT._streamingSince > 60000) {
    console.warn("[chat] turn session stuck for >60s, force-resetting");
    N.Chat.ui.removeTyping();
    N.Chat._send.endTurnSession();
    return true;
  }
  return false;
}

function _queuePending(payload) {
  _pending = payload; // single slot — a newer message replaces the old one
  if (_pendingAttempts === 0) {
    toast("応答の処理が終わってから送信します", "info");
  }
  _armPending();
}

function _armPending() {
  if (_pendingTimer) clearTimeout(_pendingTimer);
  if (_pendingAttempts >= PENDING_MAX) {
    _clearPending();
    toast("送信できませんでした。もう一度お試しください", "error");
    return;
  }
  var delay = PENDING_BACKOFF[Math.min(_pendingAttempts, PENDING_BACKOFF.length - 1)];
  _pendingTimer = setTimeout(function () {
    _pendingTimer = null;
    if (!_pending) return;
    if (CHAT.streaming || N.Chat._send.turn()) {
      if (!_resetStaleTurn()) { _armPending(); return; } // still busy — wait again
    }
    _pendingAttempts += 1;
    _attemptSend(_pending);
  }, delay);
}

// Turn-end flush: the hub reported the busy turn finished — send now
// instead of waiting out the backoff.
function _flushPending() {
  if (!_pending) return;
  if (CHAT.streaming || N.Chat._send.turn()) {
    if (!_resetStaleTurn()) return; // genuinely mid-turn — wait for its end
  }
  if (_pendingTimer) { clearTimeout(_pendingTimer); _pendingTimer = null; }
  if (_pendingAttempts >= PENDING_MAX) {
    _clearPending();
    toast("送信できませんでした。もう一度お試しください", "error");
    return;
  }
  _pendingAttempts += 1;
  _attemptSend(_pending);
}

// POST one payload: render the optimistic user bubble, register the
// turn, and on 409 hold the payload for the next free turn.
function _attemptSend(payload) {
  var inputEl = document.getElementById("chat-input");
  // Only clear the input when it still holds the message we're sending —
  // a queued send must not wipe text the user typed while waiting.
  if (inputEl && inputEl.value.trim() === (payload.rawInput || "").trim()) {
    inputEl.value = "";
    inputEl.style.height = "auto";
  }
  CHAT.attachments = [];
  var attArea = document.getElementById("chat-attachments");
  if (attArea) attArea.textContent = "";
  N.Chat.ui.append("user", payload.display, new Date().toLocaleTimeString("ja-JP", {
    hour: "2-digit",
    minute: "2-digit",
  }));
  N.Chat.ui.showTyping();
  N.Chat._send.beginTurnSession(payload.message);
  var sessionId = N.Chat.history.getSessionId();
  return api(
    "/api/chat/" + encodeURIComponent(S.persona),
    {
      method: "POST",
      // 409 is expected while a turn finishes — handled here, not by the
      // global api:error toast.
      suppressErrorToast: true,
      body: JSON.stringify({
        message: payload.message,
        session_id: sessionId,
        images: payload.images && payload.images.length > 0 ? payload.images : undefined,
        debug: document.getElementById("chat-debug-mode")?.checked || false,
      }),
    },
  ).then(function (resp) {
    if (!resp || !resp.turn_id) throw new Error("no turn_id in 202 response");
    _clearPending();
  }).catch(function (e) {
    N.Chat.ui.removeTyping();
    // Roll back the optimistic user bubble — the message is not lost; it
    // is queued below (or the input is restored).
    var users = document.querySelectorAll(".chat-msg.user");
    if (users.length) users[users.length - 1].remove();
    var els = N.Chat._send.els();
    if (els.statusEl) els.statusEl.textContent = "";
    N.Chat._send.endTurnSession();
    if (e && e.status === 409) {
      if (inputEl && !inputEl.value.trim()) inputEl.value = payload.rawInput || "";
      _queuePending(payload);
      return;
    }
    // A real failure — surface it once and drop the held message so a
    // later terminal event can't silently resend it.
    _clearPending();
    if (inputEl && !inputEl.value.trim()) inputEl.value = payload.rawInput || "";
    toast("送信失敗: " + e.message, "error");
  });
}

// ------------------------------------------------------------------
// Main send function — builds the payload and hands it to _attemptSend
// (or the pending queue when the server is mid-turn).
// ------------------------------------------------------------------
async function chatSend(retry) {
  if (!S.persona) {
    toast("ペルソナを選択してください", "error");
    return;
  }
  const inputEl = document.getElementById("chat-input");
  let rawInput;
  if (retry) {
    // Find last user message
    const msgs = document.querySelectorAll(".chat-msg.user .chat-bubble");
    rawInput = msgs.length > 0 ? msgs[msgs.length - 1].textContent : "";
    if (!rawInput) {
      toast("再送するメッセージがありません", "error");
      return;
    }
  } else {
    rawInput = inputEl.value.trim();
  }
  let message = rawInput;
  if (!message && CHAT.attachments.length === 0) return;
  if (!message) message = "";

  // Base64エンコードされた画像を収集
  const images = [];
  // Append attachment references to message
  if (CHAT.attachments.length > 0) {
    const TEXT_EXTS = new Set([
      "txt",
      "csv",
      "json",
      "py",
      "js",
      "ts",
      "md",
      "yaml",
      "yml",
      "toml",
      "ini",
      "cfg",
      "sh",
      "bash",
      "html",
      "css",
      "xml",
      "log",
      "sql",
      "rs",
      "go",
      "java",
      "cpp",
      "c",
      "h",
    ]);
    const attachParts = [];
    for (const att of CHAT.attachments) {
      const ext = att.filename.split(".").pop().toLowerCase();
      const isText = TEXT_EXTS.has(ext);
      if (isText) {
        try {
          const res = await fetch(att.url);
          const content = await res.text();
          attachParts.push(
            "\n\n--- 添付: " + att.filename + " ---\n" + content + "\n---",
          );
        } catch (_e) {
          attachParts.push("\n[添付ファイル: " + att.workspace_path + "]");
        }
      } else if (
        att.mime_type &&
        att.mime_type.startsWith("image/") &&
        att.file
      ) {
        // FileReaderでBase64に変換
        const base64 = await new Promise((resolve, reject) => {
          const reader = new FileReader();
          reader.onload = () => resolve(reader.result.split(",")[1]); // data:URLプレフィックス除去
          reader.onerror = () => reject(new Error("画像読込失敗"));
          reader.readAsDataURL(att.file);
        });
        images.push({
          filename: att.filename,
          mime_type: att.mime_type,
          base64_data: base64,
        });
      } else {
        attachParts.push("\n[添付ファイル: " + att.workspace_path + "]");
      }
    }
    if (attachParts.length > 0) {
      message = message + attachParts.join("");
    }
  }

  // Save attachment info before clearing
  const attNames = CHAT.attachments.map((a) => a.filename);
  const displayMsg =
    rawInput ||
    (attNames.length > 0
      ? N.Chat._send.paperclipPrefix + attNames.join(", ")
      : "");
  const payload = {
    message: message,
    images: images,
    rawInput: rawInput,
    display: displayMsg,
  };

  // A fresh send supersedes anything queued (single slot, latest wins).
  _clearPending();

  // Safety net: a turn session stuck >60s with no terminal event is
  // force-reset (_turn + streaming + UI) so the send proceeds instead of
  // queueing forever.
  _resetStaleTurn();

  // Server mid-turn (this tab streaming, or another client's turn): hold
  // the message instead of dropping it; the turn-end flush sends it.
  if (CHAT.streaming || N.Chat._send.turn()) {
    _queuePending(payload);
    return;
  }
  return _attemptSend(payload);
}

// ------------------------------------------------------------------
// Expose on N.Chat (chunk 2/5 — send/cancel + internal hooks)
// ------------------------------------------------------------------
N.Chat._send = N.Chat._send || {};
N.Chat._send.clearPending = _clearPending;
N.Chat._send.flushPending = _flushPending;
N.Chat.send = chatSend;
N.Chat.cancel = chatCancel;
})(window.Nous);
