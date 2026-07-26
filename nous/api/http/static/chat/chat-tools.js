/* =================================================================
   CHAT TOOLS — Tool call events, file tool calls, code execution,
   image generation, MCP tools management
   Extracted from chat.js (Phase 3, Batch 2)
   ================================================================= */
;(function(N) {
var C = N.Core;
var api = C.api, esc = C.esc, toast = C.toast, safeSetHTML = C.safeSetHTML;
var showConfirm = C.showConfirm, showAlert = C.showAlert;
var truncate = C.truncate, relativeTime = C.relativeTime, fmtDate = C.fmtDate;
var findChatLogContainer = N.Chat.ui && N.Chat.ui.findLog;
var scrollToBottom = N.Chat.ui && N.Chat.ui.scrollToBottom;
"use strict";
var S = window.S;

var CHAT = N.Chat.state;

// ------------------------------------------------------------------
// Append tool call/result event to the DOM
// ------------------------------------------------------------------
function appendToolEvent(eventType, data, targetDiv) {
  const container = document.getElementById("chat-messages");

  if (eventType === "tool_call") {
    const div = document.createElement("div");
    div.className = "chat-tool-call";
    div.dataset.toolId = data.id || "";
    let inputStr;
    try {
      inputStr = JSON.stringify(data.input, null, 2);
    } catch (e) {
      inputStr = String(data.input);
    }
    safeSetHTML(div,
      '<details><summary><i data-lucide="wrench"></i> <strong>' +
      esc(data.name) +
      "</strong>" +
      '<span class="chat-tool-status">実行中...</span></summary>' +
      '<pre class="chat-tool-detail">' +
      esc(inputStr) +
      "</pre></details>");
    if (targetDiv) {
      // F3: inline insertion inside assistant div (before .chat-time)
      const timeDiv = targetDiv.querySelector(".chat-time");
      if (timeDiv) {
        targetDiv.insertBefore(div, timeDiv);
      } else {
        targetDiv.appendChild(div);
      }
    } else {
      // Legacy: insert tool_call after the last assistant message
      const lastAssistant = container.querySelector(".chat-msg.assistant:last-child");
      if (lastAssistant && lastAssistant.nextSibling) {
        container.insertBefore(div, lastAssistant.nextSibling);
      } else if (lastAssistant) {
        container.appendChild(div);
      } else {
        container.appendChild(div);
      }
    }
    container.scrollTop = container.scrollHeight;
    N.Core.refreshIcons();
    return div;
  } else if (eventType === "tool_result") {
    let resultStr;
    try {
      resultStr =
        typeof data.result === "object"
          ? JSON.stringify(data.result, null, 2)
          : String(data.result);
    } catch (e) {
      resultStr = String(data.result);
    }

    // ── Duplicate notification ──
    if (
      typeof data.result === "object" &&
      data.result &&
      data.result.status === "duplicate"
    ) {
      toast(
        "⚠️ " + (data.result.message || "類似の記憶が既に存在します"),
        "warning",
      );
    }

    // Find matching tool_call div by id and update it
    const callDiv = data.id
      ? container.querySelector('[data-tool-id="' + CSS.escape(data.id) + '"]')
      : null;
    if (callDiv) {
      const statusEl = callDiv.querySelector(".chat-tool-status");
      if (statusEl) safeSetHTML(statusEl, ' <i data-lucide="check"></i> 完了');
      const details = callDiv.querySelector("details");
      if (details) {
        const resultPre = document.createElement("pre");
        resultPre.className = "chat-tool-detail chat-tool-result-content";
        resultPre.textContent = resultStr;
        details.appendChild(resultPre);
      }
      callDiv.classList.add("done");
      container.scrollTop = container.scrollHeight;
    } else {
      const div = document.createElement("div");
      div.className = "chat-tool-result";
      safeSetHTML(div,
        '<details><summary><i data-lucide="check"></i> <strong>' +
        esc(data.name) +
        "</strong></summary>" +
        '<pre class="chat-tool-detail chat-tool-result-content">' +
        esc(resultStr) +
        "</pre></details>");
      container.appendChild(div);
      container.scrollTop = container.scrollHeight;
      N.Core.refreshIcons();
      return div;
    }
  }
}

// ------------------------------------------------------------------
// File tool call handler — specialized rendering for file operations
// ------------------------------------------------------------------
function handleFileToolCall(evt) {
  const icons = {
    edit: '<i data-lucide="pencil"></i>',
    create: '<i data-lucide="edit-3"></i>',
    view: '<i data-lucide="eye"></i>',
    bash: '<i data-lucide="settings"></i>',
    powershell: '<i data-lucide="settings"></i>',
    str_replace_editor: '<i data-lucide="pencil"></i>',
    delete_file: '<i data-lucide="trash-2"></i>',
    list_files: '<i data-lucide="folder-open"></i>',
    write_file: '<i data-lucide="edit-3"></i>',
    read_file: '<i data-lucide="eye"></i>',
    glob: '<i data-lucide="search"></i>',
    grep: '<i data-lucide="search"></i>',
  };
  const icon = icons[evt.name] || '<i data-lucide="wrench"></i>';
  const detail =
    evt.input?.path ||
    evt.input?.file_path ||
    evt.input?.command ||
    evt.input?.pattern ||
    evt.input?.glob ||
    "";
  // チャットにもツールバブルを表示（CodingAgent閉時でも見えるように）
  appendToolEvent("tool_call", evt);
}

// ------------------------------------------------------------------
// Code block Run button — executes code via Coding Agent
// ------------------------------------------------------------------
async function execCodeBlock(code, language, resultEl, runBtn) {
  if (!S.persona) return;
  if (typeof openCodingAgent === "function") {
    openCodingAgent({ code, language });
    if (resultEl) {
      resultEl.className = "hljs-run-result stdout";
      resultEl.textContent = "▶ Coding Agent で開きました";
      resultEl.style.display = "block";
    }
    if (runBtn) runBtn.textContent = "▶ Run";
    return;
  }
  if (resultEl) {
    resultEl.className = "hljs-run-result stderr";
    resultEl.textContent = "サンドボックス実行は利用できません";
    resultEl.style.display = "block";
  }
}

// ------------------------------------------------------------------
// Image generation
// ------------------------------------------------------------------
let _imageGenSpinnerId = null;

function _isNearBottom(c) {
  return (c.scrollHeight - c.scrollTop - c.clientHeight) < 100;
}

function showImageGenSpinner(evt) {
  const container = findChatLogContainer();
  if (!container) return;

  const spinner = document.createElement("div");
  spinner.className = "chat-image-gen-spinner";
  safeSetHTML(spinner, '<div class="spinner"></div> 画像を生成中... (' + esc(evt.provider) + ', ' + evt.n + '枚)');

  _imageGenSpinnerId = "image-gen-spinner-" + Date.now();
  spinner.id = _imageGenSpinnerId;

  // スピナーをチャットログ末尾に追加
  container.appendChild(spinner);

  if (_isNearBottom(container)) scrollToBottom(container);
}

function showImageGenResult(evt) {
  console.log("[showImageGenResult] evt:", JSON.stringify({type: evt.type, imagesCount: evt.images?.length, hasImages: !!evt.images, spinnerId: _imageGenSpinnerId}));
  const container = findChatLogContainer();
  if (!container) return;

  // スピナーを削除（位置記録は不要 — ツールコール基準で挿入）
  if (_imageGenSpinnerId) {
    var spinner = document.getElementById(_imageGenSpinnerId);
    if (spinner) spinner.remove();
    _imageGenSpinnerId = null;
  }

  console.log("[showImageGenResult] images check:", {images: !!evt.images, length: evt.images?.length, self_portrait: evt.self_portrait});
  if (!evt.images || !evt.images.length) return;

  // Self-portrait → update Overview tab
  if (evt.self_portrait && evt.images[0]) {
    var portraitEl = document.getElementById('overview-portrait');
    if (portraitEl) {
      var imgUrl = evt.images[0].url || ("data:image/png;base64," + (evt.images[0].base64 || ""));
      portraitEl.style.display = 'block';
      safeSetHTML(portraitEl, '<div class="glass p-4" style="text-align:center;max-width:400px;margin:0 auto 16px">'
          + '<img src="' + esc(imgUrl) + '" alt="Self Portrait" style="max-width:100%;max-height:300px;border-radius:8px;cursor:pointer" onclick="N.Chat.attachments.openViewer(\'' + esc(imgUrl) + '\',\'image\')">'
          + '<div style="margin-top:6px;font-size:0.75rem;color:var(--text-muted)">Latest Self Portrait</div>'
          + '</div>');
    }
  }

  evt.images.forEach(function (img) {
    console.log("[showImageGenResult] img keys:", Object.keys(img));
    console.log("[showImageGenResult] base64 len:", img.base64?.length, "first 10:", img.base64?.substring(0, 10));
    var card = document.createElement("div");
    card.className = "chat-image-gen-card";

    var imgEl = document.createElement("img");
    // base64 → Blob URL: Chrome data URI上限(~2MB)を回避
    try {
      var binary = atob(img.base64);
      var bytes = new Uint8Array(binary.length);
      for (var i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
      var blob = new Blob([bytes], { type: "image/png" });
      var blobUrl = URL.createObjectURL(blob);
      imgEl.src = blobUrl;

      // Blob URL はカードがDOM削除されるまで維持（クリック時のプレビューを可能に）
      var observer = new MutationObserver(function(mutations) {
        for (var m of mutations) {
          for (var node of m.removedNodes) {
            if (node === card || (node.contains && node.contains(card))) {
              URL.revokeObjectURL(blobUrl);
              observer.disconnect();
              return;
            }
          }
        }
      });
      observer.observe(container, { childList: true, subtree: true });

      imgEl.onload = function() {
        if (typeof _isNearBottom !== 'undefined' && _isNearBottom(container)) scrollToBottom(container);
      };
    } catch (e) {
      console.warn("[showImageGenResult] Blob conversion failed, fallback to data URI:", e);
      imgEl.src = "data:image/png;base64," + img.base64;
    }
    imgEl.alt = img.revised_prompt || "生成画像";
    imgEl.title = img.revised_prompt || "";
    // Store prompt data for media viewer
    imgEl.dataset.revisedPrompt = img.revised_prompt || "";
    imgEl.dataset.negativePrompt = img.negative_prompt || "";
    imgEl.onerror = function () {
      console.error("[showImageGenResult] img decode failed, size:", img.base64?.length);
      imgEl.style.display = "none";
      var errDiv = document.createElement("div");
      errDiv.className = "image-gen-error";
      errDiv.textContent = "⚠️ 画像のデコードに失敗しました（" + (img.base64?.length || 0) + " bytes）";
      card.insertBefore(errDiv, card.firstChild);
      if (typeof _isNearBottom !== 'undefined' && _isNearBottom(container)) scrollToBottom(container);
      // エラー時は即時revoke（画像は非表示になったので不要）
      if (typeof observer !== 'undefined') observer.disconnect();
      if (typeof blobUrl !== 'undefined') URL.revokeObjectURL(blobUrl);
    };
    imgEl.onclick = function () {
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

    // 改訂プロンプトがあれば表示（先頭80文字）
    var rp = img.revised_prompt || "";
    if (rp) {
      var promptSpan = document.createElement("span");
      promptSpan.textContent =
        rp.length > 80 ? rp.substring(0, 80) + "..." : rp;
      promptSpan.style.fontStyle = "italic";
      meta.appendChild(promptSpan);
    }

    var sizeSpan = document.createElement("span");
    sizeSpan.textContent = evt.provider + " · " + (img.size || "");
    meta.appendChild(sizeSpan);

    card.appendChild(imgEl);
    card.appendChild(meta);

    // 画像カードを該当ツールコールの直後に挿入（tool_use_id で特定）
    var targetToolCall = null;
    if (evt.tool_use_id) {
      targetToolCall = container.querySelector('.chat-tool-call[data-tool-id="' + CSS.escape(evt.tool_use_id) + '"]');
    }
    // Fallback: tool_use_id がない場合（古いイベント）は lastToolCall
    if (!targetToolCall) {
      var lastAssistant = container.querySelector('.chat-msg.assistant:last-child');
      targetToolCall = lastAssistant ? lastAssistant.querySelector('.chat-tool-call:last-child') : null;
    }
    if (targetToolCall) {
      targetToolCall.insertAdjacentElement("afterend", card);
    } else {
      var lastAssistant = container.querySelector('.chat-msg.assistant:last-child');
      if (lastAssistant) {
        lastAssistant.appendChild(card);
      } else {
        container.appendChild(card);
      }
    }
  });

  if (_isNearBottom(container)) scrollToBottom(container);
}

// ------------------------------------------------------------------
// MCP Tools management
// ------------------------------------------------------------------
async function fetchMcpTools() {
  if (!S.persona) return;
  // Clear stale data before fetch to prevent cross-persona leakage (BUG 4)
  CHAT.mcpTools = [];
  CHAT.mcpErrors = [];
  try {
    const data = await api("/api/chat/" + encodeURIComponent(S.persona) + "/mcp-tools");
    CHAT.mcpTools = data.tools || [];
    CHAT.mcpErrors = data.errors || [];
    if (typeof N.Chat.settings.renderMcpJson === 'function') {
      N.Chat.settings.renderMcpJson(CHAT.mcpServers || []);
    }
  } catch (e) {
    console.warn('MCP tools fetch failed:', e);
    CHAT.mcpTools = [];
    CHAT.mcpErrors = [];
  }
}

function toggleTool(toolName) {
  if (!CHAT.disabledTools) CHAT.disabledTools = new Set();
  if (CHAT.disabledTools.has(toolName)) {
    CHAT.disabledTools.delete(toolName);
  } else {
    CHAT.disabledTools.add(toolName);
  }
  // 即時保存
  if (typeof N.Chat.settings.save === 'function') N.Chat.settings.save();
}

// ------------------------------------------------------------------
// Expose on N.Chat.tools
// ------------------------------------------------------------------
N.Chat.tools = {
  append: appendToolEvent,
  handleFile: handleFileToolCall,
  execCode: execCodeBlock,
  showGenSpinner: showImageGenSpinner,
  showGenResult: showImageGenResult,
  fetch: fetchMcpTools,
  toggle: toggleTool,
};

})(window.Nous);
