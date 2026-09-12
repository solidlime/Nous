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
// Defaults API + per-field "reset to default"
// ------------------------------------------------------------------
// Only a DOM-id -> config-key BINDING map lives here. The default VALUES
// come from GET /api/chat/{persona}/config/defaults, so adding a setting
// on the backend needs no constant duplicated on the frontend.
// Optional 3rd element: "effort" | "percent" | "radio" | "preset"
// (4th = preset name for "preset"). Otherwise plain value/checkbox.
var RESET_FIELDS = [
  ["chat-model", "model"],
  ["chat-api-key", "api_key"],
  ["chat-base-url", "base_url"],
  ["chat-temperature", "temperature"],
  ["chat-dynamic-temperature", "dynamic_temperature"],
  ["chat-emotion-temperature-scale", "emotion_temperature_scale"],
  ["chat-top-p", "top_p"],
  ["chat-reasoning-enabled", "reasoning_enabled"],
  ["chat-reasoning-effort", "reasoning_effort", "effort"],
  ["chat-max-tokens", "max_tokens"],
  ["chat-language", "language"],
  ["chat-show-timestamps", "show_message_timestamps"],
  ["chat-max-tool-calls", "max_tool_calls"],
  ["chat-system-prompt", "system_prompt"],
  ["chat-stored-msgs", "max_stored_messages"],
  ["chat-context-max-tokens", "context_max_tokens"],
  ["chat-compression-threshold", "context_compression_threshold", "percent"],
  ["chat-compression-mode", "context_compression_mode"],
  ["chat-keep-recent", "context_keep_recent_turns"],
  ["chat-memory-preload", "memory_preload_count"],
  ["chat-memory-digest", "memory_digest_count"],
  ["chat-compress-system", "context_compress_system_prompt"],
  ["chat-compress-history", "context_compress_history"],
  ["chat-parallel-tools", "enable_parallel_tools"],
  ["chat-llm-summary", "context_use_llm_summary"],
  ["chat-episode-search", "episode_search_enabled"],
  ["chat-auto-extract", "auto_extract"],
  ["chat-extract-model", "extract_model"],
  ["chat-extract-max-tokens", "extract_max_tokens"],
  ["chat-enable-memory-tools", "enable_memory_tools"],
  ["chat-reflection-enabled", "reflection_enabled"],
  ["chat-reflection-threshold", "reflection_threshold"],
  ["chat-reflection-interval", "reflection_min_interval_hours"],
  ["chat-session-summarize", "session_summarize"],
  ["chat-mental-model-enabled", "mental_model_enabled"],
  ["chat-mental-model-min-samples", "mental_model_min_samples"],
  ["chat-tool-result-max", "tool_result_max_chars"],
  ["chat-recency-weight", "retrieval_recency_weight"],
  ["chat-importance-weight", "retrieval_importance_weight"],
  ["chat-relevance-weight", "retrieval_relevance_weight"],
  ["chat-debug-mode", "debug_mode"],
  ["chat-dynamic-tool-selection", "dynamic_tool_selection"],
  ["chat-voice-enabled", "voice_enabled"],
  ["chat-voice-url", "voice_url"],
  ["chat-voice-model", "voice_model"],
  ["chat-voice-auto-play", "voice_auto_play"],
  ["chat-voice-volume", "voice_volume"],
  ["chat-voice-speed", "voice_speed"],
  ["chat-voice-emotion-mode", "voice_emotion_mode", "radio"],
  ["chat-irodori-num-steps", "irodori_num_steps"],
  ["chat-irodori-cfg-scale-text", "irodori_cfg_scale_text"],
  ["chat-irodori-cfg-scale-speaker", "irodori_cfg_scale_speaker"],
  ["chat-irodori-cfg-scale-caption", "irodori_cfg_scale_caption"],
  ["chat-irodori-chunk-min-chars", "irodori_chunk_min_chars"],
  ["chat-irodori-seed", "irodori_seed"],
  ["chat-irodori-caption-llm-model", "irodori_caption_llm_model"],
  ["chat-image-gen-enabled", "image_gen_enabled"],
  ["chat-image-gen-comfyui-url", "image_gen_comfyui_url"],
  ["chat-image-gen-width", "image_gen_comfyui_width"],
  ["chat-image-gen-height", "image_gen_comfyui_height"],
  ["chat-image-gen-max-width", "image_gen_max_width"],
  ["chat-image-gen-max-height", "image_gen_max_height"],
  ["chat-image-gen-template", "image_gen_comfyui_workflow_template"],
  ["chat-image-gen-workflow-source", "image_gen_comfyui_workflow_source"],
  ["chat-image-gen-workflow-name", "image_gen_comfyui_workflow_name"],
  ["chat-image-gen-default-preset", "image_gen_default_preset"],
  ["chat-image-gen-self-portrait-prompt", "image_gen_self_portrait_prompt"],
  ["chat-image-gen-negative-prompt", "image_gen_negative_prompt"],
  ["chat-image-gen-full-body-prefix", "image_gen_full_body_prefix"],
  ["chat-image-gen-portrait-prefix", "image_gen_portrait_prefix"],
  ["chat-image-gen-selfie-prefix", "image_gen_selfie_prefix"],
  ["chat-image-gen-scene-prefix", "image_gen_scene_prefix"],
  ["chat-image-gen-preset-portrait_large", "image_gen_presets", "preset", "portrait_large"],
  ["chat-image-gen-preset-portrait_medium", "image_gen_presets", "preset", "portrait_medium"],
  ["chat-image-gen-preset-portrait_small", "image_gen_presets", "preset", "portrait_small"],
  ["chat-image-gen-preset-landscape_large", "image_gen_presets", "preset", "landscape_large"],
  ["chat-image-gen-preset-landscape_medium", "image_gen_presets", "preset", "landscape_medium"],
  ["chat-image-gen-preset-landscape_small", "image_gen_presets", "preset", "landscape_small"],
  ["chat-image-gen-preset-square_large", "image_gen_presets", "preset", "square_large"],
  ["chat-image-gen-preset-square_medium", "image_gen_presets", "preset", "square_medium"],
  ["chat-image-gen-preset-square_small", "image_gen_presets", "preset", "square_small"],
  ["chat-image-caption-enabled", "image_caption_enabled"],
  ["chat-image-caption-provider", "image_caption_provider"],
  ["chat-image-caption-model", "image_caption_model"],
  ["chat-image-caption-api-key", "image_caption_api_key"],
  ["chat-image-caption-base-url", "image_caption_base_url"],
  ["chat-memory-enrichment-enabled", "memory_enrichment_enabled"],
  ["chat-brain-auto-run", "brain_enrich_auto_run"],
  ["chat-brain-enrich-interval", "brain_enrich_interval_seconds"],
  ["chat-brain-batch-limit", "brain_enrich_batch_limit"],
  ["chat-brain-idle-after-seconds", "brain_idle_after_seconds"],
  ["chat-brain-min-batch-size", "brain_min_batch_size"],
  ["chat-brain-max-defer-seconds", "brain_max_defer_seconds"],
  ["chat-brain-monologue", "brain_monologue_enabled"],
  ["chat-brain-reasoning", "brain_reasoning_enabled"],
  ["chat-brain-reasoning-effort", "brain_reasoning_effort"],
  ["chat-brain-spontaneous", "brain_spontaneous_enabled"],
  ["chat-brain-spontaneous-interval", "brain_spontaneous_interval_hours"],
  ["chat-brain-max-tokens", "brain_max_tokens"],
  ["chat-brain-novelty-sim", "brain_novelty_sim_threshold"],
  ["chat-brain-novelty-importance", "brain_novelty_importance_threshold"],
  ["chat-brain-novelty-multiplier", "brain_novelty_stability_multiplier"],
  ["chat-brain-emotion-gain-k", "brain_emotion_gain_k"],
  ["chat-brain-rif-rho", "brain_rif_suppression_rho"],
  ["chat-brain-separation-threshold", "brain_link_separation_threshold"],
  ["chat-brain-reflection-retrieval-penalty", "reflection_retrieval_penalty"],
  ["chat-brain-reflection-injection-min-similarity", "reflection_injection_min_similarity"],
  ["chat-brain-reflection-injection-margin", "reflection_injection_margin"],
  ["chat-brain-graph-flash", "brain_graph_flash_enabled"],
  ["chat-brain-llm-dedicated", "brain_llm_dedicated"],
  ["chat-brain-llm-provider", "brain_llm_provider"],
  ["chat-brain-llm-model", "brain_llm_model"],
  ["chat-brain-llm-base-url", "brain_llm_base_url"],
  ["chat-brain-llm-api-key", "brain_llm_api_key"],
  ["chat-forgetting-enabled", "forgetting_enabled"],
  ["chat-forgetting-trigger-threshold", "forgetting_trigger_threshold"],
  ["chat-forgetting-decay-interval-seconds", "forgetting_decay_interval_seconds"],
  ["chat-forgetting-min-strength", "forgetting_min_strength"],
  ["chat-forgetting-forget-ratio", "forgetting_forget_ratio"],
  ["chat-forgetting-forget-strength", "forgetting_forget_strength"],
  ["chat-emotion-decay-half-life-hours", "emotion_decay_half_life_hours"],
  ["chat-emotion-decay-threshold", "emotion_decay_threshold"],
  ["chat-emotion-neutral-threshold", "emotion_neutral_threshold"],
];

