/* =================================================================
   CHAT SEND — Message sending, streaming, typing indicator, rendering
   Extracted from chat.js (Phase 3, Batch 2)
   ================================================================= */
;(function(N) {
var C = N.Core;
var api = C.api, esc = C.esc, toast = C.toast, safeSetHTML = C.safeSetHTML;
var showConfirm = C.showConfirm, showAlert = C.showAlert;
var truncate = C.truncate, relativeTime = C.relativeTime, fmtDate = C.fmtDate;
var safeMarkdown = N.Chat.markdown && N.Chat.markdown.render;
"use strict";
var S = window.S;

var CHAT = N.Chat.state;
var _memoryActivityTimer = null;

// ------------------------------------------------------------------
// Append a chat message to the DOM
// ------------------------------------------------------------------
function appendChatMessage(role, content, timeStr, isMarkdown, msgId) {
  const container = document.getElementById("chat-messages");
  // Remove welcome message if present
  const welcome = container.querySelector(".chat-welcome");
  if (welcome) welcome.remove();

  // Calculate message index (0-based position in session)
  const msgIndex = container.querySelectorAll(".chat-msg").length;

  const div = document.createElement("div");
  div.className = "chat-msg " + role;
  div.dataset.msgIndex = msgIndex;
  div.dataset.msgId = msgId || "";
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
  timeDiv.textContent =
    timeStr ||
    new Date().toLocaleTimeString("ja-JP", {
      hour: "2-digit",
      minute: "2-digit",
    });
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
  const timeDiv = document.createElement("div");
  timeDiv.className = "chat-time";
  timeDiv.textContent = new Date().toLocaleTimeString("ja-JP", {
    hour: "2-digit",
    minute: "2-digit",
  });
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
  CHAT.streaming = false;
  if (CHAT.abortController) {
    CHAT.abortController.abort();
    CHAT.abortController = null;
  }
  const cancelBtn = document.getElementById("chat-cancel-btn");
  const sendBtn = document.getElementById("chat-send-btn");
  const statusEl = document.getElementById("chat-status");
  if (cancelBtn) cancelBtn.style.display = "none";
  if (sendBtn) sendBtn.style.display = "";
  if (statusEl) statusEl.textContent = "中断しました";
  removeTypingIndicator();
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

  CHAT.streaming = true;
  CHAT._streamingSince = Date.now();
  CHAT.abortController = new AbortController();
  sendBtn.style.display = "none";
  if (cancelBtn) cancelBtn.style.display = "";
  statusEl.textContent = "記憶処理中...";
  CHAT._firstContent = true;

  const sessionId = N.Chat.history.getSessionId();
  // F3: content_parts-based rendering — tracks interleaved text/tool_call/tool_result
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

  try {
    const response = await fetch("/api/chat/" + encodeURIComponent(S.persona), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        message: message,
        session_id: sessionId,
        images: images.length > 0 ? images : undefined,
        debug: document.getElementById("chat-debug-mode")?.checked || false,
      }),
      signal: CHAT.abortController.signal,
    });

    if (!response.ok) {
      throw new Error("HTTP " + response.status);
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    let streamDone = false;
    var _rafPending = false;
    var _thinkingRafPending = false;
    var _scrollListener = null;
    var chatMessages = document.getElementById("chat-messages");

    removeTypingIndicator();

    // Track user scroll intent during streaming
    CHAT._userScrolledUp = false;
    if (chatMessages) {
      _scrollListener = function _onChatScroll() {
        var threshold = 80;
        CHAT._userScrolledUp = chatMessages.scrollHeight - chatMessages.scrollTop - chatMessages.clientHeight > threshold;
      };
      chatMessages.addEventListener("scroll", _scrollListener, { passive: true });
    }

    while (true) {
      const readPromise = reader.read();
      const timeoutPromise = new Promise((_, reject) =>
        setTimeout(() => reject(new Error("Stream timeout: no data for 120s")), 120000),
      );
      const { value, done } = await Promise.race([readPromise, timeoutPromise]);
      if (done) break;
      buffer += decoder.decode(value, { stream: true });

      const lines = buffer.split("\n");
      buffer = lines.pop(); // keep incomplete line

      for (const line of lines) {
        if (!line.startsWith("data: ")) continue;
        let evt;
        try {
          evt = JSON.parse(line.slice(6));
        } catch {
          continue;
        }

        if (evt.type === "text_delta") {
          if (CHAT._firstContent) {
            CHAT._firstContent = false;
            statusEl.textContent = "応答中...";
          }
          // F3: content_parts — create or continue text bubble inside assistant div
          if (!assistantDiv) {
            assistantDiv = _createAssistantDiv();
          }
          // If the last part was a tool call, start a new text bubble
          const lastPart = contentParts[contentParts.length - 1];
          if (!lastPart || lastPart.type !== "text") {
            currentTextBubble = _createTextBubble(assistantDiv);
            currentTextContent = "";
            contentParts.push({ type: "text", bubble: currentTextBubble, content: "" });
          }
          currentTextContent += evt.content;
          contentParts[contentParts.length - 1].content = currentTextContent;

          // rAF-batched DOM update
          if (!_rafPending) {
            _rafPending = true;
            requestAnimationFrame(function() {
              _rafPending = false;
              if (currentTextBubble) {
                currentTextBubble.textContent = currentTextContent;
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
            statusEl.textContent = "応答中...";
          }
          if (!assistantDiv) {
            assistantDiv = _createAssistantDiv();
          }
          if (!thinkingDetails) {
            thinkingDetails = document.createElement("details");
            thinkingDetails.className = "chat-thinking-bubble";
            safeSetHTML(
              thinkingDetails,
              '<summary>' +
                '<span class="chat-thinking-summary-left">' +
                '<i data-lucide="brain"></i> <strong>思考</strong></span>' +
                '<span class="chat-tool-chevron"><i data-lucide="chevron-right"></i></span>' +
                '<span class="chat-tool-status">処理中...</span></summary>' +
                '<div class="chat-thinking-body"></div>',
            );
            // Keep thinking block at the head of the assistant div
            assistantDiv.insertBefore(thinkingDetails, assistantDiv.firstChild);
            thinkingContent = "";
            N.Core.refreshIcons();
          }
          thinkingContent += evt.content;
          const thinkBody = thinkingDetails.querySelector(
            ".chat-thinking-body",
          );
          // rAF-batched DOM update (independent of text_delta batching)
          if (!_thinkingRafPending) {
            _thinkingRafPending = true;
            requestAnimationFrame(function() {
              _thinkingRafPending = false;
              if (thinkBody) thinkBody.textContent = thinkingContent;
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
          if (!assistantDiv) {
            assistantDiv = _createAssistantDiv();
          }
          // End current text bubble — next text_delta will create a new one
          currentTextBubble = null;
          currentTextContent = "";
          const toolDiv = N.Chat.tools.append("tool_call", evt, assistantDiv);
          contentParts.push({ type: "tool_call", div: toolDiv, id: evt.id, name: evt.name });
          // image_generate は image_gen_start が専用のスピナー表示を行うので、
          // ここでは generic な「…を実行中」ではなく専用テキストを表示して重複を避ける
          if (evt.name === "image_generate") {
            safeSetHTML(statusEl,
              '<i data-lucide="image"></i> 画像を生成中...');
          } else {
            safeSetHTML(statusEl,
              '<i data-lucide="wrench"></i> ' + esc(evt.name) + " を実行中...");
          }
        } else if (evt.type === "tool_result") {
          N.Chat.tools.append("tool_result", evt);
          currentTextBubble = null; // ensure next text_delta creates new bubble
          currentTextContent = "";
          contentParts.push({ type: "tool_result", id: evt.id, result: evt.result });
          statusEl.textContent = "応答中...";
        } else if (evt.type === "memory_activity") {
          N.Chat.memoryPanel.update(evt.retrieved, evt.saved, evt.goals);
          if (_memoryActivityTimer) clearTimeout(_memoryActivityTimer);
          _memoryActivityTimer = setTimeout(function() { N.Chat.core.loadCommitments(); }, 500);
          statusEl.textContent = "";
        } else if (evt.type === "inventory_update") {
          N.Chat.equipment.update(evt.update);
        } else if (evt.type === "reflection_start") {
          N.Chat.memoryPanel.showReflection();
        } else if (evt.type === "reflection_done") {
          N.Chat.memoryPanel.updateReflection(evt.insights);
        } else if (evt.type === "session_summarized") {
          N.Chat.memoryPanel.sessionSummarized(evt.summary);
        } else if (evt.type === "context_compressed") {
          N.Chat.memoryPanel.contextCompressed(evt);
        } else if (evt.type === "image_gen_start") {
          N.Chat.tools.showGenSpinner(evt);
        } else if (evt.type === "image_gen_result") {
          console.log("[SSE] image_gen_result received:", Object.keys(evt), "images:", evt.images ? evt.images.length : "NONE");
          N.Chat.tools.showGenResult(evt);
        } else if (evt.type === "error") {
          removeTypingIndicator();
          toast("エラー: " + evt.message, "error");
          statusEl.textContent = "";
          streamDone = true;
          break;
        } else if (evt.type === "debug_info") {
          console.debug("[debug_info received]", Object.keys(evt));
          N.Chat.core.debug(assistantDiv, evt);
        } else if (evt.type === "done") {
          // F3: render all text parts as final markdown
          let allText = "";
          for (const part of contentParts) {
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
          if (voiceAutoPlay && voiceAutoPlay.checked && allText.trim()) {
            N.Chat.tts.autoPlay(allText.trim());
          }
          // Clean up: remove assistant div if it has no content (text, tools, or thinking)
          if (assistantDiv) {
            const hasToolCalls = assistantDiv.querySelector(".chat-tool-call");
            const hasTextBubbles = assistantDiv.querySelector(".chat-bubble");
            const hasThinking = assistantDiv.querySelector(".chat-thinking-bubble");
            if (!hasToolCalls && !hasTextBubbles && !hasThinking) {
              assistantDiv.remove();
            }
          }
          // Re-enable send immediately, keep SSE reader alive for memory_activity
          CHAT.streaming = false;
          CHAT._streamingSince = null;
          sendBtn.style.display = "";
          if (cancelBtn) cancelBtn.style.display = "none";
          statusEl.textContent = "記憶を整理中...";
          // Show truncation notice when response was auto-continued
          if (evt.truncated) {
            const notice = document.createElement("div");
            notice.className = "chat-truncation-notice";
            notice.textContent = "⚠️ 応答が長すぎたため自動継続されました";
            // Insert after the last text bubble inside assistantDiv
            const lastBubble = assistantDiv.querySelector(".chat-bubble:last-of-type");
            if (lastBubble) {
              lastBubble.insertAdjacentElement("afterend", notice);
            } else if (assistantDiv) {
              assistantDiv.appendChild(notice);
            }
          }
          // Show token usage info when available
          if (evt.usage && assistantDiv) {
            const u = evt.usage;
            const tokenInfo = document.createElement("div");
            tokenInfo.className = "chat-token-info";
            tokenInfo.style.cssText = "font-size:0.72rem;color:var(--text-muted);margin-top:4px;opacity:0.7;";
            tokenInfo.textContent = "🔤 " + u.prompt_tokens + "↑ " + u.completion_tokens + "↓ = " + u.total_tokens + " total";
            assistantDiv.appendChild(tokenInfo);
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
            if (evt.assistant_msg_id && assistantDiv) {
              assistantDiv.dataset.msgId = evt.assistant_msg_id;
            }
          }
        }
      }
      if (streamDone) break;
    }
  } catch (e) {
    removeTypingIndicator();
    if (e.name !== "AbortError") {
      toast("送信失敗: " + e.message, "error");
    }
    statusEl.textContent = "";
  } finally {
    CHAT.streaming = false;
    CHAT._streamingSince = null;
    CHAT.abortController = null;
    if (_scrollListener && chatMessages) {
      chatMessages.removeEventListener("scroll", _scrollListener);
      _scrollListener = null;
    }
    CHAT._userScrolledUp = false;
    CHAT._firstContent = false;
    _rafPending = false;
    _thinkingRafPending = false;
    sendBtn.style.display = "";
    if (cancelBtn) cancelBtn.style.display = "none";
    inputEl.focus();
    // Fallback: render markdown if stream ended without 'done' event
    // F3: iterate over all text content parts
    for (const part of contentParts) {
      if (
        part.type === "text" &&
        part.bubble &&
        part.content &&
        part.bubble.children.length === 0
      ) {
        safeSetHTML(part.bubble, safeMarkdown(part.content));
        part.bubble.querySelectorAll("img").forEach((img) => {
          img.style.cssText =
            "max-width:100%;border-radius:8px;cursor:pointer;margin:8px 0;";
          img.addEventListener("click", () => N.Chat.attachments.openViewer(img.src, "image"));
        });
      }
    }
  }
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
