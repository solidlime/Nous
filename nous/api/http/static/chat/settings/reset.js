/* =================================================================
   CHAT SETTINGS RESET — defaults API + per-field reset-to-default
   Chunk 1/4 of chat-settings.js (split: reset.js / apply.js /
   apply-groups.js / save.js). Namespace: N.Chat.settings.*
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
    ["chat-top-p", "top_p", "optional", "chat-top-p-enabled"],
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
    ["chat-character-judge-enabled", "character_judge_enabled"],
    ["chat-character-repair-max-attempts", "character_repair_max_attempts"],
    ["chat-tool-result-max", "tool_result_max_chars"],
    ["chat-recency-weight", "retrieval_recency_weight"],
    ["chat-importance-weight", "retrieval_importance_weight"],
    ["chat-relevance-weight", "retrieval_relevance_weight"],
    ["chat-debug-mode", "debug_mode"],
    ["chat-dynamic-tool-selection", "dynamic_tool_selection"],
    ["chat-mcp-json", "mcp_servers", "json"],
    ["chat-voice-enabled", "voice_enabled"],
    ["chat-voice-url", "voice_url"],
    ["chat-voice-model", "voice_model"],
    ["chat-voice-auto-play", "voice_auto_play"],
    ["chat-voice-streaming", "voice_streaming"],
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
    [
      "chat-image-gen-preset-portrait_large",
      "image_gen_presets",
      "preset",
      "portrait_large",
    ],
    [
      "chat-image-gen-preset-portrait_medium",
      "image_gen_presets",
      "preset",
      "portrait_medium",
    ],
    [
      "chat-image-gen-preset-portrait_small",
      "image_gen_presets",
      "preset",
      "portrait_small",
    ],
    [
      "chat-image-gen-preset-landscape_large",
      "image_gen_presets",
      "preset",
      "landscape_large",
    ],
    [
      "chat-image-gen-preset-landscape_medium",
      "image_gen_presets",
      "preset",
      "landscape_medium",
    ],
    [
      "chat-image-gen-preset-landscape_small",
      "image_gen_presets",
      "preset",
      "landscape_small",
    ],
    [
      "chat-image-gen-preset-square_large",
      "image_gen_presets",
      "preset",
      "square_large",
    ],
    [
      "chat-image-gen-preset-square_medium",
      "image_gen_presets",
      "preset",
      "square_medium",
    ],
    [
      "chat-image-gen-preset-square_small",
      "image_gen_presets",
      "preset",
      "square_small",
    ],
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
    [
      "chat-brain-reflection-injection-min-similarity",
      "reflection_injection_min_similarity",
    ],
    ["chat-brain-reflection-injection-margin", "reflection_injection_margin"],
    ["chat-brain-graph-flash", "brain_graph_flash_enabled"],
    ["chat-brain-llm-dedicated", "brain_llm_dedicated"],
    ["chat-brain-llm-provider", "brain_llm_provider"],
    ["chat-brain-llm-model", "brain_llm_model"],
    ["chat-brain-llm-base-url", "brain_llm_base_url"],
    ["chat-brain-llm-api-key", "brain_llm_api_key"],
    ["chat-forgetting-enabled", "forgetting_enabled"],
    ["chat-forgetting-trigger-threshold", "forgetting_trigger_threshold"],
    [
      "chat-forgetting-decay-interval-seconds",
      "forgetting_decay_interval_seconds",
    ],
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

  function _fieldElement(entry) {
    var el = document.getElementById(entry[0]);
    if (!el && entry[2] === "radio") {
      el = document.querySelector('input[name="' + entry[0] + '"]');
    }
    return el;
  }

  // Divergence check. Numeric fields compare by parsed value with a tolerance so
  // float representation noise (0.7000000000000001 vs 0.7) never shows the icon.
  // A null default means "unset": empty text/number = not divergent, and an unset
  // range (whose "" is coerced to the midpoint by the browser) is also not divergent.
  function _isFieldDirty(entry) {
    var el = _fieldElement(entry);
    if (!el) return false;
    var def = _defaultOf(entry[1]);
    if (def === undefined) return false;
    var kind = entry[2];

    if (kind === "percent") {
      if (def == null) return false;
      var pct = parseFloat(el.value);
      return isNaN(pct) || Math.abs(pct - Math.round(def * 100)) >= 0.5;
    }
    if (kind === "effort") {
      var wantIdx = ["low", "medium", "high", "max"].indexOf(String(def));
      if (wantIdx < 0) wantIdx = 1;
      return parseFloat(el.value) !== wantIdx;
    }
    if (kind === "preset") {
      var want = def && def[entry[3]] != null ? String(def[entry[3]]) : "";
      return String(el.value) !== want;
    }
    if (kind === "json") {
      try {
        return JSON.stringify(JSON.parse(el.value)) !== JSON.stringify(def);
      } catch (_) {
        return true; // unparsable editor ≠ default → offer the reset
      }
    }
    if (kind === "radio") {
      var on = document.querySelector(
        'input[name="' + el.getAttribute("name") + '"]:checked',
      );
      return !on || on.value !== (def == null ? "off" : String(def));
    }
    if (kind === "optional") {
      // Null default = unset. entry[3] is the enable checkbox; unset ⇒ unchecked.
      var optCb = document.getElementById(entry[3]);
      var optOn = optCb ? optCb.checked : true;
      var isSet = def != null;
      if (optOn !== isSet) return true;
      if (!optOn) return false;
      var oc = parseFloat(el.value);
      var orf = parseFloat(def);
      if (!isNaN(oc) && !isNaN(orf)) return Math.abs(oc - orf) > 1e-9;
      return String(el.value) !== String(def);
    }
    if (el.type === "checkbox") return el.checked !== !!def;
    if (def == null) {
      if (el.type === "range") return false;
      return String(el.value) !== "";
    }
    var cur = parseFloat(el.value);
    var ref = parseFloat(def);
    if (!isNaN(cur) && !isNaN(ref)) return Math.abs(cur - ref) > 1e-9;
    return String(el.value) !== String(def);
  }

  function _injectResetButtons() {
    for (var i = 0; i < RESET_FIELDS.length; i++) {
      var entry = RESET_FIELDS[i];
      var el = _fieldElement(entry);
      if (!el) continue;
      if (_resetButtons[entry[0]] && _resetButtons[entry[0]].isConnected)
        continue;
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
        var toggle = el.closest(".toggle-switch");
        if (toggle) {
          // Keep the switch right-aligned: group the icon just left of it.
          var grp = document.createElement("span");
          grp.className = "chat-reset-toggle-group";
          toggle.parentNode.insertBefore(grp, toggle);
          grp.appendChild(btn);
          grp.appendChild(toggle);
        } else {
          var row = el.closest(".chat-check-row") || el.parentElement;
          if (!row) continue;
          row.appendChild(btn);
          btn.classList.add("chat-reset-inline");
        }
      } else if (entry[2] === "radio") {
        var holder = el.closest("div") || el.parentElement;
        if (!holder) continue;
        holder.classList.add("chat-reset-holder");
        holder.appendChild(btn);
        btn.classList.add("chat-reset-corner");
      } else {
        var wrap = document.createElement("span");
        wrap.className = "chat-reset-wrap";
        if (el.tagName === "SELECT") {
          wrap.classList.add("chat-reset-wrap-select");
        } else if (el.tagName === "TEXTAREA") {
          wrap.classList.add("chat-reset-wrap-textarea");
        } else if (el.type === "range") {
          wrap.classList.add("chat-reset-wrap-outside");
        }
        // The input may carry inline flex/width sizing; keep it on the wrapper so
        // moving the input inside does not change the existing layout.
        if (el.style && el.tagName !== "TEXTAREA" && el.type !== "range") {
          if (el.style.flex) wrap.style.flex = el.style.flex;
          if (el.style.width) wrap.style.width = el.style.width;
        }
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
    } else if (entry[2] === "optional") {
      var optCb = document.getElementById(entry[3]);
      if (def == null) {
        if (optCb) optCb.checked = false;
        el.disabled = true;
        el.value = "1";
      } else {
        if (optCb) optCb.checked = true;
        el.disabled = false;
        el.value = String(def);
      }
    } else if (entry[2] === "json") {
      el.value = JSON.stringify(def, null, 2);
    } else {
      el.value = _defaultToDisplay(def, entry[2], entry[3]);
    }
    // Reuse the existing delegation for mirror/dependent-token sync. Never saves.
    el.dispatchEvent(new Event("input", { bubbles: true }));
    el.dispatchEvent(new Event("change", { bubbles: true }));
    if (N.Chat.settings.updateSliderLabels)
      N.Chat.settings.updateSliderLabels();
    _refreshResetButtons();
  }

  function _bindResetListeners() {
    if (_bindResetListeners._bound) return;
    _bindResetListeners._bound = true;
    document.addEventListener("click", (e) => {
      var btn =
        e.target && e.target.closest
          ? e.target.closest(".chat-reset-btn")
          : null;
      if (!btn) return;
      e.preventDefault();
      e.stopPropagation();
      _resetField(btn.getAttribute("data-reset-for"));
    });
    var onEdit = () => {
      _refreshResetButtons();
    };
    document.addEventListener("input", onEdit);
    document.addEventListener("change", onEdit);
  }

  // ------------------------------------------------------------------
  // Register namespace (chunk 1/4 — defaults/reset API)
  // ------------------------------------------------------------------
  N.Chat.settings = N.Chat.settings || {};
  N.Chat.settings.loadDefaults = loadConfigDefaults;
  N.Chat.settings.injectResetButtons = _injectResetButtons;
  N.Chat.settings.resetField = _resetField;
  N.Chat.settings.resetFields = RESET_FIELDS;
  N.Chat.settings.isFieldDirty = _isFieldDirty;
  // Internal cross-chunk hooks (used by settings/apply.js +
  // settings/apply-groups.js; namespaced _-prefixed = private).
  N.Chat.settings._defaultOf = _defaultOf;
  N.Chat.settings._refreshResetButtons = _refreshResetButtons;
})(window.Nous);
