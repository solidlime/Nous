/* =================================================================
   CHAT SEND RENDER — message DOM rendering, typing indicator, scroll,
   assistant div/bubble helpers, clipboard
   Chunk 1/5 of chat-send.js (split: render / pending / turn /
   turn-events / monologue). Namespace: N.Chat.ui + N.Chat._send.*
   Depends on: chat-core.js (N.Chat.state), chat-markdown.js,
   chat-tts.js (play), chat-attachments.js (openViewer).
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

// Marker for an attachment-only user bubble. appendChatMessage detects this
// prefix and renders the icon as a real element — filenames stay text.
var PAPERCLIP_PREFIX = '<i data-lucide="paperclip"></i> ';

function appendChatMessage(role, content, timeStr, isMarkdown, msgId, ts) {
  const container = document.getElementById("chat-messages");
  if (!container) return null;
  // Remove welcome message if present
  const welcome = container.querySelector(".chat-welcome");
  if (welcome) welcome.remove();

  // Calculate message index (0-based position in session)
  const msgIndex = container.querySelectorAll(".chat-msg").length;

  const div = document.createElement("div");
  div.className = "chat-msg " + role;
  div.dataset.msgIndex = msgIndex;
  div.dataset.msgId = msgId || "";
  // ISO anchor for monologue chronological slotting (restore + live alike)
  div.dataset.ts = ts || new Date().toISOString();
  const bubble = document.createElement("div");
  bubble.className = "chat-bubble";
  if (isMarkdown && role === "assistant") {
    safeSetHTML(bubble, safeMarkdown(content));
    // メッセージ内の画像にクリックイベント追加
    bubble.querySelectorAll("img").forEach((img) => {
      img.style.cssText =
        "max-width:100%;border-radius:8px;cursor:pointer;margin:8px 0;";
      img.addEventListener("click", () => N.Chat.attachments.openViewer(img.src, "image"));
    });
  } else if (role === "user" && typeof content === "string" &&
             content.indexOf(PAPERCLIP_PREFIX) === 0) {
    // Attachment-only bubble: build the icon as an element and keep the
    // filenames as plain text — content is never parsed as HTML.
    const icon = document.createElement("i");
    icon.setAttribute("data-lucide", "paperclip");
    bubble.appendChild(icon);
    bubble.appendChild(
      document.createTextNode(" " + content.slice(PAPERCLIP_PREFIX.length)),
    );
  } else {
    bubble.textContent = content;
  }
  const timeDiv = document.createElement("div");
  timeDiv.className = "chat-time";
  timeDiv.textContent = fmtStamp(div.dataset.ts);
  div.appendChild(bubble);
  div.appendChild(timeDiv);

  // Action buttons
  const actions = document.createElement("div");
  actions.className = "chat-msg-actions";
  if (role === "user") {
    const editBtn = document.createElement("button");
    editBtn.className = "chat-msg-action-btn edit";
    safeSetHTML(editBtn, '<i data-lucide="pencil"></i> 編集');
    editBtn.onclick = () => {
      const mid = div.dataset.msgId;
      const idx = parseInt(div.dataset.msgIndex);
      N.Chat.history.edit(mid || idx);
    };
    actions.appendChild(editBtn);

    const deleteBtn = document.createElement("button");
    deleteBtn.className = "chat-msg-action-btn delete";
    safeSetHTML(deleteBtn, '<i data-lucide="trash-2"></i>');
    deleteBtn.title = "削除";
    deleteBtn.setAttribute("aria-label", "メッセージを削除");
    deleteBtn.onclick = () => {
      const mid = div.dataset.msgId;
      const idx = parseInt(div.dataset.msgIndex);
      N.Chat.history.delete(mid || idx);
    };
    actions.appendChild(deleteBtn);
  } else if (role === "assistant") {
    const ttsBtn = document.createElement("button");
    ttsBtn.className = "chat-msg-action-btn chat-tts-btn";
    safeSetHTML(ttsBtn, '<i data-lucide="volume-2"></i>');
    ttsBtn.title = "音声で再生";
    ttsBtn.setAttribute("aria-label", "音声で再生");
    ttsBtn.onclick = () => {
        const allText = Array.from(div.querySelectorAll(".chat-bubble"))
            .map(b => b.textContent)
            .join("\n");
        N.Chat.tts.play(ttsBtn, allText);
    };
    actions.appendChild(ttsBtn);
    const retryBtn = document.createElement("button");
    retryBtn.className = "chat-msg-action-btn retry";
    safeSetHTML(retryBtn, '<i data-lucide="refresh-cw"></i> 再生成');
    retryBtn.onclick = () => {
      const mid = div.dataset.msgId;
      const idx = parseInt(div.dataset.msgIndex);
      N.Chat.history.rollback(mid || idx, true);
    };
    actions.appendChild(retryBtn);
    const copyBtn = document.createElement("button");
    copyBtn.className = "chat-msg-action-btn";
    safeSetHTML(copyBtn, '<i data-lucide="clipboard-list"></i>');
    copyBtn.title = "コピー";
    copyBtn.onclick = () => {
        const allText = Array.from(div.querySelectorAll(".chat-bubble"))
            .map(b => b.textContent)
            .join("\n");
        _copyToClipboard(allText);
    };
    actions.appendChild(copyBtn);
  }
  div.appendChild(actions);

  container.appendChild(div);
  _autoScroll(container);
  N.Core.refreshIcons();
  CHAT.messages.push(div);
  return div;
}

// ------------------------------------------------------------------
// Typing indicator
// ------------------------------------------------------------------
function showTypingIndicator() {
  const container = document.getElementById("chat-messages");
  const typing = document.createElement("div");
  typing.id = "chat-typing";
  typing.className = "chat-msg assistant";
  safeSetHTML(typing,
    '<div class="chat-bubble chat-typing"><span></span><span></span><span></span></div>');
  container.appendChild(typing);
  _autoScroll(container);
}

function removeTypingIndicator() {
  const el = document.getElementById("chat-typing");
  if (el) el.remove();
}

// ------------------------------------------------------------------
// Find chat log container / scroll to bottom
// ------------------------------------------------------------------
function findChatLogContainer() {
  const chatLog = document.getElementById("chat-messages");
  if (chatLog) {
    return chatLog;
  }
  return document.getElementById("chat-log");
}

function scrollToBottom(container) {
  if (!container) return;
  container.scrollTop = container.scrollHeight;
}

// Intent-aware auto-scroll: follow the stream unless the user scrolled up
// to read history (turn scroll listener sets CHAT._userScrolledUp).
function _autoScroll(container) {
  if (!container) return;
  var isAtBottom = container.scrollHeight - container.scrollTop - container.clientHeight < 80;
  if (isAtBottom || !CHAT._userScrolledUp) {
    container.scrollTop = container.scrollHeight;
  }
}

// ------------------------------------------------------------------
// Helper: create a new assistant message div with time stamp + actions
// ------------------------------------------------------------------
function _createAssistantDiv() {
  const container = document.getElementById("chat-messages");
  // Remove welcome message if present
  const welcome = container.querySelector(".chat-welcome");
  if (welcome) welcome.remove();
  // Calculate message index (0-based position in session)
  const msgIndex = container.querySelectorAll(".chat-msg").length;
  const div = document.createElement("div");
  div.className = "chat-msg assistant";
  div.dataset.msgIndex = msgIndex;
  div.dataset.msgId = "";
  div.dataset.ts = new Date().toISOString();
  const timeDiv = document.createElement("div");
  timeDiv.className = "chat-time";
  timeDiv.textContent = fmtStamp(div.dataset.ts);
  div.appendChild(timeDiv);
  // Action buttons (deferred — content collected from all .chat-bubble text at click time)
  const actions = document.createElement("div");
  actions.className = "chat-msg-actions";
  // TTS manual play button
  const ttsBtn = document.createElement("button");
  ttsBtn.className = "chat-msg-action-btn chat-tts-btn";
  safeSetHTML(ttsBtn, '<i data-lucide="volume-2"></i>');
  ttsBtn.title = "音声で再生";
  ttsBtn.setAttribute("aria-label", "音声で再生");
  ttsBtn.onclick = () => {
    const allText = Array.from(div.querySelectorAll(".chat-bubble"))
      .map(b => b.textContent)
      .join("\n");
    N.Chat.tts.play(ttsBtn, allText);
  };
  actions.appendChild(ttsBtn);
  // Retry / regenerate button
  const retryBtn = document.createElement("button");
  retryBtn.className = "chat-msg-action-btn retry";
  safeSetHTML(retryBtn, '<i data-lucide="refresh-cw"></i> 再生成');
  retryBtn.onclick = () => {
    const mid = div.dataset.msgId;
    const idx = parseInt(div.dataset.msgIndex);
    N.Chat.history.rollback(mid || idx, true);
  };
  actions.appendChild(retryBtn);
  // Copy button
  const copyBtn = document.createElement("button");
  copyBtn.className = "chat-msg-action-btn";
  safeSetHTML(copyBtn, '<i data-lucide="clipboard-list"></i>');
  copyBtn.title = "コピー";
  copyBtn.onclick = () => {
    const allText = Array.from(div.querySelectorAll(".chat-bubble"))
      .map(b => b.textContent)
      .join("\n");
    navigator.clipboard
      .writeText(allText)
      .then(() => toast("コピーしました", "success"));
  };
  actions.appendChild(copyBtn);
  div.appendChild(actions);
  container.appendChild(div);
  N.Core.refreshIcons();
  if (window.Nous && Nous.Chat.ttsStream && Nous.Chat.ttsStream.startStream && document.getElementById("chat-voice-streaming")?.checked) { try { Nous.Chat.ttsStream.startStream(S.persona); } catch (_e) {} }
  return div;
}

// ------------------------------------------------------------------
// Helper: create a new text bubble inside an assistant div (before .chat-time)
// ------------------------------------------------------------------
function _createTextBubble(assistantDiv) {
  const bubble = document.createElement("div");
  bubble.className = "chat-bubble";
  const timeDiv = assistantDiv.querySelector(".chat-time");
  if (timeDiv) {
    assistantDiv.insertBefore(bubble, timeDiv);
  } else {
    assistantDiv.appendChild(bubble);
  }
  return bubble;
}

// ------------------------------------------------------------------
// Clipboard helper — try modern API, fallback to execCommand
// ------------------------------------------------------------------
function _copyToClipboard(text) {
  if (navigator.clipboard && typeof navigator.clipboard.writeText === "function") {
    navigator.clipboard.writeText(text)
      .then(function() { toast("コピーしました", "success"); })
      .catch(function() { _fallbackCopy(text); });
  } else {
    _fallbackCopy(text);
  }
}

function _fallbackCopy(text) {
  var textarea = document.createElement("textarea");
  textarea.value = text;
  textarea.style.position = "fixed";
  textarea.style.left = "-9999px";
  textarea.style.top = "-9999px";
  document.body.appendChild(textarea);
  textarea.focus();
  textarea.select();
  try {
    document.execCommand("copy");
    toast("コピーしました", "success");
  } catch (e) {
    toast("コピーに失敗しました", "error");
  } finally {
    document.body.removeChild(textarea);
  }
}

// ------------------------------------------------------------------
// Expose on N.Chat (chunk 1/5 — render API). N.Chat._send is the
// internal cross-chunk table shared with send/pending.js, send/turn.js
// and send/turn-events.js (namespaced _-prefixed = private).
// ------------------------------------------------------------------
N.Chat._send = N.Chat._send || {};
N.Chat._send.autoScroll = _autoScroll;
N.Chat._send.createAssistantDiv = _createAssistantDiv;
N.Chat._send.createTextBubble = _createTextBubble;
N.Chat._send.paperclipPrefix = PAPERCLIP_PREFIX;
N.Chat.ui = {
  append: appendChatMessage,
  showTyping: showTypingIndicator,
  removeTyping: removeTypingIndicator,
  scrollToBottom: scrollToBottom,
  findLog: findChatLogContainer,
};
})(window.Nous);
