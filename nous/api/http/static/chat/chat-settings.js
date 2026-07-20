/* =================================================================
   CHAT SETTINGS — Configuration panel, MCP JSON, skills list
   Extracted from chat.js (Phase 3, Batch 1)
   ================================================================= */
;(function(N) {
var C = N.Core;
var api = C.api, esc = C.esc, toast = C.toast;
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
  set("chat-provider", cfg.provider);
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
  set("chat-max-tokens", cfg.max_tokens || 2048);
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
    dynTempCb.addEventListener("change", function () {
      emotionScaleEl.disabled = !this.checked;
    });
  }
  // Top P display sync
  const topPVal = document.getElementById("chat-top-p-val");
  const topPSlider = document.getElementById("chat-top-p");
  if (topPVal && topPSlider) {
    var v = parseFloat(topPSlider.value);
    topPVal.textContent = isNaN(v) ? "—" : v.toFixed(2);
  }
  onChatProviderChange();
  N.Chat.state.mcpServers = cfg.mcp_servers || [];
  renderMcpJson(N.Chat.state.mcpServers);
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
  set(
    "chat-display-history-turns",
    cfg.display_history_turns != null ? cfg.display_history_turns : 10,
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
  set("chat-memory-preload", cfg.memory_preload_count ?? 3);
  document.getElementById("chat-compress-system").checked =
    cfg.context_compress_system_prompt !== false;
  document.getElementById("chat-compress-history").checked =
    cfg.context_compress_history !== false;
  document.getElementById("chat-parallel-tools").checked =
    cfg.enable_parallel_tools !== false;
  document.getElementById("chat-llm-summary").checked =
    cfg.context_use_llm_summary !== false;
  document.getElementById("chat-episode-consolidation").checked =
    cfg.episode_consolidation_enabled !== false;
  document.getElementById("chat-episode-search").checked =
    cfg.episode_search_enabled !== false;
  document
    .getElementById("chat-compression-threshold")
    .addEventListener("input", function () {
      document.getElementById("threshold-display").textContent =
        this.value + "%";
    });
  // Voice / TTS settings (TE04)
  var voiceToggle = document.getElementById("chat-voice-enabled");
  if (voiceToggle) {
    voiceToggle.checked = cfg.voice_enabled || false;
    var voiceOptions = document.getElementById("chat-voice-options");
    if (voiceOptions) {
      voiceOptions.classList.toggle("settings-body-hidden", !voiceToggle.checked);
      voiceToggle.addEventListener("change", function() {
        voiceOptions.classList.toggle("settings-body-hidden", !this.checked);
      });
    }
  }
  var voiceUrlInput = document.getElementById("chat-voice-url");
  if (voiceUrlInput) voiceUrlInput.value = cfg.voice_url || "";
  setChecked("chat-voice-emotion-link", cfg.voice_emotion_link !== false);
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
  // Voice volume
  var voiceVolume = document.getElementById("chat-voice-volume");
  if (voiceVolume) voiceVolume.value = cfg.voice_volume ?? 1.0;
  if (voiceVolume) document.getElementById("chat-voice-volume-val").textContent = Math.round((cfg.voice_volume ?? 1.0) * 100) + "%";
  // Voice speed
  var voiceSpeed = document.getElementById("chat-voice-speed");
  if (voiceSpeed) voiceSpeed.value = cfg.voice_speed ?? 1.0;
  if (voiceSpeed) document.getElementById("chat-voice-speed-val").textContent = (cfg.voice_speed ?? 1.0).toFixed(2) + "x";
  // Check connection status
  checkVoiceConnection();
  // Debug mode
  setChecked("chat-debug-mode", cfg.debug_mode === true);
  const statusEl = document.getElementById("chat-config-status");
  if (statusEl) {
    if (cfg.is_configured) {
      statusEl.innerHTML =
        '<span style="color:var(--accent-green)"><i data-lucide="check"></i> APIキー設定済み</span>';
    } else {
      statusEl.innerHTML =
        '<span style="color:var(--accent-yellow)"><i data-lucide="alert-triangle"></i> APIキー未設定</span>';
    }
  }

  // Image gen enabled toggle
  var imgGenToggle = document.getElementById("chat-image-gen-enabled");
  if (imgGenToggle) {
    imgGenToggle.checked = cfg.image_gen_enabled || false;
    var imgGenOptions = document.getElementById("chat-image-options");
    if (imgGenOptions) {
      imgGenOptions.classList.toggle("settings-body-hidden", !imgGenToggle.checked);
      imgGenToggle.addEventListener("change", function() {
        imgGenOptions.classList.toggle("settings-body-hidden", !this.checked);
      });
    }
  }
  // 画像生成設定
  set("chat-image-gen-comfyui-url", cfg.image_gen_comfyui_url);
  set("chat-image-gen-checkpoint", cfg.image_gen_comfyui_checkpoint);
  set("chat-image-gen-width", cfg.image_gen_comfyui_width);
  set("chat-image-gen-height", cfg.image_gen_comfyui_height);
  set("chat-image-gen-max-width", cfg.image_gen_max_width);
  set("chat-image-gen-max-height", cfg.image_gen_max_height);
  set("chat-image-gen-steps", cfg.image_gen_comfyui_steps);
  set("chat-image-gen-cfg", cfg.image_gen_comfyui_cfg);
  set("chat-image-gen-sampler", cfg.image_gen_comfyui_sampler);
  set("chat-image-gen-scheduler", cfg.image_gen_comfyui_scheduler);
  set("chat-image-gen-seed", cfg.image_gen_comfyui_seed);
  set("chat-image-gen-denoise", cfg.image_gen_comfyui_denoise);
  set("chat-image-gen-speed-lora-method", cfg.image_gen_comfyui_speed_lora_method);
  set("chat-image-gen-speed-lora-path", cfg.image_gen_comfyui_speed_lora_path);
  set("chat-image-gen-speed-lora-weight", cfg.image_gen_comfyui_speed_lora_weight);
  set("chat-image-gen-self-portrait-prompt", cfg.image_gen_self_portrait_prompt);
  set("chat-image-gen-negative-prompt", cfg.image_gen_negative_prompt || "");
  // LoRA リスト復元
  var loraContainer = document.getElementById('chat-image-gen-lora-list');
  if (loraContainer) loraContainer.innerHTML = '';
  if (cfg.image_gen_comfyui_loras) {
    try {
      var loras = JSON.parse(cfg.image_gen_comfyui_loras);
      loras.forEach(function(l) { addLoraRow(l.path, l.weight); });
    } catch(e) { console.error('LoRA JSON parse error:', e); }
  }
  // スライダー値表示更新
  updateImageGenSliderLabels();
  // URLが設定済みなら疎通確認を自動実行
  if (cfg.image_gen_comfyui_url) {
    checkComfyUIHealth();
  }
}

function onChatProviderChange() {
  const provider = document.getElementById("chat-provider").value;
  const baseUrlRow = document.getElementById("chat-base-url-row");
  if (baseUrlRow) {
    baseUrlRow.style.display =
      provider === "openrouter" || provider === "openai" ? "" : "none";
  }
}

async function saveChatConfig() {
  if (!S.persona) {
    toast("ペルソナを選択してください", "error");
    return;
  }
  const apiKeyEl = document.getElementById("chat-api-key");
  const apiKeyVal = apiKeyEl ? apiKeyEl.value.trim() : "";
  const getChecked = (id) => document.getElementById(id)?.checked ?? false;
  const payload = {
    provider: document.getElementById("chat-provider").value,
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
    enable_parallel_tools: document.getElementById("chat-parallel-tools")
      .checked,
    context_use_llm_summary: getChecked("chat-llm-summary"),
    episode_consolidation_enabled: getChecked("chat-episode-consolidation"),
    episode_search_enabled: getChecked("chat-episode-search"),
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
    mcp_servers: parseMcpJson(),
    tool_result_max_chars: parseInt(
      document.getElementById("chat-tool-result-max")?.value || "4000",
    ),
    enabled_skills: BUILTIN_SKILLS.concat(
      (N.Chat.state.enabledSkills || []).filter(function (s) {
        return !BUILTIN_SKILLS.includes(s);
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
    retrieval_rrf_k: parseInt(
      document.getElementById("chat-retrieval-rrf-k")?.value || "5",
    ),
    display_history_turns: parseInt(
      document.getElementById("chat-display-history-turns")?.value || "10",
    ),
    mental_model_enabled: getChecked("chat-mental-model-enabled"),
    mental_model_min_samples: parseInt(
      document.getElementById("chat-mental-model-min-samples")?.value || "3",
    ),
    debug_mode: getChecked("chat-debug-mode"),
    // 画像生成設定 — ComfyUI
    image_gen_enabled: getChecked("chat-image-gen-enabled"),
    image_gen_comfyui_url: (document.getElementById("chat-image-gen-comfyui-url")?.value || "").trim(),
    image_gen_comfyui_checkpoint: document.getElementById("chat-image-gen-checkpoint")?.value || "noobaiXLNAIXL_epsilonPred11Version.safetensors",
    image_gen_comfyui_width: parseInt(document.getElementById("chat-image-gen-width")?.value || "1024"),
    image_gen_comfyui_height: parseInt(document.getElementById("chat-image-gen-height")?.value || "1024"),
    image_gen_max_width: parseInt(document.getElementById("chat-image-gen-max-width")?.value || "1200"),
    image_gen_max_height: parseInt(document.getElementById("chat-image-gen-max-height")?.value || "1200"),
    image_gen_comfyui_steps: parseInt(document.getElementById("chat-image-gen-steps")?.value || "28"),
    image_gen_comfyui_cfg: parseFloat(document.getElementById("chat-image-gen-cfg")?.value || "5.5"),
    image_gen_comfyui_sampler: document.getElementById("chat-image-gen-sampler")?.value || "euler_ancestral",
    image_gen_comfyui_scheduler: document.getElementById("chat-image-gen-scheduler")?.value || "normal",
    image_gen_comfyui_seed: parseInt(document.getElementById("chat-image-gen-seed")?.value || "0"),
    image_gen_comfyui_denoise: parseFloat(document.getElementById("chat-image-gen-denoise")?.value || "0.7"),
    image_gen_comfyui_speed_lora_method: document.getElementById("chat-image-gen-speed-lora-method")?.value || "",
    image_gen_comfyui_speed_lora_path: document.getElementById("chat-image-gen-speed-lora-path")?.value || "",
    image_gen_comfyui_speed_lora_weight: parseFloat(document.getElementById("chat-image-gen-speed-lora-weight")?.value || "1.0"),
    image_gen_comfyui_loras: JSON.stringify(collectLoraRows()),
    image_gen_self_portrait_prompt: document.getElementById("chat-image-gen-self-portrait-prompt")?.value || "",
    image_gen_negative_prompt: document.getElementById("chat-image-gen-negative-prompt")?.value || "",
    // Voice / TTS settings (TE04)
    voice_url: document.getElementById("chat-voice-url")?.value || "",
    voice_auto_play: getChecked("chat-voice-auto-play"),
    voice_emotion_link: getChecked("chat-voice-emotion-link"),
    voice_model: document.getElementById("chat-voice-model")?.value || "",
    // Irodori advanced params
    irodori_num_steps: parseInt(document.getElementById("chat-irodori-num-steps")?.value) || 30,
    irodori_cfg_scale_text: parseFloat(document.getElementById("chat-irodori-cfg-scale-text")?.value) || 3.2,
    irodori_cfg_scale_speaker: parseFloat(document.getElementById("chat-irodori-cfg-scale-speaker")?.value) || 5.0,
    irodori_cfg_scale_caption: parseFloat(document.getElementById("chat-irodori-cfg-scale-caption")?.value) || 4.2,
    irodori_chunk_min_chars: parseInt(document.getElementById("chat-irodori-chunk-min-chars")?.value) || 85,
    irodori_seed: parseInt(document.getElementById("chat-irodori-seed")?.value) || 0,
    // Voice volume
    voice_volume: parseFloat(document.getElementById("chat-voice-volume")?.value) ?? 1.0,
    voice_speed: parseFloat(document.getElementById("chat-voice-speed")?.value) ?? 1.0,
    voice_enabled: getChecked("chat-voice-enabled"),
  };
  const btn = document.querySelector(".chat-save-btn");
  if (btn) {
    btn.disabled = true;
    btn.innerHTML = '<i data-lucide="loader"></i> 保存中...';
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
      btn.innerHTML = '<i data-lucide="save"></i> 設定を保存';
      if (typeof lucide !== "undefined") lucide.createIcons();
    }
  }
}

// ------------------------------------------------------------------
// MCP JSON rendering / parsing
// ------------------------------------------------------------------
function renderMcpJson(servers) {
  const ta = document.getElementById("chat-mcp-json");
  if (!ta) return;
  if (!servers || servers.length === 0) {
    ta.value = '{\n  "mcpServers": {}\n}';
    return;
  }
  const mcpServers = {};
  (servers || []).forEach((srv) => {
    const entry = {};
    if (srv.transport === "http") {
      entry.url = srv.url || "";
      if (srv.headers && Object.keys(srv.headers).length)
        entry.headers = srv.headers;
    } else {
      entry.command = srv.command || "";
      if (srv.args && srv.args.length) entry.args = srv.args;
      if (srv.headers && Object.keys(srv.headers).length)
        entry.env = srv.headers;
    }
    mcpServers[srv.name] = entry;
  });
  ta.value = JSON.stringify({ mcpServers }, null, 2);

  /* ── Render MCP server list with Built-in badges ── */
  var listEl = document.getElementById("chat-mcp-server-list");
  if (listEl) {
    listEl.innerHTML = "";
    (servers || []).forEach(function (srv) {
      var isBuiltin = srv._builtin === true;
      var row = document.createElement("div");
      row.style.cssText =
        "display:flex;align-items:center;gap:8px;padding:6px 0;border-bottom:1px solid var(--glass-border);";
      var nameSpan = document.createElement("span");
      nameSpan.style.cssText =
        "font-size:0.82rem;color:var(--text-secondary);font-weight:500;";
      nameSpan.textContent = srv.name;
      row.appendChild(nameSpan);
      if (isBuiltin) {
        var badge = document.createElement("span");
        badge.className = "builtin-badge";
        badge.textContent = "Built-in";
        row.appendChild(badge);
      }
      var spacer = document.createElement("span");
      spacer.style.cssText = "flex:1;";
      row.appendChild(spacer);
      if (!isBuiltin) {
        var delBtn = document.createElement("button");
        delBtn.className = "mem-action-btn del";
        delBtn.textContent = "削除";
        delBtn.style.cssText = "font-size:0.68rem;padding:2px 8px;";
        delBtn.onclick = function () {
          N.Chat.state.mcpServers = N.Chat.state.mcpServers.filter(function (s) {
            return s.name !== srv.name;
          });
          renderMcpJson(N.Chat.state.mcpServers);
        };
        row.appendChild(delBtn);
      }
      listEl.appendChild(row);
      renderMcpServerTools(listEl, srv);
    });
  }
}

function renderMcpServerTools(listEl, srv) {
  var toolsForServer = (N.Chat.state.mcpTools || []).filter(function(t) {
    return t.server === srv.name;
  });
  if (!toolsForServer.length) return;

  var collapsed = false;

  var head = document.createElement("div");
  head.style.cssText =
    "font-size:0.6rem;color:var(--text-muted);cursor:pointer;user-select:none;padding:1px 4px;";
  head.textContent = "▼ tools (" + toolsForServer.length + ")";

  var body = document.createElement("div");
  body.style.cssText =
    "display:flex;flex-wrap:wrap;gap:3px;padding:2px 0 4px 8px;";

  toolsForServer.forEach(function(tool) {
    var enabled =
      !(N.Chat.state.disabledTools &&
        N.Chat.state.disabledTools.has(tool.name));
    var badge = document.createElement("span");
    badge.textContent = tool.name;
    badge.title = (tool.description || "").slice(0, 100);
    badge.style.cssText =
      "font-size:0.6rem;padding:1px 5px;border-radius:3px;border:1px solid var(--glass-border);cursor:pointer;" +
      (enabled
        ? "background:var(--glass-bg);color:var(--text-secondary);"
        : "background:var(--bg-secondary);color:var(--text-muted);opacity:0.5;text-decoration:line-through;");
    badge.onclick = function(ev) {
      ev.stopPropagation();
      N.Chat.tools.toggle(tool.name);
      renderMcpJson(N.Chat.state.mcpServers);
    };
    body.appendChild(badge);
  });

  head.onclick = function() {
    collapsed = !collapsed;
    body.style.display = collapsed ? "none" : "flex";
    head.textContent =
      (collapsed ? "▶" : "▼") + " tools (" + toolsForServer.length + ")";
  };

  var wrapper = document.createElement("div");
  wrapper.style.cssText =
    "border-bottom:1px solid var(--glass-border);margin-bottom:2px;";
  wrapper.appendChild(head);
  wrapper.appendChild(body);
  listEl.appendChild(wrapper);
}

function parseMcpJson() {
  const ta = document.getElementById("chat-mcp-json");
  const errEl = document.getElementById("chat-mcp-json-error");
  if (!ta) return N.Chat.state.mcpServers;
  if (errEl) errEl.style.display = "none";
  const raw = ta.value.trim();
  if (!raw || raw === '{\n  "mcpServers": {}\n}') return [];
  try {
    const parsed = JSON.parse(raw);
    const dict = parsed.mcpServers || {};
    /* Preserve _builtin flags from original N.Chat.state.mcpServers */
    var builtinMap = {};
    (N.Chat.state.mcpServers || []).forEach(function (s) {
      if (s._builtin) builtinMap[s.name] = true;
    });
    return Object.entries(dict).map(([name, cfg]) => ({
      name,
      transport: cfg.url ? "http" : "stdio",
      url: cfg.url || "",
      command: cfg.command || "",
      args: cfg.args || [],
      headers: cfg.headers || cfg.env || {},
      enabled: true,
      _builtin: builtinMap[name] || false,
    }));
  } catch (e) {
    // Try loosened JSON parsing
    try {
      const loosened = loosenJson(raw);
      const parsed = JSON.parse(loosened);
      const dict = parsed.mcpServers || {};
      var builtinMap = {};
      (N.Chat.state.mcpServers || []).forEach(function (s) {
        if (s._builtin) builtinMap[s.name] = true;
      });
      return Object.entries(dict).map(([name, cfg]) => ({
        name,
        transport: cfg.url ? "http" : "stdio",
        url: cfg.url || "",
        command: cfg.command || "",
        args: cfg.args || [],
        headers: cfg.headers || cfg.env || {},
        enabled: true,
        _builtin: builtinMap[name] || false,
      }));
    } catch (e2) {
      if (errEl) {
        errEl.textContent = "JSON形式エラー: " + e2.message;
        errEl.style.display = "";
      }
      return N.Chat.state.mcpServers;
    }
  }
}

// ------------------------------------------------------------------
// Skills list rendering
// ------------------------------------------------------------------
const BUILTIN_SKILLS = ["search"];

function renderSkillsList(allSkills, enabledSkills) {
  const list = document.getElementById("chat-skills-list");
  if (!list) return;
  list.innerHTML = "";
  if (!allSkills || allSkills.length === 0) {
    list.innerHTML =
      '<div style="font-size:0.75rem;color:var(--text-muted);">スキルがありません</div>';
    return;
  }
  allSkills.forEach((skill) => {
    const enabled = (enabledSkills || []).includes(skill.name);
    const isBuiltin = BUILTIN_SKILLS.includes(skill.name);
    const item = document.createElement("div");
    item.style.cssText = "display:flex;align-items:center;gap:8px;";
    const cb = document.createElement("input");
    cb.type = "checkbox";
    cb.checked = enabled;
    cb.id = "skill-cb-" + skill.name;
    cb.style.cssText =
      "width:14px;height:14px;accent-color:var(--accent-purple);cursor:pointer;";
    if (isBuiltin) {
      cb.disabled = true;
      cb.title = "Built-in スキルは削除できません";
    }
    cb.addEventListener("change", () => {
      if (cb.checked) {
        if (!N.Chat.state.enabledSkills.includes(skill.name))
          N.Chat.state.enabledSkills.push(skill.name);
      } else {
        N.Chat.state.enabledSkills = N.Chat.state.enabledSkills.filter((n) => n !== skill.name);
      }
      saveChatConfig();
    });
    const label = document.createElement("label");
    label.htmlFor = cb.id;
    label.style.cssText =
      "font-size:0.78rem;color:var(--text-secondary);cursor:pointer;display:inline-flex;align-items:center;gap:6px;";
    label.title = skill.description || "";
    label.textContent = skill.name;
    if (isBuiltin) {
      var badge = document.createElement("span");
      badge.className = "builtin-badge";
      badge.textContent = "Built-in";
      label.appendChild(badge);
    }
    item.appendChild(cb);
    item.appendChild(label);
    list.appendChild(item);
  });
}

// ------------------------------------------------------------------
// JSON utilities
// ------------------------------------------------------------------
function loosenJson(text) {
  var s = text.trim();
  if (!s) return s;
  // Remove // line comments
  s = s.replace(/\/\/.*$/gm, '');
  // Remove /* */ block comments
  s = s.replace(/\/\*[\s\S]*?\*\//g, '');
  // Convert single-quoted keys/values to double-quoted (simple heuristic)
  s = s.replace(/'([^']*)'/g, function(m, inner) {
    return '"' + inner.replace(/"/g, '\\"') + '"';
  });
  // Quote unquoted keys: /(\s*)(\w+)(\s*):/ → $1"$2"$3:
  s = s.replace(/([{,]\s*)([a-zA-Z_]\w*)(\s*:)/g, '$1"$2"$3');
  // Remove trailing commas before } or ]
  s = s.replace(/,(\s*[}\]])/g, '$1');
  return s;
}

async function formatMcpJson() {
  var ta = document.getElementById("chat-mcp-json");
  var errDiv = document.getElementById("chat-mcp-json-error");
  if (!ta) return;
  var raw = ta.value.trim();
  if (!raw) { ta.value = '{\n  "mcpServers": {}\n}'; return; }
  try {
    // Try strict first
    var parsed = JSON.parse(raw);
    ta.value = JSON.stringify(parsed, null, 2);
    if (errDiv) errDiv.style.display = "none";
  } catch (e) {
    // Try loosened
    try {
      var parsed2 = JSON.parse(loosenJson(raw));
      ta.value = JSON.stringify(parsed2, null, 2);
      if (errDiv) errDiv.style.display = "none";
    } catch (e2) {
      if (errDiv) {
        errDiv.textContent = "整形できません: " + e2.message;
        errDiv.style.display = "block";
      }
    }
  }
}

// ------------------------------------------------------------------
// ComfyUI helper functions
// ------------------------------------------------------------------
function addLoraRow(path, weight) {
  var container = document.getElementById('chat-image-gen-lora-list');
  if (!container) return;
  var idx = container.children.length;
  var div = document.createElement('div');
  div.style.cssText = 'display:flex;gap:4px;align-items:center;';
  div.innerHTML = '<input type="text" class="chat-field-input lora-path" value="' + escHtml(path || '') + '" placeholder="lora.safetensors" style="flex:1;font-size:0.82rem;">'
    + '<input type="number" class="chat-field-input lora-weight" value="' + (weight || 1.0).toFixed(1) + '" min="0.1" max="2.0" step="0.1" style="width:55px;font-size:0.82rem;">'
    + '<button type="button" onclick="this.parentElement.remove()" style="color:var(--accent-red);background:none;border:none;cursor:pointer;font-size:1rem;">\u00d7</button>';
  container.appendChild(div);
}

function collectLoraRows() {
  var container = document.getElementById('chat-image-gen-lora-list');
  if (!container) return [];
  var result = [];
  container.querySelectorAll('.lora-path').forEach(function(input, i) {
    var path = input.value.trim();
    if (path) {
      var weightEl = container.querySelectorAll('.lora-weight')[i];
      result.push({path: path, weight: parseFloat(weightEl ? weightEl.value : 1.0)});
    }
  });
  return result;
}

function updateImageGenSliderLabels() {
  // HTML側の oninput で処理するため、ここでは何もしない
}

function testImageGen() {
  var status = document.getElementById('chat-image-test-status');
  if (!status) return;
  status.textContent = '生成中...';
  status.style.color = 'var(--text-muted)';
  
  var payload = {
    checkpoint: document.getElementById('chat-image-gen-checkpoint')?.value || '',
    loras: collectLoraRows(),
    width: parseInt(document.getElementById('chat-image-gen-width')?.value || '1024'),
    height: parseInt(document.getElementById('chat-image-gen-height')?.value || '1024'),
    steps: parseInt(document.getElementById('chat-image-gen-steps')?.value || '28'),
    cfg: parseFloat(document.getElementById('chat-image-gen-cfg')?.value || '5.5'),
    sampler: document.getElementById('chat-image-gen-sampler')?.value || 'euler_ancestral',
    scheduler: document.getElementById('chat-image-gen-scheduler')?.value || 'normal',
    seed: parseInt(document.getElementById('chat-image-gen-seed')?.value || '0'),
    denoise: parseFloat(document.getElementById('chat-image-gen-denoise')?.value || '0.7'),
    prompt: document.getElementById('chat-image-gen-self-portrait-prompt')?.value.trim() || '1girl, herta, honkai star rail, solo, smile',
    negative_prompt: 'lowres, bad anatomy, bad hands, text, error',
  };
  
  fetch('/api/chat/' + (S.persona || '') + '/image-gen/test', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(payload)
  })
  .then(function(r) { return r.json(); })
  .then(function(d) {
    if (d.error) { status.textContent = '\ud83d\udd34 ' + d.error; status.style.color = 'var(--accent-red)'; return; }
    status.textContent = '\u2705 \u751f\u6210\u5b8c\u4e86 (' + (d.images ? d.images.length : 0) + '\u679a)';
    status.style.color = 'var(--accent-green)';
  })
  .catch(function(e) {
    status.textContent = '\ud83d\udd34 ' + e.message;
    status.style.color = 'var(--accent-red)';
  });
}