var _defaultsCache = null;
var _defaultsPersona = null;
var _resetButtons = {};

async function loadConfigDefaults(force) {
  if (!S.persona) return null;
  if (!force && _defaultsCache && _defaultsPersona === S.persona) {
    return _defaultsCache;
  }
  try {
    var data = await api(
      "/api/chat/" + encodeURIComponent(S.persona) + "/config/defaults",
    );
    _defaultsCache = data && data.fields ? data : { fields: {} };
  } catch (_) {
    _defaultsCache = { fields: {} };
  }
  _defaultsPersona = S.persona;
  return _defaultsCache;
}

function _defaultOf(key) {
  if (!_defaultsCache || !_defaultsCache.fields) return undefined;
  var meta = _defaultsCache.fields[key];
  return meta ? meta.default : undefined;
}

function _helpOf(key) {
  if (!_defaultsCache || !_defaultsCache.fields) return "";
  var meta = _defaultsCache.fields[key];
  return meta && meta.help ? meta.help : "";
}

function _defaultToDisplay(def, kind, name) {
  if (kind === "percent") return String(Math.round((def || 0) * 100));
  if (kind === "effort") {
    var i = ["low", "medium", "high", "max"].indexOf(String(def));
    return String(i < 0 ? 1 : i);
  }
  if (kind === "preset") {
    return String(def && def[name] != null ? def[name] : "");
  }
  if (kind === "radio") return def == null ? "off" : String(def);
  return def == null ? "" : String(def);
}

