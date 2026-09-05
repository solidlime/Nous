/* =================================================================
   CHAT CORE — State, initialization, input handling
   Extracted from chat.js (Phase 3, Batch 1)
   ================================================================= */
;(function(N) {
var C = N.Core;
var api = C.api, esc = C.esc, toast = C.toast;
function hideCommandPopup() { return N.Chat.commands.hide(); }
var showConfirm = C.showConfirm, showAlert = C.showAlert;
var truncate = C.truncate, relativeTime = C.relativeTime, fmtDate = C.fmtDate;
"use strict";
var S = window.S;

// --- Cookie helpers for panel state persistence ---
function _getCookie(name) {
  var match = document.cookie.match(new RegExp('(?:^|;\\s*)' + name + '=([^;]*)'));
  return match ? decodeURIComponent(match[1]) : null;
}
function _setCookie(name, value) {
  document.cookie = name + '=' + encodeURIComponent(value) + ';path=/;SameSite=Lax;max-age=31536000';
}

// --- State ---
var CHAT = {
  streaming: false,
  sidebarOpen: _getCookie("nous_sidebar") !== "0",
  memoryPanelOpen: _getCookie("nous_memory_panel") !== "0",
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

// Bridge CHAT state to centralized store
if (window.Nous && window.Nous.Core && window.Nous.Core.store) {
  var _cs = N.Core.store;
  _cs.init({
    streaming: CHAT.streaming,
    sidebarOpen: CHAT.sidebarOpen,
    memoryPanelOpen: CHAT.memoryPanelOpen,
    messages: [],
    mcpServers: [],
    enabledSkills: [],
    mcpTools: [],
    mcpErrors: [],
    attachments: [],
    _nextTurnReady: CHAT._nextTurnReady,
    _justReset: CHAT._justReset
  });
  _cs.syncFrom(CHAT);
}

// --- Help texts (used by showHelpTooltip) ---
var HELP_TEXTS = {
  core:
    "LLM API への接続に必須の設定です。プロバイダー（Anthropic / OpenAI / OpenRouter など）・"
    + "モデル名・APIキー・Temperature（創造性の度合い、0〜2）・MaxTokens（最大応答長）・"
    + "Base URL（カスタムエンドポイント）を設定します。ここが正しくないと AI は応答できません。",
  context:
    "LLM に渡す文脈（コンテキスト）の制御設定です。表示する会話履歴のターン数・"
    + "内部で保持する最大メッセージ数・同時ツール呼び出し上限・システムプロンプト・"
    + "コンテキスト圧縮の閾値とモードを設定します。長い会話でのメモリ使用量と応答品質の"
    + "バランスを取るために重要です。",
  memory:
    "会話から重要な情報を自動的に抽出し、長期記憶として保存する機能の設定です。"
    + "記憶の事前読み込み数・抽出用 LLM モデル・抽出時の最大トークン数を設定できます。"
    + "有効にすると AI が会話の要点を覚えてくれるようになります。",
  tools:
    "外部 MCP（Model Context Protocol）サーバーの接続設定です。mcp.json 形式でサーバーを定義し、"
    + "AI がファイル操作や Web 検索などの外部ツールを使用できるようになります。"
    + "ツール実行結果の最大表示文字数も制限できます。",
  skills:
    "利用可能なスキルの一覧です。チェックを入れたスキルが LLM のシステムプロンプトに"
    + "追加され、特定のタスク（テスト駆動開発・体系的なデバッグ・GitHub Actions など）に"
    + "特化した応答が可能になります。必要なスキルだけ有効にしてください。",
  reflection:
    "会話の振り返り（リフレクション）機能です。有効にすると、設定した間隔で会話履歴を"
    + "分析し、ユーザーの行動パターン・価値観・重要な決定事項を自動的に抽出します。"
    + "しきい値と最小間隔を調整して、振り返りの頻度を制御できます。",
  mental:
    "ユーザーの発話パターンからメンタルモデル（性格・好み・行動傾向・思考の癖）を"
    + "自動構築する機能です。十分なサンプル数が集まるとモデルが更新され、"
    + "よりパーソナライズされた自然な応答が可能になります。",
  weights:
    "記憶検索時の重みバランス設定です。「鮮度（Recency）＝新しい記憶を優先」"
    + "「重要度（Importance）＝重要な記憶を優先」「関連性（Relevance）＝話題に"
    + "近い記憶を優先」の 3 軸と、RRF（Reciprocal Rank Fusion）の k 値を調整します。"
    + "合計が 1.0 になる必要はありません。",
  image:
    "画像生成機能の設定です。有効にすると AI が画像を生成・編集できるようになります。"
    + "対応プロバイダーとモデルを選択し、生成パラメータを調整してください。"
    + "画像生成 API が利用可能な環境でのみ動作します。",
  auto_capture:
    "自動キャプチャ（Auto Capture）は、一定間隔で会話内容を分析し、重要な情報を"
    + "自動的に記憶として保存する機能です。実行間隔（秒）と 1 回あたりの最大記憶数を"
    + "設定できます。会話の流れを妨げずにバックグラウンドで動作します。",
  memory_enrichment:
    "記憶エンリッチメント（Memory Enrichment）は、既存の記憶を定期的に分析・整理し、"
    + "より構造化された形で再保存する機能です。要約の粒度（detailed / medium / brief）・"
    + "使用する LLM・プロンプトテンプレート・最小文字数などを設定します。"
    + "自動実行を有効にすると、設定した間隔で定期的に処理が走ります。",
  forgetting:
    "忘却機構（Forgetting）は、人間の記憶の減衰を模倣する機能です。重要でない記憶や"
    + "古い記憶の重要度を時間経過とともに徐々に下げ、最終的に削除します。"
    + "忘却トリガーとなる記憶数・減衰間隔・最小保持強度・1回の忘却率・忘却強度を"
    + "調整することで、記憶容量と質のバランスを最適化します。",
  other:
    "その他のユーティリティ設定です。デバッグモード（詳細ログの出力）・"
    + "表示言語（ja / en）・メッセージのタイムスタンプ表示・並列ツール実行の有効化・"
    + "エピソード検索の有効化などを設定します。開発時やトラブルシューティングに便利です。",
  voice:
    "音声合成（Irodori-TTS）の設定です。TTS サーバーの URL・声質（キャラクター名）・"
    + "感情連動（AI の感情に合わせた声色変化）・応答の自動再生を制御します。"
    + "詳細パラメータでは、推論ステップ数（品質）・テキスト忠実度・話者忠実度・"
    + "字幕忠実度・チャンク分割サイズ・乱数シードを調整できます。",
};

// ------------------------------------------------------------------
// Tooltip helpers
// ------------------------------------------------------------------
// State: track DOM elements directly (no fragile string categories)
var _activeTooltipIcon = null;   // currently shown tooltip's icon
var _pinnedTooltipIcon = null;   // click-pinned icon (null = not pinned)
var _justClickedOff = false;     // suppress hover re-show after unpin

function _showTooltip(icon) {
  _hideTooltip();
  _activeTooltipIcon = icon;

  var category = icon.getAttribute("data-category");
  var tooltip = document.createElement("div");
  tooltip.className = "chat-help-tooltip";
  tooltip.textContent = HELP_TEXTS[category] || "説明はありません。";
  tooltip.setAttribute("role", "tooltip");
  tooltip.id = "chat-help-tooltip";

  var rect = icon.getBoundingClientRect();
  var isMobile = window.innerWidth <= 768;

  document.body.appendChild(tooltip);

  if (isMobile) {
    tooltip.style.top = rect.bottom + 8 + "px";
    tooltip.style.left = rect.left + rect.width / 2 + "px";
    tooltip.style.transform = "translateX(-50%)";
  } else {
    tooltip.style.left = rect.right + 10 + "px";
    tooltip.style.top = rect.top - 5 + "px";
  }

  requestAnimationFrame(function() {
    tooltip.classList.add("visible");
    var tr = tooltip.getBoundingClientRect();
    if (tr.right > window.innerWidth - 10) {
      tooltip.style.left = (isMobile
        ? rect.left + rect.width / 2 - tr.width
        : rect.left - tr.width - 10) + "px";
    }
    if (isMobile && tr.bottom > window.innerHeight - 10) {
      tooltip.style.top = rect.top - tr.height - 8 + "px";
    }
  });
}

function _hideTooltip() {
  var tip = document.querySelector(".chat-help-tooltip");
  if (tip) {
    tip.classList.remove("visible");
    setTimeout(function() { if (tip.parentNode) tip.remove(); }, 200);
  }
  _activeTooltipIcon = null;
}

function _isMouseStillOnIcon(icon, relatedTarget) {
  return icon && relatedTarget && (
    relatedTarget === icon || icon.contains(relatedTarget) ||
    (relatedTarget.closest && relatedTarget.closest(".chat-help-tooltip"))
  );
}

// Delegated event binding for help icons
var _helpListenersBound = false;
function _bindHelpIconListeners() {
  if (_helpListenersBound) return;
  _helpListenersBound = true;

  // --- Hover in (mouseover bubbles, unlike mouseenter) ---
  document.addEventListener("mouseover", function(e) {
    var icon = e.target && e.target.nodeType === 1 ? e.target.closest(".chat-help-icon") : null;
    if (!icon) return;
    if (icon === _activeTooltipIcon) return; // already showing for this icon
    if (_justClickedOff) return;             // suppress after click-to-unpin
    if (icon === _pinnedTooltipIcon) return; // pinned icon keeps its own tooltip
    _showTooltip(icon);
  });

  // --- Hover out (mouseleave with capture for reliable leave detection) ---
  document.addEventListener("mouseleave", function(e) {
    var icon = e.target && e.target.nodeType === 1 ? e.target.closest(".chat-help-icon") : null;
    if (!icon) return;
    // Don't hide if mouse moved to child element or to the tooltip itself
    if (_isMouseStillOnIcon(icon, e.relatedTarget)) return;
    // Don't hide if this icon is pinned
    if (icon === _pinnedTooltipIcon) return;
    _hideTooltip();
  }, true);

  // --- Click: toggle pin ---
  document.addEventListener("click", function(e) {
    var icon = e.target && e.target.nodeType === 1 ? e.target.closest(".chat-help-icon") : null;
    if (!icon) return;
    e.stopPropagation();
    e.preventDefault();

    if (icon === _pinnedTooltipIcon) {
      // Unpin: hide immediately, suppress hover re-show briefly
      _pinnedTooltipIcon = null;
      _hideTooltip();
      _justClickedOff = true;
      requestAnimationFrame(function() { _justClickedOff = false; });
    } else {
      // Pin (new or different icon)
      _pinnedTooltipIcon = icon;
      _showTooltip(icon);
    }
  }, true);

  // --- Outside click: unpin + hide ---
  document.addEventListener("click", function(e) {
    if (!_pinnedTooltipIcon) return;
    if (e.target.closest(".chat-help-icon") || e.target.closest(".chat-help-tooltip")) return;
    _pinnedTooltipIcon = null;
    _hideTooltip();
    _justClickedOff = true;
    requestAnimationFrame(function() { _justClickedOff = false; });
  });

  // --- Escape: unpin + hide ---
  document.addEventListener("keydown", function(e) {
    if (e.key === "Escape" && _pinnedTooltipIcon) {
      _pinnedTooltipIcon = null;
      _hideTooltip();
    }
  });
}

// ------------------------------------------------------------------
// Chat initialization
// ------------------------------------------------------------------
async function loadChat() {
  if (!S.persona) return;
  // Reset state to prevent cross-persona data leakage (BUG 2)
  CHAT.mcpServers = [];
  CHAT.mcpTools = [];
  CHAT.mcpErrors = [];
  CHAT.disabledTools.clear();
  CHAT.enabledSkills = [];
  CHAT.messages = [];
  await N.Chat.settings.load();
  loadSkillsForChat();
  // Disable input during async restore to prevent premature chatSend()
  var _restoreInput = document.getElementById("chat-input");
  var _restoreSendBtn = document.getElementById("chat-send-btn");
  if (_restoreInput) _restoreInput.disabled = true;
  if (_restoreSendBtn) _restoreSendBtn.disabled = true;
  await N.Chat.history.restore();
  setupChatInputHandler();
  if (_restoreInput) _restoreInput.disabled = false;
  if (_restoreSendBtn) _restoreSendBtn.disabled = false;
  loadChatCommitments();
  N.Chat.equipment.load();
  N.Core.refreshIcons();
  _bindHelpIconListeners();

  // --- Restore panel open/closed state from cookies to DOM ---
  var _settingsPanel = document.getElementById("settings-panel");
  if (_settingsPanel) {
    if (CHAT.sidebarOpen) {
      // Ensure panel is open: remove collapsed class, clear inline overrides
      _settingsPanel.classList.remove("collapsed");
      _settingsPanel.style.removeProperty("width");
      _settingsPanel.style.display = "flex";
    } else {
      // Ensure panel is closed: add collapsed class
      _settingsPanel.classList.add("collapsed");
      var _isMobile = window.innerWidth <= 768;
      if (!_isMobile) {
        _settingsPanel.style.width = "0";
      }
    }
  }
  var _memoryPanel = document.getElementById("memory-panel");
  if (_memoryPanel) {
    // Restore open state explicitly: mobile CSS defaults #memory-panel to display:none
    _memoryPanel.style.display = CHAT.memoryPanelOpen ? "flex" : "none";
  }

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
      await N.Chat.attachments.upload(file);
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
        N.Chat.commands.updateSlashSelection(items);
      }
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      if (S.slashCommandIndex > 0) {
        S.slashCommandIndex--;
        N.Chat.commands.updateSlashSelection(items);
      }
    } else if (e.key === "Enter") {
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
  if (e.key === "Enter" && e.ctrlKey) {
    e.preventDefault();
    const val = input.value.trim();
    hideCommandPopup();
    // Slash commands
    if (val.startsWith("/memory ")) {
      N.Chat.commands.handle("memory_create", {
        content: val.slice(8).trim(),
        importance: 0.7,
        tags: [],
      });
    } else if (val.startsWith("/goal ")) {
      N.Chat.commands.handle("goal_manage", {
        operation: "create",
        content: val.slice(6).trim(),
        importance: 0.8,
      });
    } else if (val === "/help" || val.startsWith("/help ")) {
      input.value = "";
      input.style.height = "auto";
      N.Chat.commands.show();
    } else {
      N.Chat.send();
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
    N.Chat.commands.popup(input);
  } else {
    hideCommandPopup();
  }
}

// ------------------------------------------------------------------
// Async loaders
// ------------------------------------------------------------------
async function loadChatCommitments() {
  if (!S.persona) return;
  // Registered by chat-memory-panel.js. Skip quietly (no error toast) when
  // the panel script failed to load — a missing panel is not a data failure.
  var mp = N.Chat.memoryPanel;
  if (!mp || (typeof mp.update !== "function" && typeof mp.updateReflection !== "function")) {
    console.warn("[loadChatCommitments] memoryPanel not registered; skipping");
    return;
  }
  try {
    const data = await api(
      "/api/chat/" + encodeURIComponent(S.persona) + "/commitments",
    );
    if (Array.isArray(data.goals) && typeof mp.update === "function") {
      mp.update(undefined, undefined, data.goals);
    }
    if (data.insights && data.insights.length > 0 && typeof mp.updateReflection === "function") {
      mp.updateReflection(data.insights);
    }
  } catch (e) {
    console.error("[loadChatCommitments] failed:", e);
    toast("リフレクション読込失敗: " + e.message, "error");
    if (typeof mp.updateReflection === "function") {
      try { mp.updateReflection([]); } catch (_) {}
    }
  }
}

async function loadSkillsForChat() {
  try {
    const skills = await api("/api/skills");
    // Filter enabledSkills to only include skills that exist on disk (BUG 4)
    var validNames = new Set(skills.map(function(s) { return s.name; }));
    CHAT.enabledSkills = CHAT.enabledSkills.filter(function(n) { return validNames.has(n); });
    (N.Chat.settings.renderSkills || function(){})(skills, CHAT.enabledSkills);
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
  _setCookie("nous_sidebar", CHAT.sidebarOpen ? "1" : "0");
  if (CHAT.sidebarOpen) {
    // Open: clear collapsed state and restore dimensions
    sidebar.classList.remove("collapsed");
    sidebar.style.removeProperty("width");
    sidebar.style.display = "flex";
    if (isMobile) {
      sidebar.style.width = "100%";
    }
    if (isMobile && backdrop) backdrop.classList.add("visible");
  } else {
    // Close: apply collapsed state
    sidebar.classList.add("collapsed");
    if (isMobile) {
      // Mobile: let CSS transform handle the slide-out
      sidebar.style.removeProperty("width");
    } else {
      // Desktop: zero-width hide
      sidebar.style.width = "0";
      sidebar.style.removeProperty("display");
    }
    if (backdrop) backdrop.classList.remove("visible");
  }
}

function toggleMemoryPanel() {
  const panel = document.getElementById("memory-panel");
  CHAT.memoryPanelOpen = !CHAT.memoryPanelOpen;
  _setCookie("nous_memory_panel", CHAT.memoryPanelOpen ? "1" : "0");
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
// キャラ一貫性フラグ（character_flag SSE・非破壊・表示のみ）
// ------------------------------------------------------------------
N.Chat.showCharacterFlag = function (msgEl, violation, detail) {
  if (!msgEl) return;
  var badge = document.createElement("div");
  badge.className = "character-flag";
  badge.title = violation ? violation + (detail ? ": " + detail : "") : (detail || "");
  badge.textContent = "⚠ 内面に違和感";
  msgEl.appendChild(badge);
};

// ------------------------------------------------------------------
// Expose on N.Chat.core
// ------------------------------------------------------------------
N.Chat.core = {
  showHelp: _showTooltip,
  hideHelp: _hideTooltip,
  loadChat: loadChat,
  setupInput: setupChatInputHandler,
  setupInputWithObserver: setupChatInputHandlerWithObserver,
  keydown: chatInputKeydownHandler,
  input: chatInputInputHandler,
  loadCommitments: loadChatCommitments,
  loadSkills: loadSkillsForChat,
  toggleSettings: toggleSettingsPanel,
  toggleMemory: toggleMemoryPanel,
  debug: renderDebugPanel,
};

})(window.Nous);