function checkComfyUIHealth() {
  var url = document.getElementById('chat-image-gen-comfyui-url').value.trim();
  var status = document.getElementById('chat-image-status');
  if (!url) { status.textContent = '⚠ URLを入力してください'; status.style.color = 'var(--accent-yellow)'; return; }
  status.textContent = '確認中...';
  status.style.color = 'var(--text-secondary)';
  var controller = new AbortController();
  var timeoutId = setTimeout(function() { controller.abort(); }, 10000);
  fetch('/api/image-gen/health?url=' + encodeURIComponent(url), { signal: controller.signal })
    .then(function(r) { return r.json(); })
    .then(function(d) {
      clearTimeout(timeoutId);
      if (d.healthy) {
        status.textContent = '🟢 接続OK';
        status.style.color = 'var(--accent-green)';
      } else {
        status.textContent = '🔴 ' + (d.error || '接続失敗');
        status.style.color = 'var(--accent-red)';
      }
    })
    .catch(function(e) {
      clearTimeout(timeoutId);
      status.textContent = '🔴 ' + (e.name === 'AbortError' ? 'タイムアウト' : e.message);
      status.style.color = 'var(--accent-red)';
    });
}

function escHtml(s) {
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

// イベントリスナー初期化 (DOMContentLoaded 安全策)
(function initImageGenEvents() {
  function bind() {
    var addBtn = document.getElementById('chat-image-gen-lora-add');
    if (addBtn && !addBtn._bound) {
      addBtn._bound = true;
      addBtn.addEventListener('click', function() { addLoraRow('', 1.0); });
    }
    // ページロード時にComfyUI URLが設定済みなら疎通確認
    if (document.getElementById('chat-image-gen-comfyui-url')?.value) {
      checkComfyUIHealth();
    }
  }
  if (document.readyState !== 'loading') bind();
  else document.addEventListener('DOMContentLoaded', bind);
})();

// ------------------------------------------------------------------
// Register namespace and global backward-compat aliases
// ------------------------------------------------------------------
N.Chat.settings = {
  load: loadChatConfig,
  apply: applyChatConfig,
  save: saveChatConfig,
};

window.loadChatConfig = loadChatConfig;
window.applyChatConfig = applyChatConfig;
window.onChatProviderChange = onChatProviderChange;
window.saveChatConfig = saveChatConfig;
window.renderMcpJson = renderMcpJson;
window.parseMcpJson = parseMcpJson;
window.renderSkillsList = renderSkillsList;
window.loosenJson = loosenJson;
window.formatMcpJson = formatMcpJson;
window.checkComfyUIHealth = checkComfyUIHealth;
window.updateImageGenSliderLabels = updateImageGenSliderLabels;
window.testImageGen = testImageGen;

window.addLoraRow = addLoraRow;
window.collectLoraRows = collectLoraRows;

})(window.Nous);
