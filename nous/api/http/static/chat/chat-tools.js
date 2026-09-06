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

// 没入的ツール表示（ペルソナ汎用の一人称ナラーション調・生JSONはdetailsに維持）
var TOOL_LABELS = {
  get_context: "今の状態を確かめてる…",
  memory_create: "思い出を刻んでる…",
  memory_read: "記憶を引き出してる…",
  memory_update: "記憶を書き換えてる…",
  memory_delete: "記憶を手放してる…",
  memory_search: "記憶をたどってる…",
  memory_stats: "記憶の棚卸し中…",
  update_context: "気持ちを整理してる…",
  item_add: "持ち物を整えてる…",
  item_equip: "身支度してる…",
  item_search: "持ち物を探してる…",
  goal_manage: "目標を確かめてる…",
  image_generate: "絵を描いてる…",
  list_skills: "使える技を確認してる…",
  invoke_skill: "技を繰り出す準備…",
  recall_weaver: "過去の記憶を呼び起こしてる…",
};
// 未知のツールは生名を晒さず、系統で推測したナラーションに落とす
// （生名は summary の title と details 内の JSON で確認できる）
function toolLabel(name) {
  if (TOOL_LABELS[name]) return TOOL_LABELS[name];
  if (/skill/.test(name)) return "技を使ってる…";
  if (/^memory_/.test(name)) return "記憶を操作してる…";
  if (/^item_/.test(name)) return "持ち物を確認してる…";
  if (/^goal_/.test(name)) return "目標を整理してる…";
  return "作業してる…";
}
// wrench は汎用ツール系のみ。系統ごとに象徴的な lucide アイコン。
function toolIcon(name) {
  if (name === "image_generate") return "image";
  if (/skill/.test(name) || name === "recall_weaver") return "sparkles";
  if (/^memory_/.test(name) || name === "get_context" || name === "update_context") return "brain";
  if (/^item_/.test(name)) return "backpack";
  if (/^goal_/.test(name)) return "target";
  return "wrench";
}

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
      '<details><summary>' +
      '<span class="chat-tool-summary-left">' +
      '<i data-lucide="' + toolIcon(data.name) + '"></i> <strong title="' + esc(data.name || "") + '">' +
      esc(toolLabel(data.name)) +
      '</strong></span>' +
      '<span class="chat-tool-chevron"><i data-lucide="chevron-right"></i></span>' +
      '<span class="chat-tool-status"></span></summary>' +
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
      if (statusEl) safeSetHTML(statusEl, '<i data-lucide="check"></i>');
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
        '<details><summary>' +
        '<span class="chat-tool-summary-left">' +
        '<i data-lucide="' + toolIcon(data.name) + '"></i> <strong title="' + esc(data.name || "") + '">' +
        esc(toolLabel(data.name)) +
        '</strong></span>' +
        '<span class="chat-tool-chevron"><i data-lucide="chevron-right"></i></span>' +
        '</summary>' +
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
  safeSetHTML(spinner, '<div class="spinner"></div> 画像を生成中…（' + evt.n + '枚）');

  _imageGenSpinnerId = "image-gen-spinner-" + Date.now();
  spinner.id = _imageGenSpinnerId;

  // スピナーをチャットログ末尾に追加
  container.appendChild(spinner);

  if (_isNearBottom(container)) scrollToBottom(container);
}

function showImageGenResult(evt) {
  const container = findChatLogContainer();
  if (!container) return;

  // スピナーを削除（位置記録は不要 — ツールコール基準で挿入）
  if (_imageGenSpinnerId) {
    var spinner = document.getElementById(_imageGenSpinnerId);
    if (spinner) spinner.remove();
    _imageGenSpinnerId = null;
  }

  if (!evt.images || !evt.images.length) return;

  // Self-portrait → update Overview tab (f1: 両フラグ名を受容)
  if ((evt.self_portrait || evt.is_self_portrait) && evt.images[0]) {
    var portraitEl = document.getElementById('overview-portrait');
    if (portraitEl) {
      var imgUrl = evt.images[0].url || ("data:image/png;base64," + (evt.images[0].base64 || ""));
      portraitEl.style.display = 'block';
      safeSetHTML(portraitEl, '<div class="glass p-4">'
          + '<img src="' + esc(imgUrl) + '" alt="自画像" data-tool-viewer="1" data-url="' + esc(imgUrl) + '">'
          + '<div>最新の自画像</div>'
          + '</div>');
    }
  }

  evt.images.forEach(function (img) {
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
      errDiv.textContent = "⚠️ 画像のデコードに失敗しました";
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
        "生成イメージ: " + (rp.length > 80 ? rp.substring(0, 80) + "..." : rp);
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
  label: toolLabel,
  icon: toolIcon,
};

/* CSP-safe delegation: tool portrait viewer (no inline onclick) */
if (typeof document !== "undefined" && !showImageGenResult._delegated) {
  showImageGenResult._delegated = true;
  document.addEventListener("click", function (e) {
    var img = e.target && e.target.closest ? e.target.closest("[data-tool-viewer]") : null;
    if (!img) return;
    if (N.Chat.attachments && typeof N.Chat.attachments.openViewer === "function") {
      N.Chat.attachments.openViewer(img.getAttribute("data-url"), "image");
    }
  });
}

})(window.Nous);
