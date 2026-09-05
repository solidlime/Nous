/* =================================================================
   CHAT SETTINGS — Configuration panel (load/apply/save)
   Extracted from chat.js (Phase 3, Batch 1)
   MCP → chat-settings-mcp.js, Image → chat-settings-image.js
   ================================================================= */
;(function(N) {
var C = N.Core;
var api = C.api, esc = C.esc, toast = C.toast, safeSetHTML = C.safeSetHTML;
var showConfirm = C.showConfirm, showAlert = C.showAlert;
var truncate = C.truncate, relativeTime = C.relativeTime, fmtDate = C.fmtDate;
"use strict";
var S = window.S;

// ------------------------------------------------------------------
// Config loading / applying / saving
// ------------------------------------------------------------------
async function loadChatConfig() {
  try {
    const cfg = await api(
      "/api/chat/" + encodeURIComponent(S.persona) + "/config",
    );
    applyChatConfig(cfg);
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

  set("chat-temperature", cfg.temperature != null ? cfg.temperature : 0.7);
  setChecked("chat-dynamic-temperature", cfg.dynamic_temperature !== false);
  set(
    "chat-emotion-temperature-scale",
    cfg.emotion_temperature_scale != null ? cfg.emotion_temperature_scale : 0.2,
  );
  set("chat-top-p", cfg.top_p != null ? cfg.top_p : "");
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
    dynTempCb.onchange = function () {
      emotionScaleEl.disabled = !this.checked;
    };
  }
  // Top P display sync
  const topPVal = document.getElementById("chat-top-p-val");
  const topPSlider = document.getElementById("chat-top-p");
  if (topPVal && topPSlider) {
    var v = parseFloat(topPSlider.value);
    topPVal.textContent = isNaN(v) ? "—" : v.toFixed(2);
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
    cfg.reflection_threshold != null ? cfg.reflection_threshold : 1.0,
  );
  set(
    "chat-reflection-interval",
    cfg.reflection_min_interval_hours != null
      ? cfg.reflection_min_interval_hours
      : 1.0,
  );
  setChecked("chat-session-summarize", cfg.session_summarize !== false);
  // Mental model settings
  setChecked("chat-mental-model-enabled", cfg.mental_model_enabled !== false);
  set(
    "chat-mental-model-min-samples",
    cfg.mental_model_min_samples != null ? cfg.mental_model_min_samples : 3,
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
    cfg.retrieval_recency_weight != null ? cfg.retrieval_recency_weight : 0.3,
  );
  setSlider(
    "chat-importance-weight",
    "chat-importance-weight-val",
    cfg.retrieval_importance_weight != null
      ? cfg.retrieval_importance_weight
      : 0.3,
  );
  setSlider(
    "chat-relevance-weight",
    "chat-relevance-weight-val",
    cfg.retrieval_relevance_weight != null
      ? cfg.retrieval_relevance_weight
      : 0.4,
  );
  setSlider(
    "chat-retrieval-rrf-k",
    "chat-retrieval-rrf-k-val",
    cfg.retrieval_rrf_k != null ? cfg.retrieval_rrf_k : 5,
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
  setChecked("chat-dynamic-tool-selection", cfg.dynamic_tool_selection !== false);
  var el;
  el = document.getElementById("chat-compress-system"); if (el) el.checked = cfg.context_compress_system_prompt !== false;
  el = document.getElementById("chat-compress-history"); if (el) el.checked = cfg.context_compress_history !== false;
  el = document.getElementById("chat-parallel-tools"); if (el) el.checked = cfg.enable_parallel_tools !== false;
  el = document.getElementById("chat-llm-summary"); if (el) el.checked = cfg.context_use_llm_summary !== false;
  el = document.getElementById("chat-episode-search"); if (el) el.checked = cfg.episode_search_enabled !== false;
  el = document.getElementById("chat-show-timestamps"); if (el) el.checked = cfg.show_message_timestamps === true;
  var compThresh = document.getElementById("chat-compression-threshold");
  if (compThresh) compThresh.oninput = function () {
    document.getElementById("threshold-display").textContent =
      this.value + "%";
  };
  // Voice / TTS settings (TE04)
  var voiceToggle = document.getElementById("chat-voice-enabled");
  if (voiceToggle) {
    voiceToggle.checked = cfg.voice_enabled || false;
    var voiceOptions = document.getElementById("chat-voice-options");
    if (voiceOptions) {
      voiceOptions.classList.toggle("settings-body-hidden", !voiceToggle.checked);
      voiceToggle.onchange = function() {
        voiceOptions.classList.toggle("settings-body-hidden", !this.checked);
      };
    }
  }
  var voiceUrlInput = document.getElementById("chat-voice-url");
  if (voiceUrlInput) voiceUrlInput.value = cfg.voice_url || "";
  // Emotion reflection mode: "off" | "anchor" | "llm" (legacy bools fallback)
  var emotionMode = cfg.voice_emotion_mode;
  if (emotionMode !== "off" && emotionMode !== "anchor" && emotionMode !== "llm") {
    emotionMode = cfg.irodori_caption_llm_enabled && cfg.voice_emotion_link !== false ? "llm"
      : cfg.voice_emotion_link !== false ? "anchor" : "off";
  }
  var modeRadio = document.querySelector('input[name="chat-voice-emotion-mode"][value="' + emotionMode + '"]');
  if (modeRadio) modeRadio.checked = true;
  var llmModelWrap = document.getElementById("chat-irodori-caption-llm-model-wrap");
  if (llmModelWrap) llmModelWrap.style.display = emotionMode === "llm" ? "block" : "none";
  setChecked("chat-voice-auto-play", cfg.voice_auto_play === true);
  // Load voice model name (text input now)
  var voiceModelInput = document.getElementById("chat-voice-model");
  if (voiceModelInput) voiceModelInput.value = cfg.voice_model || "";
  // Irodori advanced params
  var irodoriNumSteps = document.getElementById("chat-irodori-num-steps");
  if (irodoriNumSteps) irodoriNumSteps.value = cfg.irodori_num_steps ?? 30;
  if (irodoriNumSteps) document.getElementById("chat-irodori-num-steps-val").textContent = cfg.irodori_num_steps ?? 30;
  var irodoriCfgText = document.getElementById("chat-irodori-cfg-scale-text");
  if (irodoriCfgText) irodoriCfgText.value = cfg.irodori_cfg_scale_text ?? 3.2;
  if (irodoriCfgText) document.getElementById("chat-irodori-cfg-text-val").textContent = (cfg.irodori_cfg_scale_text ?? 3.2).toFixed(1);
  var irodoriCfgSpeaker = document.getElementById("chat-irodori-cfg-scale-speaker");
  if (irodoriCfgSpeaker) irodoriCfgSpeaker.value = cfg.irodori_cfg_scale_speaker ?? 5.0;
  if (irodoriCfgSpeaker) document.getElementById("chat-irodori-cfg-speaker-val").textContent = (cfg.irodori_cfg_scale_speaker ?? 5.0).toFixed(1);
  var irodoriCfgCaption = document.getElementById("chat-irodori-cfg-scale-caption");
  if (irodoriCfgCaption) irodoriCfgCaption.value = cfg.irodori_cfg_scale_caption ?? 4.2;
  if (irodoriCfgCaption) document.getElementById("chat-irodori-cfg-caption-val").textContent = (cfg.irodori_cfg_scale_caption ?? 4.2).toFixed(1);
  var irodoriChunkMin = document.getElementById("chat-irodori-chunk-min-chars");
  if (irodoriChunkMin) irodoriChunkMin.value = cfg.irodori_chunk_min_chars ?? 85;
  if (irodoriChunkMin) document.getElementById("chat-irodori-chunk-min-val").textContent = cfg.irodori_chunk_min_chars ?? 85;
  var irodoriSeed = document.getElementById("chat-irodori-seed");
  if (irodoriSeed) irodoriSeed.value = cfg.irodori_seed ?? 0;
  var irodoriCaptionLLMModel = document.getElementById("chat-irodori-caption-llm-model");
  if (irodoriCaptionLLMModel) irodoriCaptionLLMModel.value = cfg.irodori_caption_llm_model || "";
  // Voice volume
  var voiceVolume = document.getElementById("chat-voice-volume");
  if (voiceVolume) voiceVolume.value = cfg.voice_volume ?? 1.0;
  if (voiceVolume) document.getElementById("chat-voice-volume-val").textContent = Math.round((cfg.voice_volume ?? 1.0) * 100) + "%";
  // Voice speed
  var voiceSpeed = document.getElementById("chat-voice-speed");
  if (voiceSpeed) voiceSpeed.value = cfg.voice_speed ?? 1.0;
  if (voiceSpeed) document.getElementById("chat-voice-speed-val").textContent = (cfg.voice_speed ?? 1.0).toFixed(2) + "x";
  // Check connection status
  N.Chat.tts.checkConnection();
  // Debug mode
  setChecked("chat-debug-mode", cfg.debug_mode === true);
  const statusEl = document.getElementById("chat-config-status");
  if (statusEl) {
    if (cfg.is_configured) {
      safeSetHTML(statusEl,
        '<span style="color:var(--accent-green)"><i data-lucide="check"></i> APIキー設定済み</span>');
    } else {
      safeSetHTML(statusEl,
        '<span style="color:var(--accent-yellow)"><i data-lucide="alert-triangle"></i> APIキー未設定</span>');
    }
  }

  // Image gen enabled toggle
  var imgGenToggle = document.getElementById("chat-image-gen-enabled");
  if (imgGenToggle) {
    imgGenToggle.checked = cfg.image_gen_enabled || false;
    var imgGenOptions = document.getElementById("chat-image-options");
    if (imgGenOptions) {
      imgGenOptions.classList.toggle("settings-body-hidden", !imgGenToggle.checked);
      imgGenToggle.onchange = function() {
        imgGenOptions.classList.toggle("settings-body-hidden", !this.checked);
      };
    }
  }
  // 画像生成設定
  set("chat-image-gen-comfyui-url", cfg.image_gen_comfyui_url);
  set("chat-image-gen-width", cfg.image_gen_comfyui_width);
  set("chat-image-gen-height", cfg.image_gen_comfyui_height);
  set("chat-image-gen-max-width", cfg.image_gen_max_width);
  set("chat-image-gen-max-height", cfg.image_gen_max_height);
  set("chat-image-gen-self-portrait-prompt", cfg.image_gen_self_portrait_prompt);
  set("chat-image-gen-negative-prompt", cfg.image_gen_negative_prompt || "");
  var templateInput = document.getElementById("chat-image-gen-template");
  if (templateInput) templateInput.value = cfg.image_gen_comfyui_workflow_template || "";
  set("chat-image-gen-workflow-source", cfg.image_gen_comfyui_workflow_source);
  var workflowNameInput = document.getElementById("chat-image-gen-workflow-name");
  if (workflowNameInput) workflowNameInput.value = cfg.image_gen_comfyui_workflow_name || "";
  // 構図プリフィックス
  set("chat-image-gen-full-body-prefix", cfg.image_gen_full_body_prefix || "");
  set("chat-image-gen-portrait-prefix", cfg.image_gen_portrait_prefix || "");
  set("chat-image-gen-selfie-prefix", cfg.image_gen_selfie_prefix || "");
  set("chat-image-gen-scene-prefix", cfg.image_gen_scene_prefix || "");
  // Image caption (non-vision providers)
  setChecked("chat-image-caption-enabled", cfg.image_caption_enabled !== false);
  set("chat-image-caption-provider", cfg.image_caption_provider || "openai_compat");
  set("chat-image-caption-model", cfg.image_caption_model || "");
  set("chat-image-caption-api-key", cfg.image_caption_api_key || "");
  set("chat-image-caption-base-url", cfg.image_caption_base_url || "");
  // プリセット解像度 復元
  var _presetNames = ["portrait_large","portrait_medium","portrait_small","landscape_large","landscape_medium","landscape_small","square_large","square_medium","square_small"];
  var _presets = cfg.image_gen_presets || {};
  _presetNames.forEach(function(name) {
    var el = document.getElementById("chat-image-gen-preset-" + name);
    if (el && _presets[name]) el.value = _presets[name];
  });
  var _defPreset = document.getElementById("chat-image-gen-default-preset");
  if (_defPreset && cfg.image_gen_default_preset) _defPreset.value = cfg.image_gen_default_preset;
  // スライダー値表示更新
  N.Chat.settings.updateSliderLabels();
  // === Auto-capture (moved from Settings) ===
  setChecked("chat-auto-capture-enabled", cfg.auto_capture_enabled === true);
  set("chat-auto-capture-interval", cfg.auto_capture_interval ?? 300);
  set("chat-auto-capture-max-memories", cfg.auto_capture_max_memories ?? 10);
  // === Memory enrichment (simplified) ===
  setChecked("chat-memory-enrichment-enabled", cfg.memory_enrichment_enabled === true);
  set("chat-memory-enrichment-model", cfg.memory_enrichment_model || "");
  setChecked("chat-memory-enrichment-auto-run", cfg.memory_enrichment_auto_run === true);
  set("chat-memory-enrichment-interval", cfg.memory_enrichment_interval ?? 60);
  set("chat-memory-enrichment-prompt-template", cfg.memory_enrichment_prompt_template || "");
  // === Forgetting (moved from Settings) ===
  setChecked("chat-forgetting-enabled", cfg.forgetting_enabled === true);
  set("chat-forgetting-trigger-threshold", cfg.forgetting_trigger_threshold ?? 100);
  set("chat-forgetting-decay-interval-seconds", cfg.forgetting_decay_interval_seconds ?? 86400);
  set("chat-forgetting-min-strength", cfg.forgetting_min_strength ?? 0.1);
  set("chat-forgetting-forget-ratio", cfg.forgetting_forget_ratio ?? 0.2);
  set("chat-forgetting-forget-strength", cfg.forgetting_forget_strength ?? 0.5);
  // Sync min-strength display
  var fs = document.getElementById("chat-forgetting-min-strength");
  if (fs) document.getElementById("chat-forgetting-min-strength-val").textContent = parseFloat(fs.value).toFixed(2);
  // Emotion decay
  set("chat-emotion-decay-half-life-hours", cfg.emotion_decay_half_life_hours ?? 24);
  set("chat-emotion-decay-threshold", cfg.emotion_decay_threshold ?? 0.005);
  set("chat-emotion-neutral-threshold", cfg.emotion_neutral_threshold ?? 0.01);
  // ComfyUI URLが設定済みなら疎通確認を自動実行
  if (cfg.image_gen_comfyui_url) {
    N.Chat.settings.checkComfyUI();
  }
}

async function saveChatConfig() {
  if (!S.persona) {
    toast("ペルソナを選択してください", "error");
    return;
  }
  const baseUrlVal = (document.getElementById("chat-base-url")?.value || "").trim();
  if (!baseUrlVal) {
    toast("Base URL は必須です", "error");
    return;
  }
  const apiKeyEl = document.getElementById("chat-api-key");
  const apiKeyVal = apiKeyEl ? apiKeyEl.value.trim() : "";
  const getChecked = (id) => document.getElementById(id)?.checked ?? false;
  const payload = {
    model: document.getElementById("chat-model").value.trim(),
    api_key: apiKeyVal,
    base_url: document.getElementById("chat-base-url").value.trim(),

    temperature: parseFloat(document.getElementById("chat-temperature").value),
    dynamic_temperature: getChecked("chat-dynamic-temperature"),
    emotion_temperature_scale: parseFloat(
      document.getElementById("chat-emotion-temperature-scale")?.value || "0.2",
    ),
    top_p: (function () {
      var v = parseFloat(document.getElementById("chat-top-p")?.value);
      return isNaN(v) ? null : v;
    })(),
    reasoning_enabled: getChecked("chat-reasoning-enabled"),
    reasoning_effort: (function () {
      var labels = ["low", "medium", "high", "max"];
      var idx = parseInt(
        document.getElementById("chat-reasoning-effort")?.value || "1",
      );
      return labels[idx] || "medium";
    })(),
    max_tokens: parseInt(document.getElementById("chat-max-tokens").value),
    max_stored_messages: parseInt(
      document.getElementById("chat-stored-msgs").value,
    ),
    context_max_tokens: (function () {
      var v = parseInt(
        document.getElementById("chat-context-max-tokens").value,
      );
      return v > 0 ? v : null;
    })(),
    context_compression_threshold:
      parseFloat(document.getElementById("chat-compression-threshold").value) /
      100,
    context_compression_mode: document.getElementById("chat-compression-mode")
      .value,
    context_keep_recent_turns: parseInt(
      document.getElementById("chat-keep-recent").value,
    ),
    context_compress_system_prompt: document.getElementById(
      "chat-compress-system",
    ).checked,
    context_compress_history: document.getElementById("chat-compress-history")
      .checked,
    memory_preload_count: parseInt(
      document.getElementById("chat-memory-preload").value,
    ),
    memory_digest_count: parseInt(
      document.getElementById("chat-memory-digest")?.value || "5",
    ),
    language: document.getElementById("chat-language")?.value || "ja",
    dynamic_tool_selection: getChecked("chat-dynamic-tool-selection"),
    enable_parallel_tools: document.getElementById("chat-parallel-tools")
      .checked,
    context_use_llm_summary: getChecked("chat-llm-summary"),
    episode_search_enabled: getChecked("chat-episode-search"),
    show_message_timestamps: getChecked("chat-show-timestamps"),
    max_tool_calls: parseInt(
      document.getElementById("chat-max-tool-calls")?.value || "5",
    ),
    system_prompt: document.getElementById("chat-system-prompt").value.trim(),
    auto_extract: getChecked("chat-auto-extract"),
    extract_model:
      document.getElementById("chat-extract-model")?.value.trim() || "",
    extract_max_tokens: parseInt(
      document.getElementById("chat-extract-max-tokens")?.value || "512",
    ),
    enable_memory_tools: getChecked("chat-enable-memory-tools"),
    mcp_servers: N.Chat.settings.parseMcpJson(),
    tool_result_max_chars: parseInt(
      document.getElementById("chat-tool-result-max")?.value || "4000",
    ),
    enabled_skills: (N.Chat.settings.BUILTIN_SKILLS || ["search"]).concat(
      (N.Chat.state.enabledSkills || []).filter(function (s) {
        return !(N.Chat.settings.BUILTIN_SKILLS || ["search"]).includes(s);
      }),
    ),
    disabled_tools: Array.from(N.Chat.state.disabledTools || []),
    reflection_enabled: getChecked("chat-reflection-enabled"),
    reflection_threshold: parseFloat(
      document.getElementById("chat-reflection-threshold")?.value || "1.0",
    ),
    reflection_min_interval_hours: parseFloat(
      document.getElementById("chat-reflection-interval")?.value || "1.0",
    ),
    session_summarize: getChecked("chat-session-summarize"),
    retrieval_recency_weight: parseFloat(
      document.getElementById("chat-recency-weight")?.value || "0.3",
    ),
    retrieval_importance_weight: parseFloat(
      document.getElementById("chat-importance-weight")?.value || "0.3",
    ),
    retrieval_relevance_weight: parseFloat(
      document.getElementById("chat-relevance-weight")?.value || "0.4",
    ),
    retrieval_rrf_k: parseFloat(
      document.getElementById("chat-retrieval-rrf-k")?.value || "5",
    ),
    mental_model_enabled: getChecked("chat-mental-model-enabled"),
    mental_model_min_samples: parseInt(
      document.getElementById("chat-mental-model-min-samples")?.value || "3",
    ),
    debug_mode: getChecked("chat-debug-mode"),
    // === Auto-capture (moved from Settings) ===
    auto_capture_enabled: getChecked("chat-auto-capture-enabled"),
    auto_capture_interval: parseInt(document.getElementById("chat-auto-capture-interval")?.value || "300"),
    auto_capture_max_memories: parseInt(document.getElementById("chat-auto-capture-max-memories")?.value || "10"),
    // === Memory enrichment (simplified) ===
    memory_enrichment_enabled: getChecked("chat-memory-enrichment-enabled"),
    memory_enrichment_model: document.getElementById("chat-memory-enrichment-model")?.value.trim() || "",
    memory_enrichment_auto_run: getChecked("chat-memory-enrichment-auto-run"),
    memory_enrichment_interval: parseInt(document.getElementById("chat-memory-enrichment-interval")?.value || "60"),
    memory_enrichment_prompt_template: document.getElementById("chat-memory-enrichment-prompt-template")?.value.trim() || "",
    // === Forgetting (moved from Settings) ===
    forgetting_enabled: getChecked("chat-forgetting-enabled"),
    forgetting_trigger_threshold: parseInt(document.getElementById("chat-forgetting-trigger-threshold")?.value || "100"),
    forgetting_decay_interval_seconds: parseInt(document.getElementById("chat-forgetting-decay-interval-seconds")?.value || "86400"),
    forgetting_min_strength: parseFloat(document.getElementById("chat-forgetting-min-strength")?.value || "0.1"),
    forgetting_forget_ratio: parseFloat(document.getElementById("chat-forgetting-forget-ratio")?.value || "0.2"),
    forgetting_forget_strength: parseFloat(document.getElementById("chat-forgetting-forget-strength")?.value || "0.5"),
    // Emotion decay
    emotion_decay_half_life_hours: parseFloat(document.getElementById("chat-emotion-decay-half-life-hours")?.value || "24"),
    emotion_decay_threshold: parseFloat(document.getElementById("chat-emotion-decay-threshold")?.value || "0.005"),
    emotion_neutral_threshold: parseFloat(document.getElementById("chat-emotion-neutral-threshold")?.value || "0.01"),
    // 画像生成設定 — ComfyUI
    image_gen_enabled: getChecked("chat-image-gen-enabled"),
    image_gen_comfyui_url: (document.getElementById("chat-image-gen-comfyui-url")?.value || "").trim(),
    image_gen_comfyui_width: parseInt(document.getElementById("chat-image-gen-width")?.value || "1024"),
    image_gen_comfyui_height: parseInt(document.getElementById("chat-image-gen-height")?.value || "1024"),
    image_gen_max_width: parseInt(document.getElementById("chat-image-gen-max-width")?.value || "1200"),
    image_gen_max_height: parseInt(document.getElementById("chat-image-gen-max-height")?.value || "1200"),
    image_gen_self_portrait_prompt: document.getElementById("chat-image-gen-self-portrait-prompt")?.value || "",
    image_gen_negative_prompt: document.getElementById("chat-image-gen-negative-prompt")?.value || "",
    // プリセット解像度
    image_gen_presets: (function() {
      var p = {};
      ["portrait_large","portrait_medium","portrait_small","landscape_large","landscape_medium","landscape_small","square_large","square_medium","square_small"].forEach(function(name) {
        var el = document.getElementById("chat-image-gen-preset-" + name);
        if (el && el.value.trim()) p[name] = el.value.trim();
      });
      return p;
    })(),
    image_gen_default_preset: document.getElementById("chat-image-gen-default-preset")?.value || "square_medium",
    image_gen_comfyui_workflow_template: document.getElementById("chat-image-gen-template")?.value || "",
    image_gen_comfyui_workflow_source: document.getElementById("chat-image-gen-workflow-source")?.value || "local",
    image_gen_comfyui_workflow_name: document.getElementById("chat-image-gen-workflow-name")?.value || "",
    // 構図プリフィックス
    image_gen_full_body_prefix: document.getElementById("chat-image-gen-full-body-prefix")?.value || "",
    image_gen_portrait_prefix: document.getElementById("chat-image-gen-portrait-prefix")?.value || "",
    image_gen_selfie_prefix: document.getElementById("chat-image-gen-selfie-prefix")?.value || "",
    image_gen_scene_prefix: document.getElementById("chat-image-gen-scene-prefix")?.value || "",
    // Image caption (non-vision providers)
    image_caption_enabled: getChecked("chat-image-caption-enabled"),
    image_caption_provider: document.getElementById("chat-image-caption-provider")?.value || "openai_compat",
    image_caption_model: document.getElementById("chat-image-caption-model")?.value.trim() || "",
    image_caption_api_key: document.getElementById("chat-image-caption-api-key")?.value || "",
    image_caption_base_url: document.getElementById("chat-image-caption-base-url")?.value.trim() || "",
    // Voice / TTS settings (TE04)
    voice_url: document.getElementById("chat-voice-url")?.value || "",
    voice_auto_play: getChecked("chat-voice-auto-play"),
    voice_emotion_mode: document.querySelector('input[name="chat-voice-emotion-mode"]:checked')?.value || "anchor",
    voice_emotion_link: (document.querySelector('input[name="chat-voice-emotion-mode"]:checked')?.value || "anchor") !== "off",
    voice_model: document.getElementById("chat-voice-model")?.value || "",
    // Irodori advanced params
    irodori_num_steps: parseInt(document.getElementById("chat-irodori-num-steps")?.value) || 30,
    irodori_cfg_scale_text: parseFloat(document.getElementById("chat-irodori-cfg-scale-text")?.value) || 3.2,
    irodori_cfg_scale_speaker: parseFloat(document.getElementById("chat-irodori-cfg-scale-speaker")?.value) || 5.0,
    irodori_cfg_scale_caption: parseFloat(document.getElementById("chat-irodori-cfg-scale-caption")?.value) || 4.2,
    irodori_chunk_min_chars: parseInt(document.getElementById("chat-irodori-chunk-min-chars")?.value) || 85,
    irodori_seed: parseInt(document.getElementById("chat-irodori-seed")?.value) || 0,
    irodori_caption_llm_enabled: (document.querySelector('input[name="chat-voice-emotion-mode"]:checked')?.value || "anchor") === "llm",
    irodori_caption_llm_model: document.getElementById("chat-irodori-caption-llm-model")?.value || "",
    // Voice volume
    voice_volume: parseFloat(document.getElementById("chat-voice-volume")?.value) ?? 1.0,
    voice_speed: parseFloat(document.getElementById("chat-voice-speed")?.value) ?? 1.0,
    voice_enabled: getChecked("chat-voice-enabled"),
  };
  const btn = document.querySelector(".chat-save-btn");
  if (btn) {
    btn.disabled = true;
    safeSetHTML(btn, '<i data-lucide="loader"></i> 保存中...');
    if (typeof lucide !== "undefined") lucide.createIcons();
  }
  try {
    const cfg = await api(
      "/api/chat/" + encodeURIComponent(S.persona) + "/config",
      {
        method: "POST",
        body: JSON.stringify(payload),
      },
    );
    applyChatConfig(cfg);
    toast("チャット設定を保存しました", "success");
  } catch (e) {
    toast("保存失敗: " + e.message, "error");
  } finally {
    if (btn) {
      btn.disabled = false;
      safeSetHTML(btn, '<i data-lucide="save"></i> 設定を保存');
      if (typeof lucide !== "undefined") lucide.createIcons();
    }
  }
}

// ------------------------------------------------------------------
// Note: MCP JSON rendering/parsing → chat-settings-mcp.js
//       ComfyUI helpers → chat-settings-image.js
// ------------------------------------------------------------------

// ------------------------------------------------------------------
// Register namespace (MCP/Image additions in chat-settings-mcp.js / chat-settings-image.js)
// ------------------------------------------------------------------
N.Chat.settings = {
  load: loadChatConfig,
  apply: applyChatConfig,
  save: saveChatConfig,
};

})(window.Nous);