function _currentDisplay(el, kind) {
  if (el.type === "checkbox") return el.checked;
  if (kind === "radio") {
    var on = document.querySelector(
      'input[name="' + el.getAttribute("name") + '"]:checked',
    );
    return on ? on.value : "";
  }
  return String(el.value);
}

function _fieldElement(entry) {
  var el = document.getElementById(entry[0]);
  if (!el && entry[2] === "radio") {
    el = document.querySelector('input[name="' + entry[0] + '"]');
  }
  return el;
}

function _isFieldDirty(entry) {
  var el = _fieldElement(entry);
  if (!el) return false;
  var def = _defaultOf(entry[1]);
  if (def === undefined) return false;
  return _currentDisplay(el, entry[2]) !== _defaultToDisplay(def, entry[2], entry[3]);
}

function _injectResetButtons() {
  for (var i = 0; i < RESET_FIELDS.length; i++) {
    var entry = RESET_FIELDS[i];
    var el = _fieldElement(entry);
    if (!el) continue;
    if (_resetButtons[entry[0]] && _resetButtons[entry[0]].isConnected) continue;
    // Field help comes from the defaults API (pydantic descriptions) — the
    // frontend keeps no per-field help text of its own.
    var help = _helpOf(entry[1]);
    if (help && entry[2] !== "radio" && !el.getAttribute("title")) {
      el.setAttribute("title", help);
    }
    var btn = document.createElement("button");
    btn.type = "button";
    btn.className = "chat-reset-btn";
    btn.setAttribute("data-reset-for", entry[0]);
    btn.setAttribute("title", "デフォルトに戻す");
    btn.setAttribute("aria-label", "デフォルトに戻す");
    btn.innerHTML = '<i data-lucide="rotate-ccw"></i>';
    if (el.type === "checkbox") {
      var row = el.closest(".chat-check-row") || el.parentElement;
      if (!row) continue;
      row.appendChild(btn);
      btn.classList.add("chat-reset-inline");
    } else if (entry[2] === "radio") {
      var holder = el.closest("div") || el.parentElement;
      if (!holder) continue;
      holder.classList.add("chat-reset-holder");
      holder.appendChild(btn);
      btn.classList.add("chat-reset-corner");
    } else {
      var wrap = document.createElement("span");
      wrap.className = "chat-reset-wrap";
      if (el.tagName === "SELECT") wrap.classList.add("chat-reset-wrap-select");
      el.parentNode.insertBefore(wrap, el);
      wrap.appendChild(el);
      wrap.appendChild(btn);
    }
    _resetButtons[entry[0]] = btn;
  }
  _refreshResetButtons();
  _bindResetListeners();
  if (N.Core && N.Core.refreshIcons) N.Core.refreshIcons();
}

