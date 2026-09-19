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
  var api = C.api,
    esc = C.esc,
    toast = C.toast,
    safeSetHTML = C.safeSetHTML;
  var showConfirm = C.showConfirm,
    showAlert = C.showAlert;
  var truncate = C.truncate,
    relativeTime = C.relativeTime,
    fmtDate = C.fmtDate;
  var S = window.S;

  // ------------------------------------------------------------------
  // Config loading / applying (chunk 2/4)
  // ------------------------------------------------------------------
  async function loadChatConfig() {
    var defaultsP = loadConfigDefaults();
    try {
      const cfg = await api(
        "/api/chat/" + encodeURIComponent(S.persona) + "/config",
      );
      await defaultsP;
      N.Chat.settings.apply(cfg);
      N.Chat.settings.injectResetButtons();

    } catch (e) {
      document.getElementById("chat-config-status").textContent =
        "設定読込失敗: " + e.message;
    }
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

    set("chat-temperature", cfg.temperature == null ? 0.7 : cfg.temperature);
    setChecked("chat-dynamic-temperature", cfg.dynamic_temperature !== false);
    set(
      "chat-emotion-temperature-scale",
      cfg.emotion_temperature_scale == null
        ? 0.2
        : cfg.emotion_temperature_scale,
    );
    set("chat-top-p", cfg.top_p == null ? 1 : cfg.top_p);
    set("chat-max-tokens", cfg.max_tokens || 8192);
    set("chat-max-tool-calls", cfg.max_tool_calls || 5);
    set("chat-system-prompt", cfg.system_prompt || "");
    setChecked("chat-auto-extract", cfg.auto_extract !== false);
    set("chat-extract-model", cfg.extract_model || "");
    set("chat-extract-max-tokens", cfg.extract_max_tokens || 512);
    setChecked("chat-enable-memory-tools", cfg.enable_memory_tools !== false);
    // Temperature display sync
    const tempEl = document.getElementById("chat-temp-val");
    const tempSlider = document.getElementById("chat-temperature");
    if (tempEl && tempSlider) {
      tempEl.textContent = parseFloat(tempSlider.value).toFixed(2);
    }
    // Dynamic temperature control
    const dynTempCb = document.getElementById("chat-dynamic-temperature");
    const emotionScaleEl = document.getElementById(
      "chat-emotion-temperature-scale",
    );
    if (dynTempCb && emotionScaleEl) {
      emotionScaleEl.disabled = !dynTempCb.checked;
      if (!dynTempCb._bound) {
        dynTempCb._bound = true;
        dynTempCb.onchange = function () {
          emotionScaleEl.disabled = !this.checked;
        };
      }
    }
    // Top P display sync
    const topPVal = document.getElementById("chat-top-p-val");
    const topPSlider = document.getElementById("chat-top-p");
    if (topPVal && topPSlider) {
      var v = parseFloat(topPSlider.value);
      topPVal.textContent = isNaN(v) ? "—" : v.toFixed(2);
    }
    // Top P is optional: null = unset → disable the slider and send null on save.
    var topPEnabled = document.getElementById("chat-top-p-enabled");
    if (topPEnabled) {
      topPEnabled.checked = cfg.top_p != null;
      if (topPSlider) topPSlider.disabled = !topPEnabled.checked;
      topPEnabled.onchange = function () {
        var s = document.getElementById("chat-top-p");
        if (!s) return;
        s.disabled = !this.checked;
        if (this.checked)
          s.dispatchEvent(new Event("input", { bubbles: true }));
      };
    }
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
    // Reflection settings
    setChecked("chat-reflection-enabled", cfg.reflection_enabled !== false);
    set(
      "chat-reflection-threshold",
      cfg.reflection_threshold == null ? 1.0 : cfg.reflection_threshold,
    );
    set(
      "chat-reflection-interval",
      cfg.reflection_min_interval_hours == null
        ? 1.0
        : cfg.reflection_min_interval_hours,
    );
    setChecked("chat-session-summarize", cfg.session_summarize !== false);
    // Mental model settings
    setChecked("chat-mental-model-enabled", cfg.mental_model_enabled !== false);
    set(
      "chat-mental-model-min-samples",
      cfg.mental_model_min_samples == null ? 3 : cfg.mental_model_min_samples,
    );
    // Character judge / repair settings
    setChecked("chat-character-judge-enabled", cfg.character_judge_enabled !== false);
    set(
      "chat-character-repair-max-attempts",
      cfg.character_repair_max_attempts == null ? 2 : cfg.character_repair_max_attempts,
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
      cfg.retrieval_recency_weight == null ? 0.3 : cfg.retrieval_recency_weight,
    );
    setSlider(
      "chat-importance-weight",
      "chat-importance-weight-val",
      cfg.retrieval_importance_weight == null
        ? 0.3
        : cfg.retrieval_importance_weight,
    );
    setSlider(
      "chat-relevance-weight",
      "chat-relevance-weight-val",
      cfg.retrieval_relevance_weight == null
        ? 0.4
        : cfg.retrieval_relevance_weight,
    );
    // Context compression settings
    set("chat-stored-msgs", cfg.max_stored_messages ?? 200);
    set("chat-context-max-tokens", cfg.context_max_tokens ?? "");
    set(
      "chat-compression-threshold",
      Math.round((cfg.context_compression_threshold ?? 0.8) * 100),
    );
    document.getElementById("threshold-display").textContent =
      Math.round((cfg.context_compression_threshold ?? 0.8) * 100) + "%";
    set("chat-compression-mode", cfg.context_compression_mode || "auto");
    set("chat-keep-recent", cfg.context_keep_recent_turns ?? 2);
    set("chat-memory-preload", cfg.memory_preload_count ?? 5);
    set("chat-memory-digest", cfg.memory_digest_count ?? 5);
    set("chat-language", cfg.language || "ja");
    setChecked(
      "chat-dynamic-tool-selection",
      cfg.dynamic_tool_selection !== false,
    );
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
    // brain/forgetting/emotion decay — same order as the pre-split code.
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
