/* =================================================================
   CHAT SETTINGS APPLY — config loading + applyChatConfig core
   Chunk 2/4 of chat-settings.js. Field groups (voice/image/brain)
   live in settings/apply-groups.js. Namespace: N.Chat.settings.*
   Depends on: settings/reset.js (N.Chat.settings.injectResetButtons),
   settings/apply-groups.js (N.Chat.settings._apply*), + settings-mcp.js
   / settings-image.js (renderMcpJson / updateSliderLabels / checkComfyUI).
   ================================================================= */
((N) => {
  "use strict";
  var C = N.Core;
  var api = C.api;
  var S = window.S;

  // ------------------------------------------------------------------
  // Config loading / applying (chunk 2/4)
  // ------------------------------------------------------------------
  async function loadChatConfig() {
    // loadConfigDefaults は reset.js の IIFE ローカル関数なので、ここから bare 名で
    // 呼ぶと ReferenceError（"loadConfigDefaults is not defined"）になり設定パネルの
    // 読み込みが全滅する。公開されている N.Chat.settings.loadDefaults 経由で呼ぶ。
    // 併せて try の外にあったため失敗が chat-config-status にすら出なかったのを内側へ。
    try {
      var defaultsP = N.Chat.settings.loadDefaults();
      const cfg = await api(
        "/api/chat/" + encodeURIComponent(S.persona) + "/config",
      );
      await defaultsP;
      N.Chat.settings.apply(cfg);
      N.Chat.settings.injectResetButtons();
      // 3-tier visibility hook (expert layer default-hidden). Single entry
      // point on the init path — reset buttons are already injected so the
      // rows to hide are complete.
      if (N.Chat.settings.applyFieldTiers) {
        N.Chat.settings.applyFieldTiers();
      }

    } catch (e) {
      document.getElementById("chat-config-status").textContent =
        "設定読込失敗: " + e.message;
    }
  }

  // ------------------------------------------------------------------
  // 承認ポリシー（shell_approval_mode）— 設定 HTML（Python）に欄が無いので
  // ツール欄の先頭にトグルを1個だけ差し込む。ON = "auto" / OFF = "ask"。
  // allowlist は UI に出さない（既存挙動を壊さないため）。
  // ------------------------------------------------------------------
  function _ensureApprovalRow() {
    if (document.getElementById("chat-shell-approval-mode")) return;
    var host = document.getElementById("chat-mcp-section");
    if (!host) return;
    var row = document.createElement("div");
    var check = document.createElement("div");
    check.className = "chat-check-row";
    var cb = document.createElement("input");
    cb.type = "checkbox";
    cb.id = "chat-shell-approval-mode";
    var label = document.createElement("label");
    label.setAttribute("for", "chat-shell-approval-mode");
    label.textContent = "ツール実行を自動承認";
    check.appendChild(cb);
    check.appendChild(label);
    var hint = document.createElement("span");
    hint.className = "setting-hint";
    hint.textContent =
      "sandbox の bash など、承認が要るツールを確認なしで実行する";
    row.appendChild(check);
    row.appendChild(hint);
    host.insertBefore(row, host.firstChild);
  }

  function applyChatConfig(cfg) {
    if (!cfg) return;
    const set = (id, v) => {
      const el = document.getElementById(id);
      if (el && v !== undefined && v !== null) el.value = v;
    };
    const setChecked = (id, v) => {
      const el = document.getElementById(id);
      if (el) el.checked = v === true;
    };
    set("chat-model", cfg.model || "");
    set("chat-api-key", cfg.api_key || "");
    set("chat-base-url", cfg.base_url || "");

    // 既定値の単一の正は defaults API（N.Chat.settings._defaultOf）。
    // ここでのリテラルは API 未取得時の保険。
    var _defaultOf = N.Chat.settings._defaultOf;
    set(
      "chat-max-tool-calls",
      cfg.max_tool_calls || (_defaultOf("max_tool_calls") ?? 5),
    );
    set("chat-system-prompt", cfg.system_prompt || "");
    setChecked("chat-auto-extract", cfg.auto_extract !== false);
    set("chat-extract-model", cfg.extract_model || "");
    set(
      "chat-extract-max-tokens",
      cfg.extract_max_tokens || (_defaultOf("extract_max_tokens") ?? 512),
    );
    setChecked("chat-enable-memory-tools", cfg.enable_memory_tools !== false);
    // Reasoning settings (R7/R8)
    const reasoningLabels = ["low", "medium", "high", "max"];
    setChecked("chat-reasoning-enabled", cfg.reasoning_enabled === true);
    const reasoningCb = document.getElementById("chat-reasoning-enabled");
    const reasoningSlider = document.getElementById("chat-reasoning-effort");
    const reasoningVal = document.getElementById("chat-reasoning-effort-val");
    if (reasoningSlider && reasoningVal) {
      var effIdx = reasoningLabels.indexOf(cfg.reasoning_effort);
      if (effIdx < 0) effIdx = 1;
      reasoningSlider.value = effIdx;
      reasoningVal.textContent = reasoningLabels[effIdx];
    }
    if (reasoningCb && reasoningSlider) {
      reasoningSlider.disabled = !reasoningCb.checked;
      reasoningCb.onchange = function () {
        reasoningSlider.disabled = !this.checked;
      };
    }
    N.Chat.state.mcpServers = cfg.mcp_servers || [];
    N.Chat.settings.renderMcpJson(N.Chat.state.mcpServers);
    // Auto-fetch MCP tools for per-server display
    if (N.Chat.tools && N.Chat.tools.fetch) {
      N.Chat.tools.fetch();
    }
    const toolMax = document.getElementById("chat-tool-result-max");
    const toolMaxVal = document.getElementById("chat-tool-max-val");
    if (toolMax && cfg.tool_result_max_chars != null) {
      toolMax.value = cfg.tool_result_max_chars;
      if (toolMaxVal) toolMaxVal.textContent = cfg.tool_result_max_chars;
    }
    N.Chat.state.enabledSkills = cfg.enabled_skills || [];
    N.Chat.state.disabledTools = new Set(cfg.disabled_tools || []);
    N.Chat.settings.renderBuiltinTools();
    // Reflection settings
    setChecked("chat-session-summarize", cfg.session_summarize !== false);
    // Mental model settings
    setChecked("chat-mental-model-enabled", cfg.mental_model_enabled !== false);
    set(
      "chat-mental-model-min-samples",
      cfg.mental_model_min_samples ??
        (_defaultOf("mental_model_min_samples") ?? 3),
    );
    // Retrieval weights
    const setSlider = (id, valId, v) => {
      const el = document.getElementById(id);
      const vel = document.getElementById(valId);
      if (el && v != null) {
        el.value = v;
        if (vel) vel.textContent = parseFloat(v).toFixed(2);
      }
    };
    setSlider(
      "chat-recency-weight",
      "chat-recency-weight-val",
      cfg.retrieval_recency_weight ??
        (_defaultOf("retrieval_recency_weight") ?? 0.3),
    );
    setSlider(
      "chat-importance-weight",
      "chat-importance-weight-val",
      cfg.retrieval_importance_weight ??
        (_defaultOf("retrieval_importance_weight") ?? 0.3),
    );
    setSlider(
      "chat-relevance-weight",
      "chat-relevance-weight-val",
      cfg.retrieval_relevance_weight ??
        (_defaultOf("retrieval_relevance_weight") ?? 0.4),
    );
    // Context compression settings
    set(
      "chat-stored-msgs",
      cfg.max_stored_messages ?? (_defaultOf("max_stored_messages") ?? 1000),
    );
    set("chat-context-max-tokens", cfg.context_max_tokens ?? "");
    var _compressionPct = Math.round(
      (cfg.context_compression_threshold ??
        (_defaultOf("context_compression_threshold") ?? 0.8)) * 100,
    );
    set("chat-compression-threshold", _compressionPct);
    document.getElementById("threshold-display").textContent =
      _compressionPct + "%";
    set(
      "chat-compression-mode",
      cfg.context_compression_mode ||
        (_defaultOf("context_compression_mode") ?? "auto"),
    );
    set(
      "chat-memory-preload",
      cfg.memory_preload_count ?? (_defaultOf("memory_preload_count") ?? 5),
    );
    set(
      "chat-memory-digest",
      cfg.memory_digest_count ?? (_defaultOf("memory_digest_count") ?? 5),
    );
    set("chat-language", cfg.language || (_defaultOf("language") ?? "ja"));
    setChecked(
      "chat-dynamic-tool-selection",
      cfg.dynamic_tool_selection !== false,
    );
    _ensureApprovalRow();
    setChecked("chat-shell-approval-mode", cfg.shell_approval_mode === "auto");
    // UI に出さない allowlist を保存で ask に潰さないため、読んだモードを控える
    var _approvalCb = document.getElementById("chat-shell-approval-mode");
    if (_approvalCb) _approvalCb.dataset.mode = cfg.shell_approval_mode || "ask";
    var el;
    el = document.getElementById("chat-compress-system");
    if (el) el.checked = cfg.context_compress_system_prompt !== false;
    el = document.getElementById("chat-compress-history");
    if (el) el.checked = cfg.context_compress_history !== false;
    el = document.getElementById("chat-parallel-tools");
    if (el) el.checked = cfg.enable_parallel_tools !== false;
    el = document.getElementById("chat-llm-summary");
    if (el) el.checked = cfg.context_use_llm_summary !== false;
    el = document.getElementById("chat-episode-search");
    if (el) el.checked = cfg.episode_search_enabled !== false;
    el = document.getElementById("chat-show-timestamps");
    if (el) el.checked = cfg.show_message_timestamps === true;
    var compThresh = document.getElementById("chat-compression-threshold");
    if (compThresh)
      compThresh.oninput = function () {
        document.getElementById("threshold-display").textContent =
          this.value + "%";
      };
    // Field-group helpers (chunk 3/4): voice/TTS, image gen,
    // brain/emotion decay — same order as the pre-split code.
    N.Chat.settings._applyVoice(cfg, set, setChecked);
    N.Chat.settings._applyImage(cfg, set, setChecked);
    N.Chat.settings.updateSliderLabels();
    N.Chat.settings._applyBrainForgetting(cfg, set, setChecked);
    // ComfyUI URLが設定済みなら疎通確認を自動実行
    if (cfg.image_gen_comfyui_url) {
      N.Chat.settings.checkComfyUI();
    }
    N.Chat.settings._refreshResetButtons();
  }
  // ------------------------------------------------------------------
  // Register namespace (chunk 2/4 — load/apply API)
  // ------------------------------------------------------------------
  N.Chat.settings = N.Chat.settings || {};
  N.Chat.settings.load = loadChatConfig;
  N.Chat.settings.apply = applyChatConfig;
})(window.Nous);
