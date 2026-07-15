/* =================================================================
   CHAT CORE — State, initialization, input handling
   Extracted from chat.js (Phase 3, Batch 1)
   ================================================================= */
;(function(N) {
"use strict";

// --- State ---
var CHAT = {
  streaming: false,
  sidebarOpen: true,
  memoryPanelOpen: true,
  messages: [], // { role, content, time }
  mcpServers: [],
  enabledSkills: [],
  mcpTools: [], // MCP tools list from server
  mcpErrors: [], // errors from mcp-tools endpoint
  disabledTools: new Set(), // set of disabled tool names
  abortController: null, // F4: AbortController for streaming cancel
  attachments: [], // { filename, url, workspace_path, mime_type, size }
  _nextTurnReady: false, // true after 'done' event; next event creates a new assistant div
  _justReset: false, // true after reset; prevents restoreChatHistory from re-fetching
};
N.Chat.state = CHAT;

// --- Help texts (used by showHelpTooltip) ---
var HELP_TEXTS = {
  core: "プロバイダー（Anthropic/OpenAI/OpenRouter）・モデル・APIキー・Temperature・MaxTokens など、LLM API への接続に必要な基本設定です。",
  context:
    "会話履歴の保持数・表示数・ツール呼び出し上限・システムプロンプト など、LLM の文脈制御に関する設定です。",
  memory:
    "会話からの自動記憶抽出（Mem0方式）・抽出用モデル・LLMメモリツールの利用 など、長期記憶機能の設定です。",
  tools:
    "外部 MCP サーバーの接続設定（mcp.json形式）および、ツール実行結果の表示制限です。",
  skills:
    "利用可能なスキルの一覧です。チェックを入れたスキルが LLM のシステムプロンプトに追加されます。",
  reflection:
    "会話の振り返り（リフレクション）機能の設定です。有効にすると、一定間隔で会話内容を分析し重要な情報を自動抽出します。",
  mental:
    "ユーザーの発話パターンからメンタルモデル（性格・好み・行動傾向）を自動構築する機能の設定です。",
  weights:
    "記憶検索時の「鮮度（新しさ）」「重要度」「関連性」の重みバランスを調整します。",
  other:
    "自動整理・Dockerサンドボックス・デバッグモード など、その他のユーティリティ設定です。",
  voice:
    "Irodori-TTS による音声合成の設定です。音声モデルの選択・感情連動・応答の自動再生を制御します。",
};

// ------------------------------------------------------------------
// Tooltip helpers
// ------------------------------------------------------------------
function showHelpTooltip(event, category) {
  const existing = document.querySelector(".chat-help-tooltip");
  if (existing) existing.remove();

  const tooltip = document.createElement("div");
  tooltip.className = "chat-help-tooltip";
  tooltip.textContent = HELP_TEXTS[category] || "説明はありません。";

  const rect = event.target.getBoundingClientRect();
  tooltip.style.left = rect.right + 10 + "px";
  tooltip.style.top = rect.top - 5 + "px";

  document.body.appendChild(tooltip);
  requestAnimationFrame(() => tooltip.classList.add("visible"));

  // 画面右端チェック
  const tr = tooltip.getBoundingClientRect();
  if (tr.right > window.innerWidth - 10) {
    tooltip.style.left = rect.left - tr.width - 10 + "px";
  }
}

function hideHelpTooltip() {
  const tooltip = document.querySelector(".chat-help-tooltip");
  if (tooltip) {
    tooltip.classList.remove("visible");
    setTimeout(() => tooltip.remove(), 200);
  }
}

// ------------------------------------------------------------------
// Chat initialization
// ------------------------------------------------------------------
function loadChat() {
  if (!S.persona) return;
  loadChatConfig();
  loadSkillsForChat();
  restoreChatHistory();
  loadChatCommitments();
  loadEquipment();
  loadPortrait();
  setupChatInputHandler();
  setTimeout(() => {
    if (typeof lucide !== "undefined") lucide.createIcons();
  }, 100);

  // Monitor persona selector changes (moved from chat.js)
  var __chatPersonaTries = 0;
  var __CHAT_PERSONA_MAX_TRIES = 20;
  var __chatPersonaWatcher = setInterval(function() {
    var sel = document.getElementById("persona-select");
    if (!sel) {
      __chatPersonaTries++;
      if (__chatPersonaTries >= __CHAT_PERSONA_MAX_TRIES) {
        console.warn("[chat] #persona-select not found, giving up");
        clearInterval(__chatPersonaWatcher);
      }
      return;
    }
    if (!sel._chatBound) {
      sel._chatBound = true;
      sel.addEventListener("change", function() {
        if (window.S && window.S.tab === "chat") {
          loadChatConfig();
          loadChatCommitments();
        }
      });
      clearInterval(__chatPersonaWatcher);
    }
  }, 500);

  // ESC closes settings panel on mobile (moved from chat.js)
  document.addEventListener("keydown", function(e) {
    if (e.key === "Escape" && CHAT.sidebarOpen) {
      var isMobile = window.innerWidth <= 768;
      if (isMobile) {
        toggleSettingsPanel();
      }
    }
  });
}

// ------------------------------------------------------------------
// Input handlers
// ------------------------------------------------------------------
function setupChatInputHandler() {
  const input = document.getElementById("chat-input");
  if (!input) {
    setupChatInputHandlerWithObserver();
    return;
  }
  if (input._keydownBound) return;
  input._keydownBound = true;
  input.addEventListener("keydown", chatInputKeydownHandler);
  input.addEventListener("input", chatInputInputHandler);
  input.addEventListener("dragover", (e) => {
    e.preventDefault();
    input.classList.add("dragover");
  });
  input.addEventListener("dragleave", () => {
    input.classList.remove("dragover");
  });
  input.addEventListener("drop", async (e) => {
    e.preventDefault();
    input.classList.remove("dragover");
    const files = Array.from(e.dataTransfer.files);
    for (const file of files) {
      await uploadAttachment(file);
    }
  });
}

function setupChatInputHandlerWithObserver() {
  const observer = new MutationObserver(() => {
    const input = document.getElementById("chat-input");
    if (input) {
      observer.disconnect();
      setupChatInputHandler();
    }
  });
  observer.observe(document.body, { childList: true, subtree: true });
  setTimeout(() => observer.disconnect(), 5000);
}

function chatInputKeydownHandler(e) {
  const input = e.currentTarget;
  // Slash command popup keyboard navigation
  const popup = document.getElementById("chat-command-popup");
  if (popup) {
    const items = popup.querySelectorAll(".chat-command-item");
    if (e.key === "ArrowDown") {
      e.preventDefault();
      if (S.slashCommandIndex < items.length - 1) {
        S.slashCommandIndex++;
        updateSlashSelection(items);
      }
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      if (S.slashCommandIndex > 0) {
        S.slashCommandIndex--;
        updateSlashSelection(items);
      }
    } else if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      if (S.slashCommandIndex >= 0 && S.slashCommandIndex < items.length) {
        items[S.slashCommandIndex].click();
      }
    } else if (e.key === "Tab") {
      e.preventDefault();
      if (S.slashCommandIndex >= 0 && S.slashCommandIndex < items.length) {
        items[S.slashCommandIndex].click();
      }
    }
    // Escape continues to default handler below
  }
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    const val = input.value.trim();
    hideCommandPopup();
    // Slash commands
    if (val.startsWith("/memory ")) {
      handleSlashCommand("memory_create", {
        content: val.slice(8).trim(),
        importance: 0.7,
        tags: [],
      });
    } else if (val.startsWith("/goal ")) {
      handleSlashCommand("goal_manage", {
        operation: "create",
        content: val.slice(6).trim(),
        importance: 0.8,
      });
    } else if (val === "/help" || val.startsWith("/help ")) {
      input.value = "";
      input.style.height = "auto";
      showHelpCommand();
    } else {
      chatSend();
    }
  }
  if (e.key === "Escape") {
    hideCommandPopup();
  }
}

