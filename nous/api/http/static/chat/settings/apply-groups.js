/* =================================================================
   CHAT SETTINGS APPLY-GROUPS — applyChatConfig field-group helpers
   Chunk 3/4 of chat-settings.js (voice/TTS, image gen,
   brain/forgetting/emotion decay). Called by settings/apply.js's
   applyChatConfig. Namespace: N.Chat.settings._apply* (private).
   Depends on: settings/reset.js (N.Chat.settings._defaultOf)
   ================================================================= */
;(function(N) {
var C = N.Core;
var api = C.api, esc = C.esc, toast = C.toast, safeSetHTML = C.safeSetHTML;
var showConfirm = C.showConfirm, showAlert = C.showAlert;
"use strict";
var S = window.S;

// ------------------------------------------------------------------
// Voice / TTS + irodori + debug-mode field application
// ------------------------------------------------------------------
function applyVoiceSection(cfg, set, setChecked) {
    // Voice / TTS settings (TE04)
    var voiceToggle = document.getElementById("chat-voice-enabled");
    if (voiceToggle) {
      voiceToggle.checked = cfg.voice_enabled || false;
      var voiceOptions = document.getElementById("chat-voice-options");
      if (voiceOptions) {
        voiceOptions.classList.toggle(
          "settings-body-hidden",
          !voiceToggle.checked,
        );
        voiceToggle.onchange = function () {
          voiceOptions.classList.toggle("settings-body-hidden", !this.checked);
        };
      }
    }
    var voiceUrlInput = document.getElementById("chat-voice-url");
    if (voiceUrlInput) voiceUrlInput.value = cfg.voice_url || "";
    // Emotion reflection mode: "off" | "anchor" | "llm" (legacy bools fallback)
    var emotionMode = cfg.voice_emotion_mode;
    if (
      emotionMode !== "off" &&
      emotionMode !== "anchor" &&
      emotionMode !== "llm"
    ) {
      emotionMode =
        cfg.irodori_caption_llm_enabled && cfg.voice_emotion_link !== false
          ? "llm"
          : cfg.voice_emotion_link === false
            ? "off"
            : "anchor";
    }
    var modeRadio = document.querySelector(
      'input[name="chat-voice-emotion-mode"][value="' + emotionMode + '"]',
    );
    if (modeRadio) modeRadio.checked = true;
    var llmModelWrap = document.getElementById(
      "chat-irodori-caption-llm-model-wrap",
    );
    if (llmModelWrap)
      llmModelWrap.style.display = emotionMode === "llm" ? "block" : "none";
    setChecked("chat-voice-auto-play", cfg.voice_auto_play === true);
    setChecked("chat-voice-streaming", cfg.voice_streaming !== false);
    // Load voice model name (text input now)
    var voiceModelInput = document.getElementById("chat-voice-model");
    if (voiceModelInput) voiceModelInput.value = cfg.voice_model || "";
    // Irodori advanced params
    var irodoriNumSteps = document.getElementById("chat-irodori-num-steps");
    if (irodoriNumSteps) irodoriNumSteps.value = cfg.irodori_num_steps ?? 30;
    if (irodoriNumSteps)
      document.getElementById("chat-irodori-num-steps-val").textContent =
        cfg.irodori_num_steps ?? 30;
    var irodoriCfgText = document.getElementById("chat-irodori-cfg-scale-text");
    if (irodoriCfgText)
      irodoriCfgText.value = cfg.irodori_cfg_scale_text ?? 3.2;
    if (irodoriCfgText)
      document.getElementById("chat-irodori-cfg-text-val").textContent = (
        cfg.irodori_cfg_scale_text ?? 3.2
      ).toFixed(1);
    var irodoriCfgSpeaker = document.getElementById(
      "chat-irodori-cfg-scale-speaker",
    );
    if (irodoriCfgSpeaker)
      irodoriCfgSpeaker.value = cfg.irodori_cfg_scale_speaker ?? 5.0;
    if (irodoriCfgSpeaker)
      document.getElementById("chat-irodori-cfg-speaker-val").textContent = (
        cfg.irodori_cfg_scale_speaker ?? 5.0
      ).toFixed(1);
    var irodoriCfgCaption = document.getElementById(
      "chat-irodori-cfg-scale-caption",
    );
    if (irodoriCfgCaption)
      irodoriCfgCaption.value = cfg.irodori_cfg_scale_caption ?? 4.2;
    if (irodoriCfgCaption)
      document.getElementById("chat-irodori-cfg-caption-val").textContent = (
        cfg.irodori_cfg_scale_caption ?? 4.2
      ).toFixed(1);
    var irodoriChunkMin = document.getElementById(
      "chat-irodori-chunk-min-chars",
    );
    if (irodoriChunkMin) {
      // 既定値の単一の正は session_config.ChatConfig.irodori_chunk_min_chars
      // （defaults API の fields.irodori_chunk_min_chars.default）。API 応答が
      // 無い場合のみ従来値 85 にフォールバックする。
      var chunkMinDefault =
        N.Chat.settings._defaultOf("irodori_chunk_min_chars") ?? 85;
      var chunkMin = cfg.irodori_chunk_min_chars ?? chunkMinDefault;
      irodoriChunkMin.value = chunkMin;
      var chunkMinVal = document.getElementById("chat-irodori-chunk-min-val");
      if (chunkMinVal) chunkMinVal.textContent = chunkMin;
    }
    var irodoriSeed = document.getElementById("chat-irodori-seed");
    if (irodoriSeed) irodoriSeed.value = cfg.irodori_seed ?? 0;
    var irodoriCaptionLLMModel = document.getElementById(
      "chat-irodori-caption-llm-model",
    );
    if (irodoriCaptionLLMModel)
      irodoriCaptionLLMModel.value = cfg.irodori_caption_llm_model || "";
    // Voice volume
    var voiceVolume = document.getElementById("chat-voice-volume");
    if (voiceVolume) voiceVolume.value = cfg.voice_volume ?? 1.0;
    if (voiceVolume)
      document.getElementById("chat-voice-volume-val").textContent =
        Math.round((cfg.voice_volume ?? 1.0) * 100) + "%";
    // Voice speed
    var voiceSpeed = document.getElementById("chat-voice-speed");
    if (voiceSpeed) voiceSpeed.value = cfg.voice_speed ?? 1.0;
    if (voiceSpeed)
      document.getElementById("chat-voice-speed-val").textContent =
        (cfg.voice_speed ?? 1.0).toFixed(2) + "x";
    // Check connection status
    N.Chat.tts.checkConnection();
    // Debug mode
    setChecked("chat-debug-mode", cfg.debug_mode === true);
    const statusEl = document.getElementById("chat-config-status");
    if (statusEl) {
      if (cfg.is_configured) {
        safeSetHTML(
          statusEl,
          '<span class="chat-config-ok"><i data-lucide="check"></i> APIキー設定済み</span>',
        );
      } else {
        safeSetHTML(
          statusEl,
          '<span class="chat-config-warn"><i data-lucide="alert-triangle"></i> APIキー未設定</span>',
        );
      }
    }

}

// ------------------------------------------------------------------
// Image gen + caption + preset field application
// ------------------------------------------------------------------
function applyImageSection(cfg, set, setChecked) {
    // Image gen enabled toggle
    var imgGenToggle = document.getElementById("chat-image-gen-enabled");
    if (imgGenToggle) {
      imgGenToggle.checked = cfg.image_gen_enabled || false;
      var imgGenOptions = document.getElementById("chat-image-options");
      if (imgGenOptions) {
        imgGenOptions.classList.toggle(
          "settings-body-hidden",
          !imgGenToggle.checked,
        );
        imgGenToggle.onchange = function () {
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
    set(
      "chat-image-gen-self-portrait-prompt",
      cfg.image_gen_self_portrait_prompt,
    );
    set("chat-image-gen-negative-prompt", cfg.image_gen_negative_prompt || "");
    var templateInput = document.getElementById("chat-image-gen-template");
    if (templateInput)
      templateInput.value = cfg.image_gen_comfyui_workflow_template || "";
    set(
      "chat-image-gen-workflow-source",
      cfg.image_gen_comfyui_workflow_source,
    );
    var workflowNameInput = document.getElementById(
      "chat-image-gen-workflow-name",
    );
    if (workflowNameInput)
      workflowNameInput.value = cfg.image_gen_comfyui_workflow_name || "";
    // 構図プリフィックス
    set(
      "chat-image-gen-full-body-prefix",
      cfg.image_gen_full_body_prefix || "",
    );
    set("chat-image-gen-portrait-prefix", cfg.image_gen_portrait_prefix || "");
    set("chat-image-gen-selfie-prefix", cfg.image_gen_selfie_prefix || "");
    set("chat-image-gen-scene-prefix", cfg.image_gen_scene_prefix || "");
    // Image caption (non-vision providers)
    setChecked(
      "chat-image-caption-enabled",
      cfg.image_caption_enabled !== false,
    );
    set(
      "chat-image-caption-provider",
      cfg.image_caption_provider || "openai_compat",
    );
    set("chat-image-caption-model", cfg.image_caption_model || "");
    set("chat-image-caption-api-key", cfg.image_caption_api_key || "");
    set("chat-image-caption-base-url", cfg.image_caption_base_url || "");
    // プリセット解像度 復元
    var _presetNames = [
      "portrait_large",
      "portrait_medium",
      "portrait_small",
      "landscape_large",
      "landscape_medium",
      "landscape_small",
      "square_large",
      "square_medium",
      "square_small",
    ];
    var _presets = cfg.image_gen_presets || {};
    _presetNames.forEach((name) => {
      var el = document.getElementById("chat-image-gen-preset-" + name);
      if (el && _presets[name]) el.value = _presets[name];
    });
    var _defPreset = document.getElementById("chat-image-gen-default-preset");
    if (_defPreset && cfg.image_gen_default_preset)
      _defPreset.value = cfg.image_gen_default_preset;
    // スライダー値表示更新
}

// ------------------------------------------------------------------
// Brain simulation + forgetting + emotion decay field application
// ------------------------------------------------------------------
function applyBrainForgettingSection(cfg, set, setChecked) {
    // === Memory enrichment (enabled toggle lives in the brain section) ===
    setChecked(
      "chat-memory-enrichment-enabled",
      cfg.memory_enrichment_enabled === true,
    );
    // === Brain simulation ===
    setChecked("chat-brain-auto-run", cfg.brain_enrich_auto_run === true);
    set(
      "chat-brain-enrich-interval",
      cfg.brain_enrich_interval_seconds ??
        N.Chat.settings._defaultOf("brain_enrich_interval_seconds") ??
        60,
    );
    set("chat-brain-batch-limit", cfg.brain_enrich_batch_limit ?? 5);
    set("chat-brain-idle-after-seconds", cfg.brain_idle_after_seconds ?? 120);
    set("chat-brain-min-batch-size", cfg.brain_min_batch_size ?? 3);
    set(
      "chat-brain-max-defer-seconds",
      cfg.brain_max_defer_seconds ??
        N.Chat.settings._defaultOf("brain_max_defer_seconds") ??
        3600,
    );
    setChecked("chat-brain-monologue", cfg.brain_monologue_enabled === true);
    setChecked("chat-brain-reasoning", cfg.brain_reasoning_enabled === true);
    set("chat-brain-reasoning-effort", cfg.brain_reasoning_effort || "medium");
    setChecked(
      "chat-brain-spontaneous",
      cfg.brain_spontaneous_enabled === true,
    );
    set(
      "chat-brain-spontaneous-interval",
      cfg.brain_spontaneous_interval_hours ??
        N.Chat.settings._defaultOf("brain_spontaneous_interval_hours") ??
        1,
    );
    set("chat-brain-max-tokens", cfg.brain_max_tokens ?? 0);
    set("chat-brain-novelty-sim", cfg.brain_novelty_sim_threshold ?? 0.75);
    set(
      "chat-brain-novelty-importance",
      cfg.brain_novelty_importance_threshold ?? 0.6,
    );
    set(
      "chat-brain-novelty-multiplier",
      cfg.brain_novelty_stability_multiplier ?? 2.0,
    );
    set("chat-brain-emotion-gain-k", cfg.brain_emotion_gain_k ?? 0.5);
    set("chat-brain-rif-rho", cfg.brain_rif_suppression_rho ?? 0.05);
    set(
      "chat-brain-separation-threshold",
      cfg.brain_link_separation_threshold ?? 0.75,
    );
    set(
      "chat-brain-reflection-retrieval-penalty",
      cfg.reflection_retrieval_penalty ?? 0.5,
    );
    set(
      "chat-brain-reflection-injection-min-similarity",
      cfg.reflection_injection_min_similarity ?? 0.45,
    );
    set(
      "chat-brain-reflection-injection-margin",
      cfg.reflection_injection_margin ?? 0.08,
    );
    setChecked(
      "chat-brain-graph-flash",
      cfg.brain_graph_flash_enabled !== false,
    );
    // === Brain dedicated LLM (fields show/hide tracks the toggle; the
    //     change-side wiring lives in core/delegation.js brain-llm-toggle) ===
    setChecked("chat-brain-llm-dedicated", cfg.brain_llm_dedicated === true);
    set("chat-brain-llm-provider", cfg.brain_llm_provider || "");
    set("chat-brain-llm-model", cfg.brain_llm_model || "");
    set("chat-brain-llm-base-url", cfg.brain_llm_base_url || "");
    set("chat-brain-llm-api-key", cfg.brain_llm_api_key || "");
    var brainLlmFields = document.getElementById("chat-brain-llm-fields");
    if (brainLlmFields) {
      brainLlmFields.classList.toggle(
        "settings-body-hidden",
        cfg.brain_llm_dedicated !== true,
      );
    }
    // Graph flash SSE follows the brain setting (graph.js may be absent on some pages)
    if (N.Features && N.Features.Graph && N.Features.Graph.setFlashEnabled) {
      N.Features.Graph.setFlashEnabled(cfg.brain_graph_flash_enabled !== false);
    }
    // === Forgetting (moved from Settings) ===
    setChecked("chat-forgetting-enabled", cfg.forgetting_enabled === true);
    set(
      "chat-forgetting-decay-interval-seconds",
      cfg.forgetting_decay_interval_seconds ??
        N.Chat.settings._defaultOf("forgetting_decay_interval_seconds") ??
        3600,
    );
    set("chat-forgetting-min-strength", cfg.forgetting_min_strength ?? 0.1);
    // Sync min-strength display
    var fs = document.getElementById("chat-forgetting-min-strength");
    if (fs)
      document.getElementById("chat-forgetting-min-strength-val").textContent =
        parseFloat(fs.value).toFixed(2);
    // Emotion decay
    // unset → 空欄 (カテゴリテーブルのデフォルトを使用)
    set(
      "chat-emotion-decay-half-life-hours",
      cfg.emotion_decay_half_life_hours ?? "",
    );
    set("chat-emotion-decay-threshold", cfg.emotion_decay_threshold ?? 0.005);
    set(
      "chat-emotion-neutral-threshold",
      cfg.emotion_neutral_threshold ?? 0.01,
    );
}

// ------------------------------------------------------------------
// Register internal cross-chunk hooks (chunk 3/4)
// ------------------------------------------------------------------
N.Chat.settings = N.Chat.settings || {};
N.Chat.settings._applyVoice = applyVoiceSection;
N.Chat.settings._applyImage = applyImageSection;
N.Chat.settings._applyBrainForgetting = applyBrainForgettingSection;
})(window.Nous);
