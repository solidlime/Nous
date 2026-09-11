/* =================================================================
   CHAT SEND — Message sending, streaming, typing indicator, rendering
   Extracted from chat.js (Phase 3, Batch 2)
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
var _memoryActivityTimer = null;

// memoryPanel is registered by chat-memory-panel.js; noop when absent
// (e.g. panel script failed to load) so streaming never crashes on it.
function _mem(fn) {
  var mp = (N.Chat && N.Chat.memoryPanel) || {};
  return typeof mp[fn] === "function" ? mp[fn].bind(mp) : function () {};
}

// ------------------------------------------------------------------
// Append a chat message to the DOM
// ------------------------------------------------------------------
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
  container.scrollTop = container.scrollHeight;
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
  container.scrollTop = container.scrollHeight;
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
// Cancel streaming
// ------------------------------------------------------------------
function chatCancel() {
  // The turn keeps running server-side (no cancel endpoint) — cancel
  // stops local rendering only; the hub's done re-syncs history.
  removeTypingIndicator();
  _endTurnSession();
  const statusEl = document.getElementById("chat-status");
  if (statusEl) statusEl.textContent = "中断しました";
}

// ------------------------------------------------------------------
// Main send function — sends a message to the server and streams response
// ------------------------------------------------------------------
async function chatSend(retry) {
  if (!S.persona) {
    toast("ペルソナを選択してください", "error");
    return;
  }
  if (CHAT.streaming) {
    // Safety net: if streaming flag has been set for > 60 seconds, force-reset
    if (CHAT._streamingSince && Date.now() - CHAT._streamingSince > 60000) {
      console.warn("[chatSend] streaming flag stuck for >60s, force-resetting");
      CHAT.streaming = false;
      CHAT._streamingSince = null;
    } else {
      return;
    }
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

  const sendBtn = document.getElementById("chat-send-btn");
  const cancelBtn = document.getElementById("chat-cancel-btn");
  const statusEl = document.getElementById("chat-status");

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

  inputEl.value = "";
  inputEl.style.height = "auto";
  // Save attachment info before clearing
  const attNames = CHAT.attachments.map((a) => a.filename);
  CHAT.attachments = [];
  const attArea = document.getElementById("chat-attachments");
  if (attArea) attArea.textContent = "";

  // Show user message with filename display
  const displayMsg =
    rawInput ||
    (attNames.length > 0
      ? '<i data-lucide="paperclip"></i> ' + attNames.join(", ")
      : "");
  const timeStr = new Date().toLocaleTimeString("ja-JP", {
    hour: "2-digit",
    minute: "2-digit",
  });
  appendChatMessage("user", displayMsg, timeStr);
  showTypingIndicator();

  const sessionId = N.Chat.history.getSessionId();
  // F3: content_parts-based rendering — tracks interleaved text/tool_call/tool_result
  // (state lives in the module-level _turn session, fed by the hub stream)
  let contentParts = [];       // [{type:"text"|"tool_call"|"tool_result", ...}]
  let assistantDiv = null;
  let currentTextBubble = null;  // DOM element currently being streamed to
  let currentTextContent = "";   // raw text accumulated for current text part
  // CoT display (R6): managed independently of text streaming.
  // Deliberately NOT pushed to contentParts and NOT .chat-bubble —
  // structural TTS/copy exclusion (TTS manual/copy collect .chat-bubble,
  // TTS auto-play collects contentParts text only).
  let thinkingDetails = null;   // <details class="chat-thinking-bubble">
  let thinkingContent = "";     // accumulated thinking text

  // F3: close the active text bubble before the next content part (tool
  // call / result) takes over. The rAF batch reads currentTextBubble at
  // fire time, so a bubble closed before its frame was never written —
  // it sat as an empty white bubble while the tool ran. Flush pending
  // text into the bubble synchronously; drop whitespace-only bubbles
  // (they render empty) so nothing lingers under the tool chip.
  function _closeTextBubble() {
    if (!currentTextBubble) return;
    if ((currentTextContent || "").trim()) {
      currentTextBubble.textContent = currentTextContent;
    } else {
      currentTextBubble.remove();
      // Drop the trailing whitespace-only part so the next text_delta
      // starts a fresh bubble instead of writing into the removed one.
      const last = contentParts[contentParts.length - 1];
      if (last && last.type === "text" && last.bubble === currentTextBubble) {
        contentParts.pop();
      }
    }
    currentTextBubble = null;
    currentTextContent = "";
  }

  // Turn session + persistent hub subscription: the POST only REGISTERS
  // the turn (202 + turn_id); every event — turn_started → … → done —
  // arrives on the chat-events SSE stream. The session is created
  // BEFORE the POST so the turn_started race (the hub publishes it
  // before the 202 lands) dedupes against the local user bubble.
  _beginTurnSession(message);

  try {
    const resp = await api(
      "/api/chat/" + encodeURIComponent(S.persona),
      {
        method: "POST",
        body: JSON.stringify({
          message: message,
          session_id: sessionId,
          images: images.length > 0 ? images : undefined,
          debug: document.getElementById("chat-debug-mode")?.checked || false,
        }),
      },
    );
    if (!resp || !resp.turn_id) throw new Error("no turn_id in 202 response");
  } catch (e) {
    removeTypingIndicator();
    toast("送信失敗: " + e.message, "error");
    var els = _els();
    if (els.statusEl) els.statusEl.textContent = "";
    _endTurnSession();
    return;
  }
}
// ------------------------------------------------------------------
// Turn hub engine — event supply switched from the fetch-stream loop
// to the persistent chat-events SSE stream (E3: server-side turn task).
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
}

// Per-event rendering — bodies carried over from the fetch-stream loop.
function _handleChatEvent(evt) {
  var t = _turn;
  var els = _els();
  var chatMessages = t ? t.chatMessages : null;

  if (evt.type === "text_delta") {
    if (!evt.content) return;
    if (CHAT._firstContent) {
      CHAT._firstContent = false;
      if (els.statusEl) els.statusEl.textContent = "応答中...";
    }
    // F3: content_parts — create or continue text bubble inside assistant div
    if (!t.assistantDiv) {
      t.assistantDiv = _createAssistantDiv();
    }
    // If the last part was a tool call, start a new text bubble
    const lastPart = t.contentParts[t.contentParts.length - 1];
    if (!lastPart || lastPart.type !== "text") {
      t.currentTextBubble = _createTextBubble(t.assistantDiv);
      t.currentTextContent = "";
      t.contentParts.push({ type: "text", bubble: t.currentTextBubble, content: "" });
    }
    t.currentTextContent += evt.content;
    if (window.Nous && Nous.Chat.ttsStream && Nous.Chat.ttsStream.onDelta && document.getElementById("chat-voice-streaming")?.checked) { try { Nous.Chat.ttsStream.onDelta(t.currentTextContent); } catch (_e) {} }
    t.contentParts[t.contentParts.length - 1].content = t.currentTextContent;

    // rAF-batched DOM update
    if (!t.rafPending) {
      t.rafPending = true;
      requestAnimationFrame(function() {
        t.rafPending = false;
        if (t.currentTextBubble) {
          t.currentTextBubble.textContent = t.currentTextContent;
        }
        // Auto-scroll with user intent detection
        if (chatMessages) {
          var isAtBottom = chatMessages.scrollHeight - chatMessages.scrollTop - chatMessages.clientHeight < 80;
          if (isAtBottom || !CHAT._userScrolledUp) {
            chatMessages.scrollTop = chatMessages.scrollHeight;
          }
        }
      });
    }
  } else if (evt.type === "thinking_delta") {
    // CoT (thinking) display — R6: dedicated .chat-thinking-bubble <details>.
    // Structural TTS/copy exclusion: content NOT pushed to contentParts and
    // class is NOT .chat-bubble, so TTS auto-play / manual / copy never see it.
    if (CHAT._firstContent) {
      CHAT._firstContent = false;
      if (els.statusEl) els.statusEl.textContent = "応答中...";
    }
    if (!t.assistantDiv) {
      t.assistantDiv = _createAssistantDiv();
    }
    if (!t.thinkingDetails) {
      t.thinkingDetails = document.createElement("details");
      t.thinkingDetails.className = "chat-thinking-bubble";
      safeSetHTML(
        t.thinkingDetails,
        '<summary>' +
          '<span class="chat-thinking-summary-left">' +
          '<i data-lucide="brain"></i> <strong>思考</strong></span>' +
          '<span class="chat-tool-chevron"><i data-lucide="chevron-right"></i></span>' +
          '<span class="chat-tool-status">処理中...</span></summary>' +
          '<div class="chat-thinking-body"></div>',
      );
      // Keep thinking block at the head of the assistant div
      t.assistantDiv.insertBefore(t.thinkingDetails, t.assistantDiv.firstChild);
      t.thinkingContent = "";
      N.Core.refreshIcons();
    }
    t.thinkingContent += evt.content;
    const thinkBody = t.thinkingDetails.querySelector(
      ".chat-thinking-body",
    );
    // rAF-batched DOM update (independent of text_delta batching)
    if (!t.thinkingRafPending) {
      t.thinkingRafPending = true;
      requestAnimationFrame(function() {
        t.thinkingRafPending = false;
        if (thinkBody) thinkBody.textContent = t.thinkingContent;
        if (chatMessages) {
          var isAtBottom = chatMessages.scrollHeight - chatMessages.scrollTop - chatMessages.clientHeight < 80;
          if (isAtBottom || !CHAT._userScrolledUp) {
            chatMessages.scrollTop = chatMessages.scrollHeight;
          }
        }
      });
    }
  } else if (evt.type === "tool_call") {
    CHAT._firstContent = false;
    if (!t.assistantDiv) {
      t.assistantDiv = _createAssistantDiv();
    }
    // End current text bubble — next text_delta will create a new one
    _closeTextBubble();
    const toolDiv = N.Chat.tools.append("tool_call", evt, t.assistantDiv);
    t.contentParts.push({ type: "tool_call", div: toolDiv, id: evt.id, name: evt.name });
    // status bar mirrors the chip's narrative label (no raw tool name);
    // image_generate keeps its dedicated text (image_gen_start has its own spinner)
    if (evt.name === "image_generate") {
      safeSetHTML(els.statusEl,
        '<i data-lucide="image"></i> 画像を生成中...');
    } else {
      safeSetHTML(els.statusEl,
        '<i data-lucide="' + N.Chat.tools.icon(evt.name) + '"></i> ' +
        esc(N.Chat.tools.label(evt.name)));
    }
  } else if (evt.type === "tool_result") {
    N.Chat.tools.append("tool_result", evt);
    _closeTextBubble(); // ensure next text_delta creates new bubble
    t.contentParts.push({ type: "tool_result", id: evt.id, result: evt.result });
    if (els.statusEl) els.statusEl.textContent = "応答中...";
  } else if (evt.type === "memory_activity") {
    if (evt.preliminary) {
      _mem("update")(evt.retrieved, undefined, undefined, undefined);
    } else {
      _mem("update")(evt.retrieved, evt.saved, evt.goals, evt.promises);
    }
    if (_memoryActivityTimer) clearTimeout(_memoryActivityTimer);
    _memoryActivityTimer = setTimeout(function() { N.Chat.core.loadCommitments(); }, 500);
    if (els.statusEl) els.statusEl.textContent = "";
  } else if (evt.type === "inventory_update") {
    N.Chat.equipment.update(evt.update);
  } else if (evt.type === "context_update") {
    try {
      var _cu = evt.update || {};
      if (_cu.emotion) {
        window.dispatchEvent(new CustomEvent("emotion-changed", { detail: _cu }));
      }
    } catch (_e) { console.warn("[context_update] handle failed:", _e); }
  } else if (evt.type === "character_flag") {
    N.Chat.showCharacterFlag(t.assistantDiv, evt.violation, evt.detail);
  } else if (evt.type === "session_summarized") {
    _mem("sessionSummarized")(evt.summary);
  } else if (evt.type === "context_compressed") {
    _mem("contextCompressed")(evt);
  } else if (evt.type === "image_gen_start") {
    N.Chat.tools.showGenSpinner(evt);
  } else if (evt.type === "image_gen_result") {
    N.Chat.tools.showGenResult(evt);
  } else if (evt.type === "debug_info") {
    console.debug("[debug_info received]", Object.keys(evt));
    N.Chat.core.debug(t.assistantDiv, evt);
  } else if (evt.type === "error") {
    removeTypingIndicator();
    toast("エラー: " + evt.message, "error");
    if (els.statusEl) els.statusEl.textContent = "";
    _endTurnSession();
    return;
  } else if (evt.type === "done") {
    _finalizeTurn(evt);
  }
}

function _finalizeTurn(evt) {
  var t = _turn;
  var els = _els();
  // F3: render all text parts as final markdown
  // 空delta由来の空バブルを除去（ツール合間の空バブル対策）
  for (const part of t.contentParts) {
    if (part.type === "text" && part.bubble && !(part.content || "").trim()) {
      part.bubble.remove();
    }
  }
  let allText = "";
  for (const part of t.contentParts) {
    if (part.type === "text" && part.bubble && part.content) {
      safeSetHTML(part.bubble, safeMarkdown(part.content));
      part.bubble.querySelectorAll("img").forEach((img) => {
        img.style.cssText =
          "max-width:100%;border-radius:8px;cursor:pointer;margin:8px 0;";
        img.addEventListener("click", () =>
          N.Chat.attachments.openViewer(img.src, "image"),
        );
      });
      allText += part.content + "\n";
    }
  }
  // TE04: Auto-play TTS for all text
  var voiceAutoPlay = document.getElementById("chat-voice-auto-play");
  var voiceStreaming = document.getElementById("chat-voice-streaming");
  if (voiceAutoPlay && voiceAutoPlay.checked && allText.trim()) {
    if (voiceStreaming && voiceStreaming.checked && Nous.Chat.ttsStream && Nous.Chat.ttsStream.finish) {
      var _msgEls = document.querySelectorAll("#chat-messages .chat-msg");
      var _msgEl = _msgEls.length ? _msgEls[_msgEls.length - 1] : null;
      Nous.Chat.ttsStream.finish(allText.trim(), _msgEl);
    } else {
      N.Chat.tts.autoPlay(allText.trim());
    }
  }
  // Clean up: remove assistant div if it has no content (text, tools, or thinking)
  if (t.assistantDiv) {
    const hasToolCalls = t.assistantDiv.querySelector(".chat-tool-call");
    const hasTextBubbles = t.assistantDiv.querySelector(".chat-bubble");
    const hasThinking = t.assistantDiv.querySelector(".chat-thinking-bubble");
    if (!hasToolCalls && !hasTextBubbles && !hasThinking) {
      t.assistantDiv.remove();
    }
  }
  var wasRemote = !t.isLocal;
  _endTurnSession();
  if (els.statusEl) els.statusEl.textContent = "ちょっと考えてる…";
  // Show truncation notice when response was auto-continued
  if (evt.truncated) {
    const notice = document.createElement("div");
    notice.className = "chat-truncation-notice";
    notice.textContent = "（つづき）";
    // e1: 空応答時はassistantDivがnullのためガード
    if (t.assistantDiv) {
      // Insert after the last text bubble inside assistantDiv
      const lastBubble = t.assistantDiv.querySelector(".chat-bubble:last-of-type");
      if (lastBubble) {
        lastBubble.insertAdjacentElement("afterend", notice);
      } else {
        t.assistantDiv.appendChild(notice);
      }
    }
  }
  // Show token usage info when available
  if (evt.usage && t.assistantDiv) {
    const u = evt.usage;
    const tokenInfo = document.createElement("div");
    tokenInfo.className = "chat-token-info";
    tokenInfo.style.cssText = "font-size:0.72rem;color:var(--text-muted);margin-top:4px;opacity:0.7;";
    tokenInfo.textContent = "🔤 " + u.prompt_tokens + "↑ " + u.completion_tokens + "↓ = " + u.total_tokens + " 合計";
    t.assistantDiv.appendChild(tokenInfo);
  }
  // Set message IDs from server
  if (evt.user_msg_id || evt.assistant_msg_id) {
    if (evt.user_msg_id) {
      const userMsgs = document.querySelectorAll(".chat-msg.user");
      const lastUser = userMsgs[userMsgs.length - 1];
      // Only set if not already assigned (retry may reuse existing msgId)
      if (lastUser && !lastUser.dataset.msgId) {
        lastUser.dataset.msgId = evt.user_msg_id;
      }
    }
    if (evt.assistant_msg_id && t.assistantDiv) {
      t.assistantDiv.dataset.msgId = evt.assistant_msg_id;
    }
  }
  // Viewer tab (other client / late join): pull the canonical history
  // — the sender keeps its live-rendered DOM plus the msg_ids above.
  if (wasRemote && N.Chat.history && typeof N.Chat.history.restore === "function") {
    N.Chat.history.restore(false);
  }
}

// Hub message: seq dedupe (EventSource id:) → turn_started lifecycle →
// per-event dispatch. Backlog replay while idle (page load, post-cancel)
// is swallowed: deltas drop, done re-syncs via history reload.
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
    removeTypingIndicator();
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
    _beginTurnSession(null);
    appendChatMessage("user", evt.user_message || "");
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
      _handleChatEvent(evt);
    }
    return;
  }
  _handleChatEvent(evt);
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
  _endTurnSession();
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
// ------------------------------------------------------------------
var MONOLOGUE_URL = "/api/memory/wiring/stream";
var _monologuePersona = null;
var _monologueMaxSeq = 0;

function _tsEpoch(ts) {
  if (typeof ts !== "string" || !ts) return NaN;
  var n = Date.parse(ts);
  return isFinite(n) ? n : NaN;
}

// First message node strictly newer than the whisper's timestamp —
// epoch-ms comparison (ISO strings with mixed offsets sort wrong).
function findMonologueAnchor(container, ts) {
  var epoch = _tsEpoch(ts);
  if (isNaN(epoch)) return null;
  var nodes = container.children;
  for (var i = 0; i < nodes.length; i++) {
    var t = _tsEpoch(nodes[i].dataset && nodes[i].dataset.ts);
    if (!isNaN(t) && t > epoch) return nodes[i];
  }
  return null;
}

// Re-slot every existing whisper after history prepends new older
// messages (loadOlderMessages): remove-free reorder in place.
function reslotMonologueBubbles() {
  var container = findChatLogContainer();
  if (!container) return;
  var movable = [];
  container.querySelectorAll(".chat-monologue-bubble").forEach(function (b) {
    if (!isNaN(_tsEpoch(b.dataset && b.dataset.ts))) movable.push(b);
  });
  movable.sort(function (a, b) { return _tsEpoch(a.dataset.ts) - _tsEpoch(b.dataset.ts); });
  movable.forEach(function (b) {
    container.insertBefore(b, findMonologueAnchor(container, b.dataset.ts));
  });
}

function appendMonologueBubble(text, ts, kind) {
  if (!text || typeof text !== "string") return;
  var container = findChatLogContainer();
  if (!container) return;
  var isExploration = kind === "exploration";
  var bubble = document.createElement("details");
  bubble.className = "chat-monologue-bubble";
  bubble.dataset.ts = ts || "";
  if (isExploration) bubble.dataset.kind = "exploration";
  var summary = document.createElement("summary");
  summary.textContent = isExploration ? "🔍 調べたこと" : "💭 独り言";
  // The canonical reader is the memory modal (keyless preview — no
  // Edit/Delete); suppress the native details toggle so the click does
  // exactly one legible thing. CSP-safe: listener, no inline handler.
  summary.addEventListener("click", function (e) {
    e.preventDefault();
    if (N.Components && N.Components.memModal &&
        typeof N.Components.memModal.openMemory === "function") {
      N.Components.memModal.openMemory({
        content: text,
        tags: isExploration ? ["monologue", "exploration"] : ["monologue"],
      });
    }
  });
  // Timestamp rides in the summary, not the details body: the bubble
  // renders collapsed (the modal is the canonical reader), so a label
  // inside the body would stay display:none and never be seen.
  if (!isNaN(_tsEpoch(ts))) {
    var timeSpan = document.createElement("span");
    timeSpan.className = "chat-time chat-monologue-time";
    timeSpan.textContent = fmtStamp(ts);
    summary.appendChild(timeSpan);
  }
  var body = document.createElement("div");
  body.className = "chat-monologue-text";
  body.textContent = text; // CSP-safe: textContent, never parsed as HTML
  bubble.appendChild(summary);
  bubble.appendChild(body);
  // Restored whispers carry their ISO timestamp — slot them between
  // messages in conversation order instead of the tail. Live whispers
  // (no parseable timestamp) keep append-at-end, which IS their order.
  var anchor = findMonologueAnchor(container, ts);
  if (anchor) container.insertBefore(bubble, anchor);
  else container.appendChild(bubble);
  // Follow the stream only while the user is already at the bottom
  if (container.scrollHeight - container.scrollTop - container.clientHeight < 80) {
    container.scrollTop = container.scrollHeight;
  }
}

function handleMonologueWiring(data) {
  try {
    var evt = JSON.parse(data);
    if (!evt || evt.kind !== "monologue") return;
    // The endpoint flushes its whole ring buffer (last_seq=0) on every
    // connect, so a reconnect re-delivers old monologues as if fresh.
    // Same seq dedupe as the panel's pushWiringEvent.
    var seq = Number(evt.seq);
    if (isFinite(seq) && seq > 0) {
      if (seq <= _monologueMaxSeq) return;
      _monologueMaxSeq = seq;
    }
    var meta = evt.meta || {};
    // Stale socket from a previous persona: drop quietly.
    if (meta.persona && window.S && meta.persona !== window.S.persona) return;
    // kind="exploration" は reload (restoreMonologueBubbles) と同じ 🔍 ラベルにする
    appendMonologueBubble(meta.text, meta.timestamp, meta.kind);
  } catch (err) {
    console.warn("[monologue wiring parse]:", err.message);
  }
}

function connectMonologueStream(persona) {
  _monologuePersona = persona || (window.S && window.S.persona) || null;
  // Persona switch: replayed buffer entries for the new persona must
  // render once — start the seq guard from zero (clearWiring's twin).
  _monologueMaxSeq = 0;
  N.Core.connectStream("wiring-chat", {
    url: function () {
      return _monologuePersona
        ? MONOLOGUE_URL + "?persona=" + encodeURIComponent(_monologuePersona)
        : null;
    },
    handlers: {
      wiring: function (e) { handleMonologueWiring(e.data); },
    },
  });
}

// Persona select (init + change) funnels through N.Core.connectSSE —
// mirror it so the monologue AND chat-events streams always follow the
// active persona (wraps once, even under script double-load).
if (typeof N.Core.connectSSE === "function" && !N.Core._monologueConnectWrapped) {
  N.Core._monologueConnectWrapped = true;
  (function () {
    var _origConnect = N.Core.connectSSE;
    N.Core.connectSSE = function (persona) {
      var r = _origConnect.apply(this, arguments);
      try { connectMonologueStream(persona); } catch (_e) {}
      try { connectChatEvents(persona); } catch (_e) {}
      return r;
    };
  })();
}

// ------------------------------------------------------------------
// Expose on N.Chat
// ------------------------------------------------------------------
N.Chat.send = chatSend;
N.Chat.cancel = chatCancel;
N.Chat.ui = {
  append: appendChatMessage,
  showTyping: showTypingIndicator,
  removeTyping: removeTypingIndicator,
  scrollToBottom: scrollToBottom,
  findLog: findChatLogContainer,
};
N.Chat.monologue = {
  append: appendMonologueBubble,
  reslot: reslotMonologueBubbles,
  handle: handleMonologueWiring,
  connect: connectMonologueStream,
};
// tool.called (source=introspection) ハンドラ — connectChatEvents が参照し、
// テストからも直接検証できるよう公開する。
N.Chat.introspectionTool = { handle: handleToolCalledEvent };

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

})(window.Nous);
