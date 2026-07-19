/* =================================================================
   CHAT TOOLS — Tool call events, file tool calls, code execution,
   image generation, MCP tools management
   Extracted from chat.js (Phase 3, Batch 2)
   ================================================================= */
;(function(N) {
var C = N.Core;
var api = C.api, esc = C.esc, toast = C.toast;
var showConfirm = C.showConfirm, showAlert = C.showAlert;
var truncate = C.truncate, relativeTime = C.relativeTime, fmtDate = C.fmtDate;
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
    div.innerHTML =
      '<details><summary><i data-lucide="wrench"></i> <strong>' +
      esc(data.name) +
      "</strong>" +
      '<span class="chat-tool-status">実行中...</span></summary>' +
      '<pre class="chat-tool-detail">' +
      esc(inputStr) +
      "</pre></details>";
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
    setTimeout(() => {
      if (typeof lucide !== "undefined") lucide.createIcons();
    }, 50);
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
      if (statusEl) statusEl.innerHTML = ' <i data-lucide="check"></i> 完了';
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
      div.innerHTML =
        '<details><summary><i data-lucide="check"></i> <strong>' +
        esc(data.name) +
        "</strong></summary>" +
        '<pre class="chat-tool-detail chat-tool-result-content">' +
        esc(resultStr) +
        "</pre></details>";
      container.appendChild(div);
      container.scrollTop = container.scrollHeight;
      setTimeout(() => {
        if (typeof lucide !== "undefined") lucide.createIcons();
      }, 50);
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

function showImageGenSpinner(evt) {
  const container = findChatLogContainer();
  if (!container) return;

  const spinner = document.createElement("div");
  spinner.className = "chat-image-gen-spinner";
  spinner.innerHTML = '<div class="spinner"></div> ';
  spinner.innerHTML +=
    "画像を生成中... (" + esc(evt.provider) + ", " + evt.n + "枚)";

  _imageGenSpinnerId = "image-gen-spinner-" + Date.now();
  spinner.id = _imageGenSpinnerId;

  // スピナーをチャットログ末尾に追加
  container.appendChild(spinner);

  scrollToBottom(container);
}

function showImageGenResult(evt) {
  console.log("[showImageGenResult] evt:", JSON.stringify({type: evt.type, imagesCount: evt.images?.length, hasImages: !!evt.images, spinnerId: _imageGenSpinnerId}));
  const container = findChatLogContainer();
  if (!container) return;

  // スピナーを検索（後で差し替えるため、削除前に位置を記録）
  var anchor = null;
  if (_imageGenSpinnerId) {
    var spinner = document.getElementById(_imageGenSpinnerId);
    if (spinner) {
      anchor = spinner.nextSibling;
      spinner.remove();
    }
    _imageGenSpinnerId = null;
  }

  console.log("[showImageGenResult] images check:", {images: !!evt.images, length: evt.images?.length});
  if (!evt.images || !evt.images.length) return;

  evt.images.forEach(function (img) {
    console.log("[showImageGenResult] img keys:", Object.keys(img));
    console.log("[showImageGenResult] base64 len:", img.base64?.length, "first 10:", img.base64?.substring(0, 10));
    var card = document.createElement("div");
    card.className = "chat-image-gen-card";

    var imgEl = document.createElement("img");
    imgEl.src = "data:image/png;base64," + img.base64;
    imgEl.alt = img.revised_prompt || "生成画像";
    imgEl.title = img.revised_prompt || "";
    imgEl.onclick = function () {
      if (typeof openMediaViewer === "function") {
        openMediaViewer(imgEl.src, "image");
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

    // スピナーの後に画像カードを挿入
    container.appendChild(card);
  });

  scrollToBottom(container);
}

// ------------------------------------------------------------------
// MCP Tools management
// ------------------------------------------------------------------
async function fetchMcpTools() {
  if (!S.persona) return;
  try {
    const data = await api("/api/chat/" + encodeURIComponent(S.persona) + "/mcp-tools");
    CHAT.mcpTools = data.tools || [];
    CHAT.mcpErrors = data.errors || [];
    if (typeof renderMcpJson === 'function') {
      renderMcpJson(CHAT.mcpServers || []);
    }
  } catch (e) {
    console.warn('MCP tools fetch failed:', e);
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
  if (typeof saveChatConfig === 'function') saveChatConfig();
}

// ------------------------------------------------------------------
// Expose on N.Chat.tools
// ------------------------------------------------------------------
N.Chat.tools = {
  append: appendToolEvent,
  fetch: fetchMcpTools,
  toggle: toggleTool,
};

// Expose globals:
window.appendToolEvent = appendToolEvent;
window.handleFileToolCall = handleFileToolCall;
window.execCodeBlock = execCodeBlock;
window.showImageGenSpinner = showImageGenSpinner;
window.showImageGenResult = showImageGenResult;
window.fetchMcpTools = fetchMcpTools;
window.toggleTool = toggleTool;

})(window.Nous);