function chatInputInputHandler() {
  const input = document.getElementById("chat-input");
  if (!input) return;
  input.style.height = "auto";
  input.style.height = Math.min(input.scrollHeight, 160) + "px";
  // Show command popup when typing /
  if (input.value.startsWith("/")) {
    showCommandPopup(input);
  } else {
    hideCommandPopup();
  }
}

// ------------------------------------------------------------------
// Async loaders
// ------------------------------------------------------------------
async function loadChatCommitments() {
  if (!S.persona) return;
  try {
    const data = await api(
      "/api/chat/" + encodeURIComponent(S.persona) + "/commitments",
    );
    if (Array.isArray(data.goals)) {
      updateMemoryPanel(undefined, undefined, data.goals);
    }
    if (data.insights && data.insights.length > 0) {
      updateReflectionPanel(data.insights);
    }
  } catch (e) {
    console.error("[loadChatCommitments] failed:", e);
    toast("リフレクション読込失敗: " + e.message, "error");
  }
}

async function loadSkillsForChat() {
  try {
    // Auto-sync skills from filesystem on every chat tab open
    await api("/api/skills/sync", { method: "POST" });
    const skills = await api("/api/skills");
    renderSkillsList(skills, CHAT.enabledSkills);
  } catch (e) {
    console.error("[loadSkillsForChat] failed:", e);
    toast("スキル読込失敗: " + e.message, "error");
  }
}

