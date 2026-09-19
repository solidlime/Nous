/* =================================================================
   CHAT HISTORY RENDER — segment bubble renderer + shared message render
   Chunk 1/3 of chat-history.js (split: render / session / restore).
   Namespace: N.Chat._history.renderMessages + appendSegments,
   N.Chat.history.renderSegments.
   Depends on: chat-markdown.js, send/render.js (N.Chat.ui.append),
   chat-tools.js, chat-attachments.js.
   ================================================================= */
;(function(N) {
var C = N.Core;
var api = C.api, esc = C.esc, toast = C.toast, safeSetHTML = C.safeSetHTML;
var showConfirm = C.showConfirm, showAlert = C.showAlert;
var truncate = C.truncate, relativeTime = C.relativeTime, fmtDate = C.fmtDate;
var fmtStamp = C.fmtStamp;
var safeMarkdown = N.Chat.markdown && N.Chat.markdown.render;
var appendChatMessage = N.Chat.ui && N.Chat.ui.append;
"use strict";
var S = window.S;

function _appendSegmentsToBubble(msg, msgDiv) {
  // Graceful degradation: callers pass container.querySelector(".chat-msg:last-child"),
  // which is null when the bubble was never appended (e.g. sanitizer fallback).
  if (!msg || !msgDiv || typeof msgDiv.querySelector !== "function") return;
  if (!msg.segments || !msg.segments.length) return;
  // Conversation-order normalization: the turn persists text before
  // thinking within a round (two separate accumulators flush text
  // first), but live streaming shows ALL thinking merged into ONE
  // details bubble at the head of the message. Fold every thinking
  // segment into a single head bubble so a reload matches the live
  // view — for new and already-stored turns alike.
  var thinkingText = "";
  var flow = [];
  for (var fi = 0; fi < msg.segments.length; fi++) {
    if (msg.segments[fi].type === "thinking") {
      thinkingText += msg.segments[fi].content || "";
    } else {
      flow.push(msg.segments[fi]);
    }
  }
  var segs = thinkingText.trim()
    ? [{ type: "thinking", content: thinkingText }].concat(flow)
    : flow;
  var toolCallDivs = {};
  for (var si = 0; si < segs.length; si++) {
    var seg = segs[si];
    if (seg.type === "text") {
      if (!seg.content || !seg.content.trim()) continue;
      var bubble = document.createElement("div");
      bubble.className = "chat-bubble";
      safeSetHTML(bubble, safeMarkdown(seg.content));
      bubble.querySelectorAll("img").forEach(function(img) {
        img.style.cssText = "max-width:100%;border-radius:8px;cursor:pointer;margin:8px 0;";
        img.addEventListener("click", function() { N.Chat.attachments.openViewer(img.src, "image"); });
      });
      var timeDiv = msgDiv.querySelector(".chat-time");
      if (timeDiv) msgDiv.insertBefore(bubble, timeDiv);
      else msgDiv.appendChild(bubble);
    } else if (seg.type === "thinking") {
      // CoT restore (R7): same .chat-thinking-bubble <details> as streaming.
      // NOT .chat-bubble — excluded from TTS manual / copy collectors.
      if (!seg.content || !seg.content.trim()) continue;
      var thinkDiv = document.createElement("details");
      thinkDiv.className = "chat-thinking-bubble";
      safeSetHTML(thinkDiv,
        '<summary>' +
        '<span class="chat-thinking-summary-left">' +
        '<i data-lucide="brain"></i> <strong>思考</strong></span>' +
        '<span class="chat-tool-chevron"><i data-lucide="chevron-right"></i></span>' +
        '<span class="chat-tool-status"><i data-lucide="check"></i> 完了</span></summary>' +
        '<div class="chat-thinking-body"></div>');
      var thinkBody = thinkDiv.querySelector(".chat-thinking-body");
      // Guard: sanitizer fallback (textContent) leaves no .chat-thinking-body —
      // skip the segment instead of failing the whole history restore.
      if (thinkBody) thinkBody.textContent = seg.content;
      var timeDiv3 = msgDiv.querySelector(".chat-time");
      if (timeDiv3) msgDiv.insertBefore(thinkDiv, timeDiv3);
      else msgDiv.appendChild(thinkDiv);
    } else if (seg.type === "tool_call") {
      var inputStr;
      try { inputStr = JSON.stringify(seg.input, null, 2); } catch (e) { inputStr = String(seg.input); }
      var div = document.createElement("div");
      div.className = "chat-tool-call done";
      if (seg.id) div.dataset.toolId = seg.id;
      // Immersive chip label/icon (same vocabulary as live chips);
      // raw name kept in the title + details for debugging.
      var toolApi = N.Chat.tools || {};
      var toolName = typeof toolApi.label === "function" ? toolApi.label(seg.name) : (seg.name || "");
      var toolGlyph = typeof toolApi.icon === "function" ? toolApi.icon(seg.name) : "wrench";
      safeSetHTML(div, '<details><summary>' +
        '<span class="chat-tool-summary-left">' +
        '<i data-lucide="' + toolGlyph + '"></i> <strong title="' + esc(seg.name || "") + '">' +
        esc(toolName) + '</strong></span>' +
        '<span class="chat-tool-chevron"><i data-lucide="chevron-right"></i></span>' +
        '<span class="chat-tool-status"><i data-lucide="check"></i> 完了</span></summary>' +
        '<pre class="chat-tool-detail">' + esc(inputStr) + '</pre></details>');
      if (seg.id) toolCallDivs[seg.id] = div;
      var timeDiv2 = msgDiv.querySelector(".chat-time");
      if (timeDiv2) msgDiv.insertBefore(div, timeDiv2);
      else msgDiv.appendChild(div);
    } else if (seg.type === "tool_result") {
      var toolDiv = seg.id ? toolCallDivs[seg.id] : null;
      if (toolDiv) {
        var resultStr;
        try { resultStr = typeof seg.result === "object" ? JSON.stringify(seg.result, null, 2) : String(seg.result); }
        catch (e) { resultStr = String(seg.result); }
        var details = toolDiv.querySelector("details");
        if (details) {
          var resultPre = document.createElement("pre");
          resultPre.className = "chat-tool-detail chat-tool-result-content";
          resultPre.textContent = resultStr;
          details.appendChild(resultPre);
        }
        // 画像生成結果があればレンダリング（履歴復元時）
        if (seg.id && msg.tool_calls) {
          var tc = msg.tool_calls.find(function(t) { return t.id === seg.id; });
          if (tc && tc.result_raw && tc.result_raw.images && tc.result_raw.images.length) {
            tc.result_raw.images.forEach(function(img) {
              var card = document.createElement("div");
              card.className = "chat-image-gen-card";
              var imgEl = document.createElement("img");
              if (img.url) {
                imgEl.src = img.url;
              } else if (img.base64) {
                try {
                  var binary = atob(img.base64);
                  var bytes = new Uint8Array(binary.length);
                  for (var b = 0; b < binary.length; b++) bytes[b] = binary.charCodeAt(b);
                  var blob = new Blob([bytes], { type: "image/png" });
                  imgEl.src = URL.createObjectURL(blob);
                } catch (e) {
                  imgEl.src = "data:image/png;base64," + img.base64;
                }
              }
              imgEl.alt = img.revised_prompt || "生成画像";
              imgEl.title = img.revised_prompt || "";
              imgEl.dataset.revisedPrompt = img.revised_prompt || "";
              imgEl.dataset.negativePrompt = img.negative_prompt || "";
              imgEl.onerror = function() {
                imgEl.style.display = "none";
                var errDiv = document.createElement("div");
                errDiv.className = "image-gen-error";
                errDiv.textContent = "⚠️ 画像のデコードに失敗しました";
                card.insertBefore(errDiv, card.firstChild);
              };
              imgEl.onclick = function() {
                if (typeof N.Chat.attachments.openViewer === "function") {
                  N.Chat.attachments.openViewer(imgEl.src, "image", null, {
                    revised_prompt: imgEl.dataset.revisedPrompt,
                    negative_prompt: imgEl.dataset.negativePrompt,
                  });
                } else {
                  window.open(imgEl.src, "_blank");
                }
              };
              var meta = document.createElement("div");
              meta.className = "image-gen-meta";
              var rp = img.revised_prompt || "";
              if (rp) {
                var promptSpan = document.createElement("span");
                promptSpan.textContent = rp.length > 80 ? rp.substring(0, 80) + "..." : rp;
                promptSpan.style.fontStyle = "italic";
                meta.appendChild(promptSpan);
              }
              var sizeSpan = document.createElement("span");
              sizeSpan.textContent = (tc.result_raw.provider || "") + " · " + (img.size || "");
              meta.appendChild(sizeSpan);
              card.appendChild(imgEl);
              card.appendChild(meta);
              toolDiv.parentNode.insertBefore(card, toolDiv.nextSibling);
            });
          }
        }
      }
    }
  }
  // Remove empty bubbles (初期の空バブル＋空textセグメント由来を全除去)
  msgDiv.querySelectorAll(".chat-bubble").forEach(function(b) {
    if (!(b.textContent || "").trim() && !b.querySelector("img,video,audio,canvas")) b.remove();
  });
  // Set time — full stamp (YYYY/MM/DD HH:MM) from the ISO `ts` payload;
  // legacy payloads without ts fall back to the HH:MM label.
  var timeEl = msgDiv.querySelector(".chat-time");
  if (timeEl) timeEl.textContent = fmtStamp(msg.ts) || msg.time || "";
}


function renderMessages(msgs, opts) {
  var prepend = !!(opts && opts.prepend);
  var container = document.getElementById("chat-messages");
  var anchor = prepend ? container.firstChild : null;
  for (const msg of msgs) {
    var marker = prepend ? container.lastChild : null;

    // ── Segments-based rendering (F2: correct interleaving) ──
    if (msg.segments) {
      appendChatMessage(msg.role, "", msg.time, false, msg.id, msg.ts);
      _appendSegmentsToBubble(msg, container.querySelector(".chat-msg:last-child"));
    } else {
      // ── Legacy: no segments (backward compat) ──
      if (msg.role === "assistant" && msg.tool_calls?.length) {
        for (const tc of msg.tool_calls) {
          const div = document.createElement("div");
          div.className = "chat-tool-call done";
          let inputStr;
          try {
            inputStr = JSON.stringify(tc.input, null, 2);
          } catch (e) {
            inputStr = String(tc.input);
          }
          let resultStr;
          try {
            resultStr =
              typeof tc.result === "object"
                ? JSON.stringify(tc.result, null, 2)
                : String(tc.result);
          } catch (e) {
            resultStr = String(tc.result);
          }
          safeSetHTML(div,
            '<details><summary>' +
            '<span class="chat-tool-summary-left">' +
            '<i data-lucide="wrench"></i> <strong>' +
            esc(tc.name) +
            '</strong></span>' +
            '<span class="chat-tool-chevron"><i data-lucide="chevron-right"></i></span>' +
            '<span class="chat-tool-status"><i data-lucide="check"></i> 完了</span></summary>' +
            '<pre class="chat-tool-detail">' +
            esc(inputStr) +
            "</pre>" +
            '<pre class="chat-tool-detail chat-tool-result-content">' +
            esc(resultStr) +
            "</pre></details>");
          container.appendChild(div);
        }
      }
      // 空本文ではバブルを作らない（ツールのみのlegacyメッセージ対策）
      if (msg.content && String(msg.content).trim()) {
        appendChatMessage(
          msg.role,
          msg.content,
          msg.time,
          msg.role === "assistant",
          msg.id,
          msg.ts,
        );
      }
      if (msg.role !== "assistant" && msg.tool_calls?.length) {
        for (const tc of msg.tool_calls) {
          const div = document.createElement("div");
          div.className = "chat-tool-call done";
          let inputStr;
          try {
            inputStr = JSON.stringify(tc.input, null, 2);
          } catch (e) {
            inputStr = String(tc.input);
          }
          let resultStr;
          try {
            resultStr =
              typeof tc.result === "object"
                ? JSON.stringify(tc.result, null, 2)
                : String(tc.result);
          } catch (e) {
            resultStr = String(tc.result);
          }
          safeSetHTML(div,
            '<details><summary>' +
            '<span class="chat-tool-summary-left">' +
            '<i data-lucide="wrench"></i> <strong>' +
            esc(tc.name) +
            '</strong></span>' +
            '<span class="chat-tool-chevron"><i data-lucide="chevron-right"></i></span>' +
            '<span class="chat-tool-status"><i data-lucide="check"></i> 完了</span></summary>' +
            '<pre class="chat-tool-detail">' +
            esc(inputStr) +
            "</pre>" +
            '<pre class="chat-tool-detail chat-tool-result-content">' +
            esc(resultStr) +
            "</pre></details>");
          container.appendChild(div);
        }
      }
    }

    // 追加ロード: このメッセージで生成した要素を先頭（anchor 前）へ移動
    if (prepend && marker) {
      var el = marker.nextSibling;
      while (el) {
        var next = el.nextSibling;
        container.insertBefore(el, anchor);
        el = next;
      }
    }
  }
}
// ------------------------------------------------------------------
// Expose on N.Chat (chunk 1/3 — render API + internal hooks)
// ------------------------------------------------------------------
N.Chat._history = N.Chat._history || {};
N.Chat._history.appendSegments = _appendSegmentsToBubble;
N.Chat._history.renderMessages = renderMessages;
N.Chat.history = N.Chat.history || {};
N.Chat.history.renderSegments = _appendSegmentsToBubble;
})(window.Nous);