function _refreshResetButtons() {
  for (var i = 0; i < RESET_FIELDS.length; i++) {
    var btn = _resetButtons[RESET_FIELDS[i][0]];
    if (!btn) continue;
    btn.classList.toggle("is-dirty", _isFieldDirty(RESET_FIELDS[i]));
  }
}

function _resetField(id) {
  var entry = null;
  for (var i = 0; i < RESET_FIELDS.length; i++) {
    if (RESET_FIELDS[i][0] === id) {
      entry = RESET_FIELDS[i];
      break;
    }
  }
  if (!entry) return;
  var el = _fieldElement(entry);
  if (!el) return;
  var def = _defaultOf(entry[1]);
  if (def === undefined) return;
  if (el.type === "checkbox") {
    el.checked = !!def;
  } else if (entry[2] === "radio") {
    var val = _defaultToDisplay(def, "radio");
    var radios = document.querySelectorAll(
      'input[name="' + el.getAttribute("name") + '"]',
    );
    for (var j = 0; j < radios.length; j++) {
      if (radios[j].value === val) radios[j].checked = true;
    }
  } else {
    el.value = _defaultToDisplay(def, entry[2], entry[3]);
  }
  // Reuse the existing delegation for mirror/dependent-token sync. Never saves.
  el.dispatchEvent(new Event("input", { bubbles: true }));
  el.dispatchEvent(new Event("change", { bubbles: true }));
  if (N.Chat.settings.updateSliderLabels) N.Chat.settings.updateSliderLabels();
  _refreshResetButtons();
}

function _bindResetListeners() {
  if (_bindResetListeners._bound) return;
  _bindResetListeners._bound = true;
  document.addEventListener("click", function(e) {
    var btn =
      e.target && e.target.closest ? e.target.closest(".chat-reset-btn") : null;
    if (!btn) return;
    e.preventDefault();
    e.stopPropagation();
    _resetField(btn.getAttribute("data-reset-for"));
  });
  var onEdit = function() {
    _refreshResetButtons();
  };
  document.addEventListener("input", onEdit);
  document.addEventListener("change", onEdit);
}