// ------------------------------------------------------------------
// Panel toggles
// ------------------------------------------------------------------
function toggleSettingsPanel() {
  var sidebar = document.getElementById("settings-panel");
  var backdrop = document.getElementById("settings-backdrop");
  var isMobile = window.innerWidth <= 768;
  CHAT.sidebarOpen = !CHAT.sidebarOpen;
  if (CHAT.sidebarOpen) {
    sidebar.style.width = isMobile ? "100%" : "360px";
    sidebar.style.display = "flex";
    sidebar.classList.remove("collapsed");
    if (isMobile && backdrop) backdrop.classList.add("visible");
  } else {
    sidebar.style.width = "0";
    sidebar.classList.add("collapsed");
    if (backdrop) backdrop.classList.remove("visible");
  }
}

function toggleMemoryPanel() {
  const panel = document.getElementById("memory-panel");
  CHAT.memoryPanelOpen = !CHAT.memoryPanelOpen;
  if (!panel) return;
  if (CHAT.memoryPanelOpen) {
    panel.style.display = "flex";
  } else {
    panel.style.display = "none";
  }
  document
    .querySelectorAll(".mem-panel-toggle")
    .forEach((b) => b.classList.toggle("active", CHAT.memoryPanelOpen));
}

// ------------------------------------------------------------------
// Debug panel
// ------------------------------------------------------------------
function renderDebugPanel(anchorEl, data) {
  try {
    console.group("[debug_info]");
    const SECTIONS = [
      "system_prompt",
      "context_summary",
      "memories_raw",
      "tool_calls",
      "messages_sent",
      "context_state",
      "skills_raw",
    ];
    for (const key of SECTIONS) {
      if (data[key] !== undefined && data[key] !== null) {
        console.debug(key + ":", data[key]);
      }
    }
    const extra = Object.fromEntries(
      Object.entries(data).filter(([k]) => !["type", ...SECTIONS].includes(k)),
    );
    if (Object.keys(extra).length) console.debug("extra:", extra);
    console.groupEnd();
  } catch (e) {
    console.error("[debug panel render error]", e);
  }
}

// ------------------------------------------------------------------
// Expose as global functions for backward compat (Phase 3 → Phase 9)
// ------------------------------------------------------------------
window.showHelpTooltip = showHelpTooltip;
window.hideHelpTooltip = hideHelpTooltip;
window.loadChat = loadChat;
window.setupChatInputHandler = setupChatInputHandler;
window.setupChatInputHandlerWithObserver = setupChatInputHandlerWithObserver;
window.chatInputKeydownHandler = chatInputKeydownHandler;
window.chatInputInputHandler = chatInputInputHandler;
window.loadChatCommitments = loadChatCommitments;
window.loadSkillsForChat = loadSkillsForChat;
window.toggleSettingsPanel = toggleSettingsPanel;
window.toggleMemoryPanel = toggleMemoryPanel;
window.renderDebugPanel = renderDebugPanel;

})(window.Nous);
