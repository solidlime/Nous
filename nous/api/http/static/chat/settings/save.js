/* =================================================================
   CHAT SETTINGS SAVE — saveChatConfig field collection + POST
   Chunk 4/4 of chat-settings.js. Namespace: N.Chat.settings.save
   Depends on: settings/reset.js + settings/apply.js (N.Chat.settings.apply),
   settings-mcp.js (parseMcpJson / BUILTIN_SKILLS).
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

  async function saveChatConfig() {
    if (!S.persona) {
      toast("ペルソナを選択してください", "error");
      return;
    }
    const baseUrlVal = (
      document.getElementById("chat-base-url")?.value || ""
    ).trim();
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

      temperature: parseFloat(
        document.getElementById("chat-temperature").value,
      ),
      dynamic_temperature: getChecked("chat-dynamic-temperature"),
      emotion_temperature_scale: parseFloat(
        document.getElementById("chat-emotion-temperature-scale")?.value ||
          "0.2",
      ),
      top_p: (() => {
        var enabled = document.getElementById("chat-top-p-enabled");
        if (enabled && !enabled.checked) return null;
        var v = parseFloat(document.getElementById("chat-top-p")?.value);
        return isNaN(v) ? null : v;
      })(),
      reasoning_enabled: getChecked("chat-reasoning-enabled"),
      reasoning_effort: (() => {
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
      context_max_tokens: (() => {
        var v = parseInt(
          document.getElementById("chat-context-max-tokens").value,
        );
        return v > 0 ? v : null;
      })(),
      context_compression_threshold:
        parseFloat(
          document.getElementById("chat-compression-threshold").value,
        ) / 100,
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
        (N.Chat.state.enabledSkills || []).filter(
          (s) => !(N.Chat.settings.BUILTIN_SKILLS || ["search"]).includes(s),
        ),
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
      character_judge_enabled: getChecked("chat-character-judge-enabled"),
      character_repair_max_attempts: parseInt(
        document.getElementById("chat-character-repair-max-attempts")?.value || "2",
      ),
      debug_mode: getChecked("chat-debug-mode"),

      // === Memory enrichment (enabled toggle lives in the brain section) ===
      memory_enrichment_enabled: getChecked("chat-memory-enrichment-enabled"),
      // === Brain simulation ===
      brain_enrich_auto_run: getChecked("chat-brain-auto-run"),
      brain_enrich_interval_seconds: parseInt(
        document.getElementById("chat-brain-enrich-interval")?.value || "60",
      ),
      brain_enrich_batch_limit: parseInt(
        document.getElementById("chat-brain-batch-limit")?.value || "5",
      ),
      // REM scheduling knobs: 空なら送らない (merge API keeps the stored value)
      brain_idle_after_seconds: (() => {
        var v = (
          document.getElementById("chat-brain-idle-after-seconds")?.value || ""
        ).trim();
        return v ? parseInt(v) : undefined;
      })(),
      brain_min_batch_size: (() => {
        var v = (
          document.getElementById("chat-brain-min-batch-size")?.value || ""
        ).trim();
        return v ? parseInt(v) : undefined;
      })(),
      brain_max_defer_seconds: (() => {
        var v = (
          document.getElementById("chat-brain-max-defer-seconds")?.value || ""
        ).trim();
        return v ? parseInt(v) : undefined;
      })(),
      brain_monologue_enabled: getChecked("chat-brain-monologue"),
      brain_reasoning_enabled: getChecked("chat-brain-reasoning"),
      brain_reasoning_effort: getChecked("chat-brain-reasoning")
        ? document.getElementById("chat-brain-reasoning-effort")?.value ||
          "medium"
        : undefined,
      brain_spontaneous_enabled: getChecked("chat-brain-spontaneous"),
      brain_spontaneous_interval_hours: getChecked("chat-brain-spontaneous")
        ? parseInt(
            document.getElementById("chat-brain-spontaneous-interval")?.value ||
              "6",
          )
        : undefined,
      brain_novelty_sim_threshold: parseFloat(
        document.getElementById("chat-brain-novelty-sim")?.value || "0.75",
      ),
      brain_novelty_importance_threshold: parseFloat(
        document.getElementById("chat-brain-novelty-importance")?.value ||
          "0.6",
      ),
      brain_novelty_stability_multiplier: parseFloat(
        document.getElementById("chat-brain-novelty-multiplier")?.value ||
          "2.0",
      ),
      brain_emotion_gain_k: parseFloat(
        document.getElementById("chat-brain-emotion-gain-k")?.value || "0.5",
      ),
      brain_rif_suppression_rho: parseFloat(
        document.getElementById("chat-brain-rif-rho")?.value || "0.05",
      ),
      // リフレクション降格・注入ゲート: 空なら送らない (merge API keeps the stored value)
      reflection_retrieval_penalty: (() => {
        var v = (
          document.getElementById("chat-brain-reflection-retrieval-penalty")
            ?.value || ""
        ).trim();
        return v ? parseFloat(v) : undefined;
      })(),
      reflection_injection_min_similarity: (() => {
        var v = (
          document.getElementById(
            "chat-brain-reflection-injection-min-similarity",
          )?.value || ""
        ).trim();
        return v ? parseFloat(v) : undefined;
      })(),
      reflection_injection_margin: (() => {
        var v = (
          document.getElementById("chat-brain-reflection-injection-margin")
            ?.value || ""
        ).trim();
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
        var v = (
          document.getElementById("chat-brain-max-tokens")?.value || ""
        ).trim();
        return v ? parseInt(v) : undefined;
      })(),
      forgetting_trigger_threshold: parseInt(
        document.getElementById("chat-forgetting-trigger-threshold")?.value ||
          "100",
      ),
      forgetting_decay_interval_seconds: parseInt(
        document.getElementById("chat-forgetting-decay-interval-seconds")
          ?.value || "3600",
      ),
      forgetting_min_strength: parseFloat(
        document.getElementById("chat-forgetting-min-strength")?.value || "0.1",
      ),
      forgetting_forget_ratio: parseFloat(
        document.getElementById("chat-forgetting-forget-ratio")?.value || "0.2",
      ),
      forgetting_forget_strength: parseFloat(
        document.getElementById("chat-forgetting-forget-strength")?.value ||
          "0.5",
      ),
      // Emotion decay
      // 空欄なら null を送り保存値を解除 (カテゴリテーブル有効化)
      emotion_decay_half_life_hours: (() => {
        var v = (
          document.getElementById("chat-emotion-decay-half-life-hours")
            ?.value || ""
        ).trim();
        return v === "" ? null : parseFloat(v);
      })(),
      emotion_decay_threshold: parseFloat(
        document.getElementById("chat-emotion-decay-threshold")?.value ||
          "0.005",
      ),
      emotion_neutral_threshold: parseFloat(
        document.getElementById("chat-emotion-neutral-threshold")?.value ||
          "0.01",
      ),
      // 画像生成設定 — ComfyUI
      image_gen_enabled: getChecked("chat-image-gen-enabled"),
      image_gen_comfyui_url: (
        document.getElementById("chat-image-gen-comfyui-url")?.value || ""
      ).trim(),
      image_gen_comfyui_width: parseInt(
        document.getElementById("chat-image-gen-width")?.value || "1024",
      ),
      image_gen_comfyui_height: parseInt(
        document.getElementById("chat-image-gen-height")?.value || "1024",
      ),
      image_gen_max_width: parseInt(
        document.getElementById("chat-image-gen-max-width")?.value || "1200",
      ),
      image_gen_max_height: parseInt(
        document.getElementById("chat-image-gen-max-height")?.value || "1200",
      ),
      image_gen_self_portrait_prompt:
        document.getElementById("chat-image-gen-self-portrait-prompt")?.value ||
        "",
      image_gen_negative_prompt:
        document.getElementById("chat-image-gen-negative-prompt")?.value || "",
      // プリセット解像度
      image_gen_presets: (() => {
        var p = {};
        [
          "portrait_large",
          "portrait_medium",
          "portrait_small",
          "landscape_large",
          "landscape_medium",
          "landscape_small",
          "square_large",
          "square_medium",
          "square_small",
        ].forEach((name) => {
          var el = document.getElementById("chat-image-gen-preset-" + name);
          if (el && el.value.trim()) p[name] = el.value.trim();
        });
        return p;
      })(),
      image_gen_default_preset:
        document.getElementById("chat-image-gen-default-preset")?.value ||
        "square_medium",
      image_gen_comfyui_workflow_template:
        document.getElementById("chat-image-gen-template")?.value || "",
      image_gen_comfyui_workflow_source:
        document.getElementById("chat-image-gen-workflow-source")?.value ||
        "local",
      image_gen_comfyui_workflow_name:
        document.getElementById("chat-image-gen-workflow-name")?.value || "",
      // 構図プリフィックス
      image_gen_full_body_prefix:
        document.getElementById("chat-image-gen-full-body-prefix")?.value || "",
      image_gen_portrait_prefix:
        document.getElementById("chat-image-gen-portrait-prefix")?.value || "",
      image_gen_selfie_prefix:
        document.getElementById("chat-image-gen-selfie-prefix")?.value || "",
      image_gen_scene_prefix:
        document.getElementById("chat-image-gen-scene-prefix")?.value || "",
      // Image caption (non-vision providers)
      image_caption_enabled: getChecked("chat-image-caption-enabled"),
      image_caption_provider:
        document.getElementById("chat-image-caption-provider")?.value ||
        "openai_compat",
      image_caption_model:
        document.getElementById("chat-image-caption-model")?.value.trim() || "",
      image_caption_api_key:
        document.getElementById("chat-image-caption-api-key")?.value || "",
      image_caption_base_url:
        document.getElementById("chat-image-caption-base-url")?.value.trim() ||
        "",
      // Voice / TTS settings (TE04)
      voice_url: document.getElementById("chat-voice-url")?.value || "",
      voice_auto_play: getChecked("chat-voice-auto-play"),
      voice_streaming: getChecked("chat-voice-streaming"),
      voice_emotion_mode:
        document.querySelector('input[name="chat-voice-emotion-mode"]:checked')
          ?.value || "anchor",
      voice_emotion_link:
        (document.querySelector('input[name="chat-voice-emotion-mode"]:checked')
          ?.value || "anchor") !== "off",
      voice_model: document.getElementById("chat-voice-model")?.value || "",
      // Irodori advanced params
      irodori_num_steps:
        parseInt(document.getElementById("chat-irodori-num-steps")?.value) ||
        30,
      irodori_cfg_scale_text:
        parseFloat(
          document.getElementById("chat-irodori-cfg-scale-text")?.value,
        ) || 3.2,
      irodori_cfg_scale_speaker:
        parseFloat(
          document.getElementById("chat-irodori-cfg-scale-speaker")?.value,
        ) || 5.0,
      irodori_cfg_scale_caption:
        parseFloat(
          document.getElementById("chat-irodori-cfg-scale-caption")?.value,
        ) || 4.2,
      irodori_chunk_min_chars:
        parseInt(
          document.getElementById("chat-irodori-chunk-min-chars")?.value,
        ) || 85,
      irodori_seed:
        parseInt(document.getElementById("chat-irodori-seed")?.value) || 0,
      irodori_caption_llm_enabled:
        (document.querySelector('input[name="chat-voice-emotion-mode"]:checked')
          ?.value || "anchor") === "llm",
      irodori_caption_llm_model:
        document.getElementById("chat-irodori-caption-llm-model")?.value || "",
      // Voice volume
      voice_volume:
        parseFloat(document.getElementById("chat-voice-volume")?.value) ?? 1.0,
      voice_speed:
        parseFloat(document.getElementById("chat-voice-speed")?.value) ?? 1.0,
      voice_enabled: getChecked("chat-voice-enabled"),
    };
    if (getChecked("chat-brain-llm-dedicated")) {
      payload.brain_llm_provider =
        document.getElementById("chat-brain-llm-provider")?.value.trim() || "";
      payload.brain_llm_model =
        document.getElementById("chat-brain-llm-model")?.value.trim() || "";
      payload.brain_llm_base_url =
        document.getElementById("chat-brain-llm-base-url")?.value.trim() || "";
      payload.brain_llm_api_key =
        document.getElementById("chat-brain-llm-api-key")?.value || "";
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
      N.Chat.settings.apply(cfg);
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
  // ------------------------------------------------------------------
  // Register namespace (chunk 4/4 — save API)
  // ------------------------------------------------------------------
  N.Chat.settings = N.Chat.settings || {};
  N.Chat.settings.save = saveChatConfig;
})(window.Nous);