// ------------------------------------------------------------------
// Config loading / applying / saving
// ------------------------------------------------------------------
async function loadChatConfig() {
  var defaultsP = loadConfigDefaults();
  try {
    const cfg = await api(
      "/api/chat/" + encodeURIComponent(S.persona) + "/config",
    );
    await defaultsP;
    applyChatConfig(cfg);
    _injectResetButtons();
    _bindResetListeners();
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
        '<span class="chat-config-ok"><i data-lucide="check"></i> APIキー設定済み</span>');
    } else {
      safeSetHTML(statusEl,
        '<span class="chat-config-warn"><i data-lucide="alert-triangle"></i> APIキー未設定</span>');
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
  // === Memory enrichment (enabled toggle lives in the brain section) ===
  setChecked("chat-memory-enrichment-enabled", cfg.memory_enrichment_enabled === true);
  // === Brain simulation ===
  setChecked("chat-brain-auto-run", cfg.brain_enrich_auto_run === true);
  set("chat-brain-enrich-interval", cfg.brain_enrich_interval_seconds ?? _defaultOf("brain_enrich_interval_seconds") ?? 60);
  set("chat-brain-batch-limit", cfg.brain_enrich_batch_limit ?? 5);
  set("chat-brain-idle-after-seconds", cfg.brain_idle_after_seconds ?? 120);
  set("chat-brain-min-batch-size", cfg.brain_min_batch_size ?? 3);
  set("chat-brain-max-defer-seconds", cfg.brain_max_defer_seconds ?? _defaultOf("brain_max_defer_seconds") ?? 3600);
  setChecked("chat-brain-monologue", cfg.brain_monologue_enabled === true);
  setChecked("chat-brain-reasoning", cfg.brain_reasoning_enabled === true);
  set("chat-brain-reasoning-effort", cfg.brain_reasoning_effort || "medium");
  setChecked("chat-brain-spontaneous", cfg.brain_spontaneous_enabled === true);
  set("chat-brain-spontaneous-interval", cfg.brain_spontaneous_interval_hours ?? _defaultOf("brain_spontaneous_interval_hours") ?? 1);
  set("chat-brain-max-tokens", cfg.brain_max_tokens ?? 2048);
  set("chat-brain-novelty-sim", cfg.brain_novelty_sim_threshold ?? 0.75);
  set("chat-brain-novelty-importance", cfg.brain_novelty_importance_threshold ?? 0.6);
  set("chat-brain-novelty-multiplier", cfg.brain_novelty_stability_multiplier ?? 2.0);
  set("chat-brain-emotion-gain-k", cfg.brain_emotion_gain_k ?? 0.5);
  set("chat-brain-rif-rho", cfg.brain_rif_suppression_rho ?? 0.05);
  set("chat-brain-separation-threshold", cfg.brain_link_separation_threshold ?? 0.75);
  set("chat-brain-reflection-retrieval-penalty", cfg.reflection_retrieval_penalty ?? 0.5);
  set("chat-brain-reflection-injection-min-similarity", cfg.reflection_injection_min_similarity ?? 0.45);
  set("chat-brain-reflection-injection-margin", cfg.reflection_injection_margin ?? 0.08);
  setChecked("chat-brain-graph-flash", cfg.brain_graph_flash_enabled !== false);
  // === Brain dedicated LLM (fields show/hide tracks the toggle; the
  //     change-side wiring lives in core/delegation.js brain-llm-toggle) ===
  setChecked("chat-brain-llm-dedicated", cfg.brain_llm_dedicated === true);
  set("chat-brain-llm-provider", cfg.brain_llm_provider || "");
  set("chat-brain-llm-model", cfg.brain_llm_model || "");
  set("chat-brain-llm-base-url", cfg.brain_llm_base_url || "");
  set("chat-brain-llm-api-key", cfg.brain_llm_api_key || "");
  var brainLlmFields = document.getElementById("chat-brain-llm-fields");
  if (brainLlmFields) {
    brainLlmFields.classList.toggle("settings-body-hidden", cfg.brain_llm_dedicated !== true);
  }
  // Graph flash SSE follows the brain setting (graph.js may be absent on some pages)
  if (N.Features && N.Features.Graph && N.Features.Graph.setFlashEnabled) {
    N.Features.Graph.setFlashEnabled(cfg.brain_graph_flash_enabled !== false);
  }
  // === Forgetting (moved from Settings) ===
  setChecked("chat-forgetting-enabled", cfg.forgetting_enabled === true);
  set("chat-forgetting-trigger-threshold", cfg.forgetting_trigger_threshold ?? _defaultOf("forgetting_trigger_threshold") ?? 100);
  set("chat-forgetting-decay-interval-seconds", cfg.forgetting_decay_interval_seconds ?? _defaultOf("forgetting_decay_interval_seconds") ?? 3600);
  set("chat-forgetting-min-strength", cfg.forgetting_min_strength ?? 0.1);
  set("chat-forgetting-forget-ratio", cfg.forgetting_forget_ratio ?? 0.2);
  set("chat-forgetting-forget-strength", cfg.forgetting_forget_strength ?? 0.5);
  // Sync min-strength display
  var fs = document.getElementById("chat-forgetting-min-strength");
  if (fs) document.getElementById("chat-forgetting-min-strength-val").textContent = parseFloat(fs.value).toFixed(2);
  // Emotion decay
  // unset → 空欄 (カテゴリテーブルのデフォルトを使用)
  set("chat-emotion-decay-half-life-hours", cfg.emotion_decay_half_life_hours ?? "");
  set("chat-emotion-decay-threshold", cfg.emotion_decay_threshold ?? 0.005);
  set("chat-emotion-neutral-threshold", cfg.emotion_neutral_threshold ?? 0.01);
  // ComfyUI URLが設定済みなら疎通確認を自動実行
  if (cfg.image_gen_comfyui_url) {
    N.Chat.settings.checkComfyUI();
  }
  _refreshResetButtons();
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
    mental_model_enabled: getChecked("chat-mental-model-enabled"),
    mental_model_min_samples: parseInt(
      document.getElementById("chat-mental-model-min-samples")?.value || "3",
    ),
    debug_mode: getChecked("chat-debug-mode"),

    // === Memory enrichment (enabled toggle lives in the brain section) ===
    memory_enrichment_enabled: getChecked("chat-memory-enrichment-enabled"),
    // === Brain simulation ===
    brain_enrich_auto_run: getChecked("chat-brain-auto-run"),
    brain_enrich_interval_seconds: parseInt(document.getElementById("chat-brain-enrich-interval")?.value || "60"),
    brain_enrich_batch_limit: parseInt(document.getElementById("chat-brain-batch-limit")?.value || "5"),
    // REM scheduling knobs: 空なら送らない (merge API keeps the stored value)
    brain_idle_after_seconds: (() => {
      var v = (document.getElementById("chat-brain-idle-after-seconds")?.value || "").trim();
      return v ? parseInt(v) : undefined;
    })(),
    brain_min_batch_size: (() => {
      var v = (document.getElementById("chat-brain-min-batch-size")?.value || "").trim();
      return v ? parseInt(v) : undefined;
    })(),
    brain_max_defer_seconds: (() => {
      var v = (document.getElementById("chat-brain-max-defer-seconds")?.value || "").trim();
      return v ? parseInt(v) : undefined;
    })(),
    brain_monologue_enabled: getChecked("chat-brain-monologue"),
    brain_reasoning_enabled: getChecked("chat-brain-reasoning"),
    brain_reasoning_effort: getChecked("chat-brain-reasoning") ? (document.getElementById("chat-brain-reasoning-effort")?.value || "medium") : undefined,
    brain_spontaneous_enabled: getChecked("chat-brain-spontaneous"),
    brain_spontaneous_interval_hours: getChecked("chat-brain-spontaneous")
      ? parseInt(document.getElementById("chat-brain-spontaneous-interval")?.value || "6")
      : undefined,
    brain_novelty_sim_threshold: parseFloat(document.getElementById("chat-brain-novelty-sim")?.value || "0.75"),
    brain_novelty_importance_threshold: parseFloat(document.getElementById("chat-brain-novelty-importance")?.value || "0.6"),
    brain_novelty_stability_multiplier: parseFloat(document.getElementById("chat-brain-novelty-multiplier")?.value || "2.0"),
    brain_emotion_gain_k: parseFloat(document.getElementById("chat-brain-emotion-gain-k")?.value || "0.5"),
    brain_rif_suppression_rho: parseFloat(document.getElementById("chat-brain-rif-rho")?.value || "0.05"),
    // リフレクション降格・注入ゲート: 空なら送らない (merge API keeps the stored value)
    reflection_retrieval_penalty: (() => {
      var v = (document.getElementById("chat-brain-reflection-retrieval-penalty")?.value || "").trim();
      return v ? parseFloat(v) : undefined;
    })(),
    reflection_injection_min_similarity: (() => {
      var v = (document.getElementById("chat-brain-reflection-injection-min-similarity")?.value || "").trim();
      return v ? parseFloat(v) : undefined;
    })(),
    reflection_injection_margin: (() => {
      var v = (document.getElementById("chat-brain-reflection-injection-margin")?.value || "").trim();
      return v ? parseFloat(v) : undefined;
    })(),
    // brain_link_separation_threshold is dormant (similarity source not wired) — not collected
    brain_graph_flash_enabled: getChecked("chat-brain-graph-flash"),
    // === Brain dedicated LLM: toggle is always sent; dedicated fields
    //     only when ON (OFF = reuse chat LLM, keep stored values) ===
    brain_llm_dedicated: getChecked("chat-brain-llm-dedicated"),
    // === Forgetting (moved from Settings) ===
    forgetting_enabled: getChecked("chat-forgetting-enabled"),
    // brain_max_tokens: 空なら送らない (merge API keeps the stored value)
    brain_max_tokens: (() => {
      var v = (document.getElementById("chat-brain-max-tokens")?.value || "").trim();
      return v ? parseInt(v) : undefined;
    })(),
    forgetting_trigger_threshold: parseInt(document.getElementById("chat-forgetting-trigger-threshold")?.value || "100"),
    forgetting_decay_interval_seconds: parseInt(document.getElementById("chat-forgetting-decay-interval-seconds")?.value || "86400"),
    forgetting_min_strength: parseFloat(document.getElementById("chat-forgetting-min-strength")?.value || "0.1"),
    forgetting_forget_ratio: parseFloat(document.getElementById("chat-forgetting-forget-ratio")?.value || "0.2"),
    forgetting_forget_strength: parseFloat(document.getElementById("chat-forgetting-forget-strength")?.value || "0.5"),
    // Emotion decay
    // 空欄なら null を送り保存値を解除 (カテゴリテーブル有効化)
    emotion_decay_half_life_hours: (function () {
      var v = (document.getElementById("chat-emotion-decay-half-life-hours")?.value || "").trim();
      return v === "" ? null : parseFloat(v);
    })(),
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
  if (getChecked("chat-brain-llm-dedicated")) {
    payload.brain_llm_provider = document.getElementById("chat-brain-llm-provider")?.value.trim() || "";
    payload.brain_llm_model = document.getElementById("chat-brain-llm-model")?.value.trim() || "";
    payload.brain_llm_base_url = document.getElementById("chat-brain-llm-base-url")?.value.trim() || "";
    payload.brain_llm_api_key = document.getElementById("chat-brain-llm-api-key")?.value || "";
  }
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
  loadDefaults: loadConfigDefaults,
  injectResetButtons: _injectResetButtons,
  resetField: _resetField,
  resetFields: RESET_FIELDS,
  isFieldDirty: _isFieldDirty,
};

})(window.Nous);
