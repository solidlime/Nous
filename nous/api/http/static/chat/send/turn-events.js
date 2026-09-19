/* =================================================================
   CHAT SEND TURN-EVENTS — per-event streaming renderer + turn finalize
   Chunk 4/5 of chat-send.js (_handleChatEvent / _finalizeTurn).
   Reached from send/turn.js's hub dispatch via N.Chat._send.handleEvent.
   Depends on: send/render.js (N.Chat._send.createAssistantDiv /
   createTextBubble / autoScroll + N.Chat.ui.removeTyping),
   send/turn.js (N.Chat._send.els / turn / closeTextBubble /
   emitChatSSE / endTurnSession), send/pending.js
   (N.Chat._send.flushPending), chat-core.js (state), chat-tools.js.
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

// memoryPanel is registered by chat-memory-panel.js; noop when absent
// (e.g. panel script failed to load) so streaming never crashes on it.
function _mem(fn) {
  var mp = (N.Chat && N.Chat.memoryPanel) || {};
  return typeof mp[fn] === "function" ? mp[fn].bind(mp) : function () {};
}

function _handleChatEvent(evt) {
  var t = N.Chat._send.turn();
  var els = N.Chat._send.els();
  var chatMessages = t ? t.chatMessages : null;
  N.Chat._send.emitChatSSE(evt);

  if (evt.type === "text_delta") {
    if (!evt.content) return;
    if (CHAT._firstContent) {
      CHAT._firstContent = false;
      if (els.statusEl) els.statusEl.textContent = "応答中...";
    }
    // F3: content_parts — create or continue text bubble inside assistant div
    if (!t.assistantDiv) {
      t.assistantDiv = N.Chat._send.createAssistantDiv();
    }
    // If the last part was a tool call, start a new text bubble
    const lastPart = t.contentParts[t.contentParts.length - 1];
    if (!lastPart || lastPart.type !== "text") {
      t.currentTextBubble = N.Chat._send.createTextBubble(t.assistantDiv);
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
        N.Chat._send.autoScroll(chatMessages);
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
      t.assistantDiv = N.Chat._send.createAssistantDiv();
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
        N.Chat._send.autoScroll(chatMessages);
      });
    }
  } else if (evt.type === "tool_call") {
    CHAT._firstContent = false;
    if (!t.assistantDiv) {
      t.assistantDiv = N.Chat._send.createAssistantDiv();
    }
    // End current text bubble — next text_delta will create a new one
    N.Chat._send.closeTextBubble();
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
    N.Chat._send.closeTextBubble(); // ensure next text_delta creates new bubble
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
  } else if (evt.type === "response_replaced") {
    // RepairStep: 応答がキャラ修復で再生成・置換された — 最後のテキストバブルを
    // data.content で差し替え、safeMarkdown で再描画する（_finalizeTurn と同じ描画）。
    try {
      if (!t.assistantDiv) t.assistantDiv = N.Chat._send.createAssistantDiv();
      var lastText = null;
      for (var _i = t.contentParts.length - 1; _i >= 0; _i--) {
        if (t.contentParts[_i].type === "text" && t.contentParts[_i].bubble) {
          lastText = t.contentParts[_i];
          break;
        }
      }
      if (!lastText) {
        lastText = { type: "text", bubble: N.Chat._send.createTextBubble(t.assistantDiv), content: "" };
        t.contentParts.push(lastText);
      }
      lastText.content = evt.content || "";
      if (t.contentParts[t.contentParts.length - 1] === lastText) t.currentTextContent = lastText.content;
      if (lastText.bubble) safeSetHTML(lastText.bubble, safeMarkdown(lastText.content));
    } catch (_e) { console.warn("[response_replaced] handle failed:", _e); }
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
    N.Chat.ui.removeTyping();
    toast("エラー: " + evt.message, "error");
    if (els.statusEl) els.statusEl.textContent = "";
    N.Chat._send.endTurnSession();
    N.Chat._send.flushPending();
    return;
  } else if (evt.type === "done") {
    _finalizeTurn(evt);
  }
}

function _finalizeTurn(evt) {
  var t = N.Chat._send.turn();
  var els = N.Chat._send.els();
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
  N.Chat._send.endTurnSession();
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
  // A held message (409) waits for this turn to end — send it now.
  N.Chat._send.flushPending();
}
// ------------------------------------------------------------------
// Expose on N.Chat (chunk 4/5 — event renderer hook)
// ------------------------------------------------------------------
N.Chat._send = N.Chat._send || {};
N.Chat._send.handleEvent = _handleChatEvent;
})(window.Nous);
