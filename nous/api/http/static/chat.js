/* =================================================================
   CHAT TAB
   ================================================================= */
const CHAT = {
  streaming: false,
  sidebarOpen: true,
  memoryPanelOpen: true,
  messages: [], // { role, content, time }
  mcpServers: [],
  enabledSkills: [],
  abortController: null, // F4: AbortController for streaming cancel
  attachments: [], // { filename, url, workspace_path, mime_type, size }
};

const HELP_TEXTS = {
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
};

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

function loadChat() {
  if (!S.persona) return;
  loadChatConfig();
  loadSkillsForChat();
  restoreChatHistory();
  loadChatCommitments();
  loadEquipment();
  loadPortrait();
  setTimeout(() => {
    if (typeof lucide !== "undefined") lucide.createIcons();
  }, 100);
}

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
  } catch (_e) {
    // commitments API unavailable — ignore silently
  }
}

async function loadEquipment() {
  if (!S.persona) return;
  try {
    const data = await api("/api/dashboard/" + encodeURIComponent(S.persona));
    const equipment = data.equipment || {};
    updateEquipmentPanel({ equip: equipment });
  } catch (_e) {
    // dashboard API unavailable — ignore silently
  }
}

async function loadSkillsForChat() {
  try {
    // Auto-sync skills from filesystem on every chat tab open
    await api("/api/skills/sync", { method: "POST" });
    const skills = await api("/api/skills");
    renderSkillsList(skills, CHAT.enabledSkills);
  } catch (_e) {
    // skills API not available yet, ignore
  }
}

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
  CHAT.mcpServers = cfg.mcp_servers || [];
  renderMcpJson(CHAT.mcpServers);
  const toolMax = document.getElementById("chat-tool-result-max");
  const toolMaxVal = document.getElementById("chat-tool-max-val");
  if (toolMax && cfg.tool_result_max_chars) {
    toolMax.value = cfg.tool_result_max_chars;
    if (toolMaxVal) toolMaxVal.textContent = cfg.tool_result_max_chars;
  }
  CHAT.enabledSkills = cfg.enabled_skills || [];
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
  // Housekeeping settings
  set(
    "chat-display-history-turns",
    cfg.display_history_turns != null ? cfg.display_history_turns : 20,
  );
  set(
    "chat-housekeeping-threshold",
    cfg.housekeeping_threshold != null ? cfg.housekeeping_threshold : 10,
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
  // Sandbox settings
  setChecked("chat-sandbox-enabled", cfg.sandbox_enabled === true);
  onSandboxEnabledChange();
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

  // 画像生成設定
  const igEnabled = document.getElementById("chat-image-gen-enabled");
  const igProvider = document.getElementById("chat-image-gen-provider");
  const igDalleModel = document.getElementById("chat-image-gen-dalle-model");
  const igStabilityUrl = document.getElementById(
    "chat-image-gen-stability-url",
  );
  const igOptions = document.getElementById("chat-image-gen-options");
  const igDalleOptions = document.getElementById(
    "chat-image-gen-dalle-options",
  );
  const igStabilityOptions = document.getElementById(
    "chat-image-gen-stability-options",
  );

  if (igEnabled) igEnabled.checked = cfg.image_gen_enabled || false;
  if (igProvider) igProvider.value = cfg.image_gen_provider || "openai";
  if (igDalleModel)
    igDalleModel.value = cfg.image_gen_dalle_model || "dall-e-3";
  if (igStabilityUrl) igStabilityUrl.value = cfg.image_gen_stability_url || "";

  // 表示切替
  function updateImageGenUI() {
    if (!igOptions) return;
    const enabled = igEnabled && igEnabled.checked;
    igOptions.style.display = enabled ? "" : "none";
    if (igProvider && igDalleOptions && igStabilityOptions) {
      const prov = igProvider.value;
      igDalleOptions.style.display = prov === "openai" ? "" : "none";
      igStabilityOptions.style.display = prov === "stability" ? "" : "none";
    }
  }
  if (igEnabled) igEnabled.addEventListener("change", updateImageGenUI);
  if (igProvider) igProvider.addEventListener("change", updateImageGenUI);
  updateImageGenUI();
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
      (CHAT.enabledSkills || []).filter(function (s) {
        return !BUILTIN_SKILLS.includes(s);
      }),
    ),
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
    display_history_turns: parseInt(
      document.getElementById("chat-display-history-turns")?.value || "20",
    ),
    housekeeping_threshold: parseInt(
      document.getElementById("chat-housekeeping-threshold")?.value || "10",
    ),
    sandbox_enabled: getChecked("chat-sandbox-enabled"),
    mental_model_enabled: getChecked("chat-mental-model-enabled"),
    mental_model_min_samples: parseInt(
      document.getElementById("chat-mental-model-min-samples")?.value || "3",
    ),
    debug_mode: getChecked("chat-debug-mode"),
    // 画像生成設定
    image_gen_enabled: document.getElementById("chat-image-gen-enabled")
      ? document.getElementById("chat-image-gen-enabled").checked
      : false,
    image_gen_provider: document.getElementById("chat-image-gen-provider")
      ? document.getElementById("chat-image-gen-provider").value
      : "openai",
    image_gen_dalle_model: document.getElementById("chat-image-gen-dalle-model")
      ? document.getElementById("chat-image-gen-dalle-model").value
      : "dall-e-3",
    image_gen_stability_url: document.getElementById(
      "chat-image-gen-stability-url",
    )
      ? document.getElementById("chat-image-gen-stability-url").value.trim()
      : "",
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
          CHAT.mcpServers = CHAT.mcpServers.filter(function (s) {
            return s.name !== srv.name;
          });
          renderMcpJson(CHAT.mcpServers);
          renderMcpServerList(CHAT.mcpServers);
        };
        row.appendChild(delBtn);
      }
      listEl.appendChild(row);
    });
  }
}

function parseMcpJson() {
  const ta = document.getElementById("chat-mcp-json");
  const errEl = document.getElementById("chat-mcp-json-error");
  if (!ta) return CHAT.mcpServers;
  if (errEl) errEl.style.display = "none";
  const raw = ta.value.trim();
  if (!raw || raw === '{\n  "mcpServers": {}\n}') return [];
  try {
    const parsed = JSON.parse(raw);
    const dict = parsed.mcpServers || {};
    /* Preserve _builtin flags from original CHAT.mcpServers */
    var builtinMap = {};
    (CHAT.mcpServers || []).forEach(function (s) {
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
    if (errEl) {
      errEl.textContent = "JSON形式エラー: " + e.message;
      errEl.style.display = "";
    }
    return CHAT.mcpServers;
  }
}

const BUILTIN_SKILLS = ["browser", "search"];

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
        if (!CHAT.enabledSkills.includes(skill.name))
          CHAT.enabledSkills.push(skill.name);
      } else {
        CHAT.enabledSkills = CHAT.enabledSkills.filter((n) => n !== skill.name);
      }
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

// ESC key closes settings panel on mobile
document.addEventListener("keydown", function (e) {
  if (e.key === "Escape" && CHAT.sidebarOpen) {
    var isMobile = window.innerWidth <= 768;
    if (isMobile) {
      toggleSettingsPanel();
    }
  }
});

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

/* ── Memory Panel helpers ── */
function updateMemoryPanel(retrieved, saved, goals) {
  const escAttr = (s) =>
    String(s)
      .replace(/&/g, "&amp;")
      .replace(/"/g, "&quot;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;");
  if (retrieved !== undefined) {
    const retrievedList = document.getElementById("memory-retrieved-list");
    if (retrievedList) {
      if (!retrieved || retrieved.length === 0) {
        retrievedList.innerHTML = '<div class="memory-empty">なし</div>';
      } else {
        retrievedList.innerHTML = retrieved
          .map((m) => {
            const score = m.score != null ? parseFloat(m.score).toFixed(3) : "";
            const imp =
              m.importance != null ? parseFloat(m.importance).toFixed(2) : "";
            const content = esc((m.content || "").substring(0, 80));
            const meta = [
              score ? "score:" + score : "",
              imp ? "imp:" + imp : "",
            ]
              .filter(Boolean)
              .join(" ");
            const key = m.key || "";
            const emotionBadges = renderEmotionBadges(
              m.emotion,
              m.emotion_intensity,
            );
            const bodyCompact = renderBodyStateCompact(m.body_state);
            const extra = [emotionBadges, bodyCompact]
              .filter(Boolean)
              .join(" ");
            return (
              '<div class="memory-item-card" data-key="' +
              escAttr(key) +
              '" data-content="' +
              escAttr(m.content || "") +
              '" data-importance="' +
              (m.importance || 0.5) +
              '" data-tags="' +
              escAttr((m.tags || []).join(",")) +
              '" onclick="openMemEdit(this)">' +
              (meta ? '<div class="mem-score">' + esc(meta) + "</div>" : "") +
              content +
              (extra
                ? '<div class="mem-score" style="font-size:0.7rem;margin-top:3px">' +
                  extra +
                  "</div>"
                : "") +
              '<div class="mem-actions"><button class="mem-action-btn del" onclick="event.stopPropagation();deleteMemCard(\'' +
              escAttr(key) +
              "')\">削除</button></div>" +
              "</div>"
            );
          })
          .join("");
      }
    }
  }
  if (saved !== undefined) {
    const savedList = document.getElementById("memory-saved-list");
    if (savedList) {
      if (!saved || saved.length === 0) {
        savedList.innerHTML = '<div class="memory-empty">なし</div>';
      } else {
        savedList.innerHTML = saved
          .map((m) => {
            const content = esc((m.content || "").substring(0, 80));
            const tags = m.tags ? m.tags.join(", ") : "";
            const key = m.key || "";
            const emotionBadges = renderEmotionBadges(
              m.emotion,
              m.emotion_intensity,
            );
            const bodyCompact = renderBodyStateCompact(m.body_state);
            const extra = [emotionBadges, bodyCompact]
              .filter(Boolean)
              .join(" ");
            return (
              '<div class="memory-item-card" data-key="' +
              escAttr(key) +
              '" data-content="' +
              escAttr(m.content || "") +
              '" data-importance="' +
              (m.importance || 0.5) +
              '" data-tags="' +
              escAttr((m.tags || []).join(",")) +
              '" onclick="openMemEdit(this)">' +
              content +
              (tags ? '<div class="mem-score">' + esc(tags) + "</div>" : "") +
              (extra
                ? '<div class="mem-score" style="font-size:0.7rem;margin-top:3px">' +
                  extra +
                  "</div>"
                : "") +
              '<div class="mem-actions"><button class="mem-action-btn del" onclick="event.stopPropagation();deleteMemCard(\'' +
              escAttr(key) +
              "')\">削除</button></div>" +
              "</div>"
            );
          })
          .join("");
      }
    }
  }
  if (goals !== undefined) {
    const goalsList = document.getElementById("memory-goals-list");
    if (goalsList) {
      if (!goals || goals.length === 0) {
        goalsList.innerHTML = '<div class="memory-empty">なし</div>';
      } else {
        goalsList.innerHTML = goals
          .map((g) => {
            const key = g.key || "";
            return (
              '<div class="memory-item-card" data-key="' +
              escAttr(key) +
              '" data-content="' +
              escAttr(g.content || "") +
              '" data-importance="' +
              (g.importance || 0.75) +
              '" data-tags="' +
              escAttr((g.tags || []).join(",")) +
              '" onclick="openMemEdit(this)">' +
              '<i data-lucide="target"></i> ' +
              esc((g.content || "").substring(0, 80)) +
              '<div class="mem-actions"><button class="mem-action-btn done" onclick="event.stopPropagation();completeGoal(\'' +
              escAttr(key) +
              "','" +
              escAttr((g.content || "").substring(0, 50)) +
              '\')">完了</button><button class="mem-action-btn del" onclick="event.stopPropagation();deleteMemCard(\'' +
              escAttr(key) +
              "')\">削除</button></div>" +
              "</div>"
            );
          })
          .join("");
      }
    }
  }
}

function showReflectionStart() {
  const header = document.getElementById("reflection-header");
  if (header) {
    header.innerHTML =
      '<i data-lucide="sparkles"></i> リフレクション (実行中...)';
    if (typeof lucide !== "undefined") lucide.createIcons();
  }
  const list = document.getElementById("memory-reflection-list");
  if (list)
    list.innerHTML =
      '<div class="memory-empty" style="color:var(--accent-purple);">分析中...</div>';
}

function updateReflectionPanel(insights) {
  const header = document.getElementById("reflection-header");
  if (header) {
    header.innerHTML = '<i data-lucide="sparkles"></i> リフレクション';
    if (typeof lucide !== "undefined") lucide.createIcons();
  }
  const list = document.getElementById("memory-reflection-list");
  if (!list) return;
  if (!insights || insights.length === 0) {
    list.innerHTML = '<div class="memory-empty">洞察なし</div>';
    return;
  }
  list.innerHTML = insights
    .map((s) => '<div class="reflection-insight">' + esc(s) + "</div>")
    .join("");
}

function showSessionSummarized(summary) {
  const statusEl = document.getElementById("chat-status");
  if (statusEl) {
    statusEl.innerHTML =
      '<i data-lucide="edit-3"></i> セッションを要約しました';
    setTimeout(() => {
      if (statusEl) statusEl.textContent = "";
    }, 3000);
  }
}

function showContextCompressed(evt) {
  const beforePct = Math.round((evt.before_tokens / evt.budget) * 100);
  const afterPct = Math.round((evt.after_tokens / evt.budget) * 100);
  const savings = evt.before_tokens - evt.after_tokens;
  toast(
    "🧠 圧縮: " +
      evt.before_tokens +
      "→" +
      evt.after_tokens +
      " tokens (" +
      beforePct +
      "%→" +
      afterPct +
      "% 予算比) " +
      ((-savings / evt.before_tokens) * 100).toFixed(0) +
      "%削減",
    "info",
  );
}

function resetToWelcome() {
  const container = document.getElementById("chat-messages");
  container.innerHTML = `
        <div class="chat-welcome" id="chat-welcome">
            <div class="chat-welcome-icon"><i data-lucide="message-circle"></i></div>
            <p>チャットを開始するには下のテキストボックスにメッセージを入力してください。</p>
            <p class="chat-welcome-hint">APIキーとプロバイダーを設定してください。<br><a href="#" onclick="toggleSettingsPanel();return false;" class="chat-welcome-link"><i data-lucide="settings"></i> 設定パネルを開く</a></p>
            <div class="chat-welcome-commands">
                <span class="chat-welcome-cmd">/memory</span>
                <span class="chat-welcome-cmd">/goal</span>
                <span class="chat-welcome-cmd">/code</span>
                <span class="chat-welcome-cmd">/help</span>
                <span class="chat-welcome-cmd">/search</span>
                <span class="chat-welcome-cmd">/browser</span>
                <span class="chat-welcome-cmd">/image</span>
                <span class="chat-welcome-cmd">/sandbox</span>
                <span class="chat-welcome-cmd">/invoke_skill</span>
            </div>
        </div>`;
  setTimeout(() => {
    if (typeof lucide !== "undefined") lucide.createIcons();
  }, 50);
}

async function clearChatHistory() {
  if (CHAT.messages.length === 0) {
    resetToWelcome();
    return;
  }
  const ok = await showConfirm("会話をリセットしますか？現在の会話履歴がすべて削除されます。");
  if (!ok) return;
  CHAT.messages = [];
  resetToWelcome();
  // Delete server-side session (F3)
  const oldSid = getChatSessionId();
  if (S.persona && oldSid) {
    fetch(
      "/api/chat/" +
        encodeURIComponent(S.persona) +
        "/sessions/" +
        encodeURIComponent(oldSid),
      { method: "DELETE" },
    ).catch(() => {
      /* ignore */
    });
  }
  document.getElementById("chat-status").textContent = "会話をリセットしました";
  setTimeout(() => {
    document.getElementById("chat-status").textContent = "";
  }, 2000);
}

function getChatSessionId() {
  // Fixed session ID per persona — enables cross-device sync
  return "main";
}

// Rollback: undo messages from keep_until onwards, optionally auto-resend
async function rollbackChat(keepUntil, shouldResend) {
  if (!S.persona) return;
  const sid = getChatSessionId();

  try {
    const result = await api(
      "/api/chat/" +
        encodeURIComponent(S.persona) +
        "/sessions/" +
        encodeURIComponent(sid) +
        "/rollback",
      {
        method: "POST",
        body: JSON.stringify({ keep_until: keepUntil }),
      },
    );

    // Remove DOM messages from keep_until onwards
    const container = document.getElementById("chat-messages");
    const allMsgs = container.querySelectorAll(".chat-msg");
    for (const msg of allMsgs) {
      if (parseInt(msg.dataset.msgIndex) >= keepUntil) {
        msg.remove();
      }
    }

    // Restore welcome if no messages left
    if (container.querySelectorAll(".chat-msg").length === 0) {
      resetToWelcome();
    }

    if (result.removed_user_text) {
      const inputEl = document.getElementById("chat-input");
      if (inputEl) {
        inputEl.value = result.removed_user_text;
        inputEl.focus();
        inputEl.dispatchEvent(new Event("input"));
      }

      if (shouldResend) {
        // Small delay to let the DOM settle, then auto-send
        setTimeout(() => {
          chatSend(false);
        }, 100);
      }
    }

    if (result.removed_count > 0) {
      toast(
        "🔄 " + result.removed_count + "件のメッセージを元に戻しました",
        "info",
      );
    }
  } catch (e) {
    toast("ロールバック失敗: " + e.message, "error");
  }
}

function appendChatMessage(role, content, timeStr, isMarkdown) {
  const container = document.getElementById("chat-messages");
  // Remove welcome message if present
  const welcome = container.querySelector(".chat-welcome");
  if (welcome) welcome.remove();

  // Calculate message index (0-based position in session)
  const msgIndex = container.querySelectorAll(".chat-msg").length;

  const div = document.createElement("div");
  div.className = "chat-msg " + role;
  div.dataset.msgIndex = msgIndex;
  const bubble = document.createElement("div");
  bubble.className = "chat-bubble";
  if (isMarkdown && role === "assistant") {
    bubble.innerHTML = safeMarkdown(content);
    // メッセージ内の画像にクリックイベント追加
    bubble.querySelectorAll("img").forEach((img) => {
      img.style.cssText =
        "max-width:100%;border-radius:8px;cursor:pointer;margin:8px 0;";
      img.addEventListener("click", () => openMediaViewer(img.src, "image"));
    });
  } else {
    bubble.textContent = content;
  }
  const timeDiv = document.createElement("div");
  timeDiv.className = "chat-time";
  timeDiv.textContent =
    timeStr ||
    new Date().toLocaleTimeString("ja-JP", {
      hour: "2-digit",
      minute: "2-digit",
    });
  div.appendChild(bubble);
  div.appendChild(timeDiv);

  // Action buttons
  const actions = document.createElement("div");
  actions.className = "chat-msg-actions";
  if (role === "user") {
    const editBtn = document.createElement("button");
    editBtn.className = "chat-msg-action-btn edit";
    editBtn.innerHTML = '<i data-lucide="pencil"></i> 編集';
    editBtn.onclick = () => {
      rollbackChat(msgIndex, false);
    };
    actions.appendChild(editBtn);
  } else if (role === "assistant") {
    const ttsBtn = document.createElement("button");
    ttsBtn.className = "chat-msg-action-btn chat-tts-btn";
    ttsBtn.innerHTML = '<i data-lucide="volume-2"></i>';
    ttsBtn.title = "音声で再生";
    ttsBtn.setAttribute("aria-label", "音声で再生");
    ttsBtn.onclick = () => playTts(ttsBtn, content);
    actions.appendChild(ttsBtn);
    const retryBtn = document.createElement("button");
    retryBtn.className = "chat-msg-action-btn retry";
    retryBtn.innerHTML = '<i data-lucide="refresh-cw"></i> 再生成';
    retryBtn.onclick = () => {
      // Rollback to the paired user message (at index-1) and auto-resend
      rollbackChat(msgIndex, true);
    };
    actions.appendChild(retryBtn);
    const copyBtn = document.createElement("button");
    copyBtn.className = "chat-msg-action-btn";
    copyBtn.innerHTML = '<i data-lucide="clipboard-list"></i>';
    copyBtn.title = "コピー";
    copyBtn.onclick = () => {
      navigator.clipboard
        .writeText(content)
        .then(() => toast("コピーしました", "success"));
    };
    actions.appendChild(copyBtn);
  }
  div.appendChild(actions);

  container.appendChild(div);
  container.scrollTop = container.scrollHeight;
  setTimeout(() => {
    if (typeof lucide !== "undefined") lucide.createIcons();
  }, 50);
  return div;
}

// F1: Safe Markdown renderer using marked.js + DOMPurify
function safeMarkdown(text) {
  if (!text) return "";
  try {
    if (typeof marked !== "undefined" && typeof DOMPurify !== "undefined") {
      // Pre-process fenced code blocks to preserve onclick handlers through DOMPurify
      const codeBlocks = [];
      const textWithPlaceholders = text.replace(
        /```(\w*)\n([\s\S]*?)```/g,
        function (_, lang, code) {
          const idx = codeBlocks.length;
          codeBlocks.push(renderCodeBlock(lang || "", code.trimEnd()));
          return "CODEBLOCK_PLACEHOLDER_" + idx + "_END";
        },
      );
      const html = marked.parse(textWithPlaceholders, {
        breaks: true,
        gfm: true,
      });
      let sanitized = DOMPurify.sanitize(html, {
        ALLOWED_TAGS: [
          "p",
          "strong",
          "em",
          "b",
          "i",
          "u",
          "s",
          "code",
          "pre",
          "ul",
          "ol",
          "li",
          "h1",
          "h2",
          "h3",
          "h4",
          "blockquote",
          "a",
          "br",
          "hr",
          "table",
          "thead",
          "tbody",
          "tr",
          "th",
          "td",
          "span",
          "img",
        ],
        ALLOWED_ATTR: [
          "href",
          "target",
          "rel",
          "title",
          "src",
          "alt",
          "width",
          "height",
        ],
      });
      // Restore code blocks (renderCodeBlock output is already escaped/safe)
      codeBlocks.forEach(function (block, idx) {
        sanitized = sanitized.replace(
          "CODEBLOCK_PLACEHOLDER_" + idx + "_END",
          block,
        );
      });
      return sanitized;
    }
  } catch (e) {
    /* fallback to escaped text */
  }
  return esc(text).replace(/\n/g, "<br>");
}

// F2: Restore chat history from server on page load / persona switch
async function restoreChatHistory() {
  if (!S.persona) return;
  const sid = getChatSessionId();
  const container = document.getElementById("chat-messages");
  // Always reset DOM first to prevent previous persona's messages from lingering
  CHAT.messages = [];
  resetToWelcome();
  // Show loading skeleton while fetching history
  const skeletonHtml =
    '<div class="chat-msg assistant"><div class="chat-bubble" style="opacity:0.5"><div class="skeleton skeleton-text" style="width:80%;height:14px;margin-bottom:8px"></div><div class="skeleton skeleton-text" style="width:60%;height:14px;margin-bottom:8px"></div><div class="skeleton skeleton-text" style="width:40%;height:14px"></div></div></div>' +
    '<div class="chat-msg user" style="align-self:flex-end"><div class="chat-bubble" style="opacity:0.5"><div class="skeleton skeleton-text" style="width:70%;height:14px;margin-bottom:8px"></div><div class="skeleton skeleton-text" style="width:50%;height:14px"></div></div></div>';
  const skeletonDiv = document.createElement("div");
  skeletonDiv.id = "chat-history-skeleton";
  skeletonDiv.innerHTML = skeletonHtml;
  container.appendChild(skeletonDiv);
  try {
    const data = await api(
      "/api/chat/" +
        encodeURIComponent(S.persona) +
        "/sessions/" +
        encodeURIComponent(sid),
    );
    // Remove skeleton
    const skel = document.getElementById("chat-history-skeleton");
    if (skel) skel.remove();
    if (!data || !data.messages || data.messages.length === 0) return;
    // display_history_turns 件数分（最新N turns = N*2 messages）に制限
    const displayTurns = parseInt(
      document.getElementById("chat-display-history-turns")?.value || "20",
    );
    const maxMsgs = displayTurns * 2;
    const msgs = data.messages.slice(-maxMsgs);
    container.innerHTML = "";
    for (const msg of msgs) {
      // assistant の tool_calls は先にレンダリング（時系列順: tool_call → tool_result → assistant 応答）
      if (msg.role === "assistant" && msg.tool_calls?.length) {
        const msgContainer = document.getElementById("chat-messages");
        for (const tc of msg.tool_calls) {
          const div = document.createElement("div");
          div.className = "chat-tool-call done";
          let inputStr;
          try {
            inputStr = JSON.stringify(tc.input, null, 2);
          } catch (e) {
            inputStr = String(tc.input);
          }
          let resultStr;
          try {
            resultStr =
              typeof tc.result === "object"
                ? JSON.stringify(tc.result, null, 2)
                : String(tc.result);
          } catch (e) {
            resultStr = String(tc.result);
          }
          div.innerHTML =
            '<details><summary><i data-lucide="wrench"></i> <strong>' +
            esc(tc.name) +
            "</strong>" +
            '<span class="chat-tool-status"> <i data-lucide="check"></i> 完了</span></summary>' +
            '<pre class="chat-tool-detail">' +
            esc(inputStr) +
            "</pre>" +
            '<pre class="chat-tool-detail chat-tool-result-content">' +
            esc(resultStr) +
            "</pre></details>";
          msgContainer.appendChild(div);
        }
      }
      appendChatMessage(
        msg.role,
        msg.content,
        msg.time,
        msg.role === "assistant",
      );
      // user メッセージの tool_calls（存在すれば）は従来通り後
      if (msg.role !== "assistant" && msg.tool_calls?.length) {
        const msgContainer = document.getElementById("chat-messages");
        for (const tc of msg.tool_calls) {
          const div = document.createElement("div");
          div.className = "chat-tool-call done";
          let inputStr;
          try {
            inputStr = JSON.stringify(tc.input, null, 2);
          } catch (e) {
            inputStr = String(tc.input);
          }
          let resultStr;
          try {
            resultStr =
              typeof tc.result === "object"
                ? JSON.stringify(tc.result, null, 2)
                : String(tc.result);
          } catch (e) {
            resultStr = String(tc.result);
          }
          div.innerHTML =
            '<details><summary><i data-lucide="wrench"></i> <strong>' +
            esc(tc.name) +
            "</strong>" +
            '<span class="chat-tool-status"> <i data-lucide="check"></i> 完了</span></summary>' +
            '<pre class="chat-tool-detail">' +
            esc(inputStr) +
            "</pre>" +
            '<pre class="chat-tool-detail chat-tool-result-content">' +
            esc(resultStr) +
            "</pre></details>";
          msgContainer.appendChild(div);
        }
      }
    }
    setTimeout(() => {
      if (typeof lucide !== "undefined") lucide.createIcons();
    }, 50);
  } catch (_e) {
    // Session not found or API unavailable — start fresh
    const skel = document.getElementById("chat-history-skeleton");
    if (skel) skel.remove();
  }
}

// Housekeeping: manual trigger
async function runHousekeeping() {
  if (!S.persona) {
    toast("ペルソナを選択してください", "error");
    return;
  }
  const statusEl = document.getElementById("chat-housekeeping-status");
  if (statusEl)
    statusEl.innerHTML =
      '<span style="color:var(--text-muted)">整理中...</span>';
  try {
    const result = await api(
      "/api/chat/" + encodeURIComponent(S.persona) + "/housekeeping",
      {
        method: "POST",
      },
    );
    const g = (result.cancelled_goals || []).length;
    const i = (result.removed_items || []).length;
    const msg = `完了: goals ${g}件 / items ${i}件 を整理`;
    if (statusEl)
      statusEl.innerHTML = `<span style="color:var(--accent-green)">${msg}</span>`;
    toast(msg, "success");
  } catch (e) {
    if (statusEl)
      statusEl.innerHTML = `<span style="color:var(--accent-red)">失敗: ${e.message}</span>`;
    toast("整理失敗: " + e.message, "error");
  }
}

// F4: Cancel streaming
function chatCancel() {
  CHAT.streaming = false;
  if (CHAT.abortController) {
    CHAT.abortController.abort();
    CHAT.abortController = null;
  }
  const cancelBtn = document.getElementById("chat-cancel-btn");
  const sendBtn = document.getElementById("chat-send-btn");
  const statusEl = document.getElementById("chat-status");
  if (cancelBtn) cancelBtn.style.display = "none";
  if (sendBtn) sendBtn.style.display = "";
  if (statusEl) statusEl.textContent = "中断しました";
  removeTypingIndicator();
}

/* ── Export chat history ── */
function exportChatHistory() {
  const container = document.getElementById("chat-messages");
  if (!container) return;
  const bubbles = container.querySelectorAll(".chat-msg");
  if (bubbles.length === 0) {
    toast("エクスポートする会話がありません", "error");
    return;
  }
  const lines = [];
  const persona = S.persona;
  lines.push("# 会話ログ - " + persona);
  lines.push("> エクスポート日時: " + new Date().toISOString());
  lines.push("");
  bubbles.forEach((msg) => {
    const role = msg.classList.contains("user")
      ? '**<i data-lucide="user"></i> ユーザー**'
      : '**<i data-lucide="bot"></i> アシスタント**';
    const bubble = msg.querySelector(".chat-bubble");
    const time = msg.querySelector(".chat-time")?.textContent || "";
    const content = bubble ? bubble.textContent : "";
    lines.push("### " + role + " _" + time + "_");
    lines.push("");
    lines.push(content);
    lines.push("");
  });
  const blob = new Blob([lines.join("\n")], {
    type: "text/markdown;charset=utf-8",
  });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download =
    "chat-" + persona + "-" + new Date().toISOString().slice(0, 10) + ".md";
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
  toast("会話をエクスポートしました", "success");
}

/* ── Voice input (Web Speech API) ── */
let _voiceRecognition = null;
function toggleVoiceInput() {
  const btn = document.getElementById("chat-voice-btn");
  if (!("webkitSpeechRecognition" in window || "SpeechRecognition" in window)) {
    toast("お使いのブラウザは音声入力に対応していません", "error");
    return;
  }
  const SpeechRecognition =
    window.SpeechRecognition || window.webkitSpeechRecognition;
  if (_voiceRecognition) {
    _voiceRecognition.stop();
    _voiceRecognition = null;
    if (btn) {
      btn.innerHTML = '<i data-lucide="mic"></i>';
      btn.style.color = "";
    }
    return;
  }
  _voiceRecognition = new SpeechRecognition();
  _voiceRecognition.lang = "ja-JP";
  _voiceRecognition.interimResults = false;
  _voiceRecognition.continuous = false;
  if (btn) {
    btn.innerHTML = '<i data-lucide="circle-dot"></i>';
    btn.style.color = "var(--accent-red)";
  }
  _voiceRecognition.onresult = (event) => {
    const transcript = event.results[0][0].transcript;
    const inputEl = document.getElementById("chat-input");
    if (inputEl) {
      inputEl.value = (inputEl.value ? inputEl.value + " " : "") + transcript;
      inputEl.dispatchEvent(new Event("input"));
    }
    _voiceRecognition = null;
    if (btn) {
      btn.innerHTML = '<i data-lucide="mic"></i>';
      btn.style.color = "";
    }
  };
  _voiceRecognition.onerror = () => {
    toast("音声認識エラー", "error");
    _voiceRecognition = null;
    if (btn) {
      btn.innerHTML = '<i data-lucide="mic"></i>';
      btn.style.color = "";
    }
  };
  _voiceRecognition.onend = () => {
    if (btn) {
      btn.innerHTML = '<i data-lucide="mic"></i>';
      btn.style.color = "";
    }
  };
  _voiceRecognition.start();
}

function appendToolEvent(eventType, data) {
  const container = document.getElementById("chat-messages");

  if (eventType === "tool_call") {
    const div = document.createElement("div");
    div.className = "chat-tool-call";
    div.dataset.toolId = data.id || "";
    let inputStr;
    try {
      inputStr = JSON.stringify(data.input, null, 2);
    } catch (e) {
      inputStr = String(data.input);
    }
    div.innerHTML =
      '<details><summary><i data-lucide="wrench"></i> <strong>' +
      esc(data.name) +
      "</strong>" +
      '<span class="chat-tool-status">実行中...</span></summary>' +
      '<pre class="chat-tool-detail">' +
      esc(inputStr) +
      "</pre></details>";
    container.appendChild(div);
    container.scrollTop = container.scrollHeight;
    setTimeout(() => {
      if (typeof lucide !== "undefined") lucide.createIcons();
    }, 50);
    return div;
  } else if (eventType === "tool_result") {
    let resultStr;
    try {
      resultStr =
        typeof data.result === "object"
          ? JSON.stringify(data.result, null, 2)
          : String(data.result);
    } catch (e) {
      resultStr = String(data.result);
    }

    // ── Duplicate notification ──
    if (
      typeof data.result === "object" &&
      data.result &&
      data.result.status === "duplicate"
    ) {
      toast(
        "⚠️ " + (data.result.message || "類似の記憶が既に存在します"),
        "warning",
      );
    }

    // Find matching tool_call div by id and update it
    const callDiv = data.id
      ? container.querySelector('[data-tool-id="' + CSS.escape(data.id) + '"]')
      : null;
    if (callDiv) {
      const statusEl = callDiv.querySelector(".chat-tool-status");
      if (statusEl) statusEl.innerHTML = ' <i data-lucide="check"></i> 完了';
      const details = callDiv.querySelector("details");
      if (details) {
        const resultPre = document.createElement("pre");
        resultPre.className = "chat-tool-detail chat-tool-result-content";
        resultPre.textContent = resultStr;
        details.appendChild(resultPre);
      }
      callDiv.classList.add("done");
    } else {
      const div = document.createElement("div");
      div.className = "chat-tool-result";
      div.innerHTML =
        '<details><summary><i data-lucide="check"></i> <strong>' +
        esc(data.name) +
        "</strong></summary>" +
        '<pre class="chat-tool-detail chat-tool-result-content">' +
        esc(resultStr) +
        "</pre></details>";
      container.appendChild(div);
      container.scrollTop = container.scrollHeight;
      setTimeout(() => {
        if (typeof lucide !== "undefined") lucide.createIcons();
      }, 50);
      return div;
    }
  }
}

function showTypingIndicator() {
  const container = document.getElementById("chat-messages");
  const typing = document.createElement("div");
  typing.id = "chat-typing";
  typing.className = "chat-msg assistant";
  typing.innerHTML =
    '<div class="chat-bubble chat-typing"><span></span><span></span><span></span></div>';
  container.appendChild(typing);
  container.scrollTop = container.scrollHeight;
}

function removeTypingIndicator() {
  const el = document.getElementById("chat-typing");
  if (el) el.remove();
}

async function uploadAttachment(file) {
  if (!S.persona) {
    toast("ペルソナを選択してください", "error");
    return;
  }
  const formData = new FormData();
  formData.append("file", file);
  try {
    const res = await fetch(
      "/api/chat/" + encodeURIComponent(S.persona) + "/attachment/upload",
      {
        method: "POST",
        body: formData,
      },
    );
    if (!res.ok) throw new Error("HTTP " + res.status);
    const data = await res.json();
    data.file = file; // 元のFileオブジェクトを保持（Base64エンコード用）
    CHAT.attachments.push(data);
    renderAttachmentBadge(data);
  } catch (e) {
    toast("ファイルのアップロードに失敗しました: " + e.message, "error");
  }
}

function renderAttachmentBadge(att) {
  const area = document.getElementById("chat-attachments");
  if (!area) return;
  const badge = document.createElement("div");
  badge.className = "chat-attachment-badge";
  badge.dataset.filename = att.filename;

  const isImage = att.mime_type && att.mime_type.startsWith("image/");
  const isVideo = att.mime_type && att.mime_type.startsWith("video/");
  const isAudio = att.mime_type && att.mime_type.startsWith("audio/");

  if (isImage) {
    const img = document.createElement("img");
    img.className = "thumb";
    img.src = att.url;
    img.alt = att.filename;
    img.onclick = () => openMediaViewer(att.url, "image");
    badge.appendChild(img);
  } else if (isVideo) {
    const vid = document.createElement("video");
    vid.className = "thumb";
    vid.src = att.url;
    vid.muted = true;
    vid.onclick = () => openMediaViewer(att.url, "video");
    badge.appendChild(vid);
  } else if (isAudio) {
    const icon = document.createElement("span");
    icon.innerHTML = '<i data-lucide="volume-2"></i>';
    badge.appendChild(icon);
    badge.style.cursor = "pointer";
    badge.onclick = () => openMediaViewer(att.url, "audio", att.mime_type);
  } else {
    const icon = document.createElement("span");
    const ext = att.filename.split(".").pop().toLowerCase();
    if (ext === "pdf") {
      icon.innerHTML = '<i data-lucide="book"></i>';
      badge.appendChild(icon);
      badge.style.cursor = "pointer";
      badge.onclick = () => openMediaViewer(att.url, "pdf");
    } else {
      icon.innerHTML =
        ext === "zip" || ext === "tar" || ext === "gz"
          ? '<i data-lucide="package"></i>'
          : '<i data-lucide="file-text"></i>';
      badge.appendChild(icon);
    }
  }

  const nameSpan = document.createElement("span");
  nameSpan.className = "attach-name";
  nameSpan.textContent = att.filename;
  badge.appendChild(nameSpan);

  const removeBtn = document.createElement("button");
  removeBtn.className = "attach-remove";
  removeBtn.innerHTML = '<i data-lucide="x"></i>';
  removeBtn.onclick = () => {
    CHAT.attachments = CHAT.attachments.filter(
      (a) => a.filename !== att.filename,
    );
    badge.remove();
  };
  badge.appendChild(removeBtn);
  area.appendChild(badge);
}

function openMediaViewer(url, type, mimeType) {
  const overlay = document.getElementById("media-viewer-overlay");
  const inner = document.getElementById("media-viewer-inner");
  if (!overlay || !inner) return;
  inner.innerHTML = "";
  if (type === "image") {
    const img = document.createElement("img");
    img.src = url;
    inner.appendChild(img);
  } else if (type === "video") {
    const vid = document.createElement("video");
    vid.src = url;
    vid.controls = true;
    vid.autoplay = true;
    inner.appendChild(vid);
  } else if (type === "pdf") {
    inner.innerHTML =
      '<iframe src="' +
      url +
      '" width="100%" height="80vh" style="border:none;border-radius:8px;"></iframe>';
  } else if (type === "audio") {
    inner.innerHTML =
      '<audio controls autoplay style="max-width:90vw;"><source src="' +
      url +
      '" type="' +
      (mimeType || "audio/mpeg") +
      '"></audio>';
  } else {
    const vid = document.createElement("video");
    vid.src = url;
    vid.controls = true;
    vid.autoplay = true;
    inner.appendChild(vid);
  }
  overlay.classList.add("visible");
  // ESC to close
  const escHandler = (e) => {
    if (e.key === "Escape") {
      closeMediaViewer();
      document.removeEventListener("keydown", escHandler);
    }
  };
  document.addEventListener("keydown", escHandler);
}

function closeMediaViewer() {
  const overlay = document.getElementById("media-viewer-overlay");
  const inner = document.getElementById("media-viewer-inner");
  if (overlay) overlay.classList.remove("visible");
  if (inner) {
    const vid = inner.querySelector("video");
    if (vid) vid.pause();
    inner.innerHTML = "";
  }
}

/* ── Memory CRUD operations ── */
let _memEditKey = null;

function openMemEdit(card) {
  _memEditKey = card.dataset.key;
  document.getElementById("mem-edit-content").value =
    card.dataset.content || "";
  document.getElementById("mem-edit-importance").value =
    card.dataset.importance || "0.5";
  document.getElementById("mem-edit-tags").value = card.dataset.tags || "";
  document.getElementById("mem-edit-overlay").classList.add("show");
}

function closeMemEdit() {
  document.getElementById("mem-edit-overlay").classList.remove("show");
  _memEditKey = null;
}

async function saveMemEdit() {
  if (!_memEditKey || !S.persona) return;
  const content = document.getElementById("mem-edit-content").value.trim();
  const importance =
    parseFloat(document.getElementById("mem-edit-importance").value) || 0.5;
  const tagsStr = document.getElementById("mem-edit-tags").value.trim();
  const tags = tagsStr
    ? tagsStr
        .split(",")
        .map((t) => t.trim())
        .filter(Boolean)
    : [];
  if (!content) {
    toast("内容を入力してください", "error");
    return;
  }
  try {
    await api(
      "/api/memories/" +
        encodeURIComponent(S.persona) +
        "/" +
        encodeURIComponent(_memEditKey),
      {
        method: "PUT",
        body: JSON.stringify({ content, importance, tags }),
      },
    );
    closeMemEdit();
    toast("メモリを更新しました", "success");
    loadChatCommitments(); // refresh panels
  } catch (e) {
    toast("更新失敗: " + e.message, "error");
  }
}

async function deleteMemCard(key) {
  const k = key || _memEditKey;
  if (!k || !S.persona) return;
  showConfirm("このメモリを削除しますか？", async function () {
    try {
      await api(
        "/api/memories/" +
          encodeURIComponent(S.persona) +
          "/" +
          encodeURIComponent(k),
        {
          method: "DELETE",
        },
      );
      closeMemEdit();
      toast("メモリを削除しました", "success");
      loadChatCommitments(); // refresh panels
    } catch (e) {
      toast("削除失敗: " + e.message, "error");
    }
  });
}

async function completeGoal(key, content) {
  if (!S.persona) return;
  try {
    const resp = await api(
      "/api/chat/" + encodeURIComponent(S.persona) + "/tool",
      {
        method: "POST",
        body: JSON.stringify({
          tool: "goal_manage",
          input: { operation: "achieve", content, memory_key: key },
        }),
      },
    );
    if (resp.status === "ok") {
      toast("目標を達成しました: " + (resp.updated || content), "success");
      loadChatCommitments();
    } else {
      toast("完了失敗: " + (resp.message || ""), "error");
    }
  } catch (e) {
    toast("エラー: " + e.message, "error");
  }
}

/* ── Slash command handler ── */
const SLASH_COMMANDS = [
  { name: "/memory", desc: "記憶を作成", example: "/memory 今日は楽しかった" },
  {
    name: "/goal",
    desc: "目標を作成",
    example: "/goal プロジェクトを完成させる",
  },
  { name: "/code", desc: "コードを実行", example: '/code print("hello")' },
  { name: "/help", desc: "コマンド一覧を表示", example: "/help" },
  { name: "/search", desc: "記憶を検索", example: "/search 昨日の会話" },
  {
    name: "/browser",
    desc: "ブラウザ操作",
    example: "/browser open https://example.com",
  },
  { name: "/image", desc: "画像を生成", example: "/image 猫の写真" },
  {
    name: "/sandbox",
    desc: "サンドボックスで実行",
    example: "/sandbox python script.py",
  },
  {
    name: "/invoke_skill",
    desc: "スキルを呼び出す",
    example: "/invoke_skill skill_name",
  },
];

function showHelpCommand() {
  const timeStr = new Date().toLocaleTimeString("ja-JP", {
    hour: "2-digit",
    minute: "2-digit",
  });
  let msg = "**利用可能なコマンド**\n\n";
  SLASH_COMMANDS.forEach(function (cmd) {
    msg += "`" + cmd.name + "` — " + cmd.desc + "\n";
    msg += "  例: `" + cmd.example + "`\n\n";
  });
  msg += "**キーボードショートカット**\n\n";
  msg += "`Alt+1` ~ `Alt+0` — タブ切り替え\n";
  msg += "`Ctrl+F` — 検索\n";
  msg += "`Enter` — 送信 / `Shift+Enter` — 改行\n";
  appendChatMessage("assistant", msg, timeStr, true);
}

function showCommandPopup(inputEl) {
  hideCommandPopup();
  const val = inputEl.value.trim();
  if (!val.startsWith("/")) return;

  const query = val.toLowerCase();
  const matches = SLASH_COMMANDS.filter(function (cmd) {
    return cmd.name.startsWith(query);
  });
  if (matches.length === 0) return;

  const popup = document.createElement("div");
  popup.className = "chat-command-popup";
  popup.id = "chat-command-popup";

  matches.forEach(function (cmd, idx) {
    const item = document.createElement("div");
    item.className = "chat-command-item" + (idx === 0 ? " active" : "");
    item.innerHTML =
      '<span class="cmd-name">' +
      cmd.name +
      '</span><span class="cmd-desc">' +
      cmd.desc +
      "</span>";
    item.onclick = function () {
      inputEl.value = cmd.name + " ";
      inputEl.focus();
      hideCommandPopup();
      inputEl.dispatchEvent(new Event("input"));
    };
    popup.appendChild(item);
  });

  const inputArea = inputEl.closest("#chat-input-area") || inputEl.parentNode;
  inputArea.style.position = "relative";
  inputArea.appendChild(popup);
}

function hideCommandPopup() {
  const existing = document.getElementById("chat-command-popup");
  if (existing) existing.remove();
}

async function handleSlashCommand(toolName, toolInput) {
  const inputEl = document.getElementById("chat-input");
  const rawInput = inputEl.value.trim();
  inputEl.value = "";
  inputEl.style.height = "auto";
  const timeStr = new Date().toLocaleTimeString("ja-JP", {
    hour: "2-digit",
    minute: "2-digit",
  });
  appendChatMessage("user", rawInput, timeStr);
  showTypingIndicator();
  try {
    const resp = await api(
      "/api/chat/" + encodeURIComponent(S.persona) + "/tool",
      {
        method: "POST",
        body: JSON.stringify({ tool: toolName, input: toolInput }),
      },
    );
    removeTypingIndicator();
    const resultMsg =
      resp.status === "ok"
        ? '<i data-lucide="check"></i> ' +
          (resp.key
            ? "作成: " + resp.key
            : resp.updated
              ? "更新: " + resp.updated
              : "実行完了")
        : '<i data-lucide="x"></i> ' + (resp.message || resp.error || "エラー");
    appendChatMessage(
      "assistant",
      resultMsg,
      new Date().toLocaleTimeString("ja-JP", {
        hour: "2-digit",
        minute: "2-digit",
      }),
    );
    if (resp.status === "ok") toast(resultMsg, "success");
  } catch (ex) {
    removeTypingIndicator();
    appendChatMessage(
      "assistant",
      '<i data-lucide="x"></i> コマンド実行失敗: ' + ex.message,
      new Date().toLocaleTimeString("ja-JP", {
        hour: "2-digit",
        minute: "2-digit",
      }),
    );
    toast("コマンド失敗: " + ex.message, "error");
  }
}

async function chatSend(retry) {
  if (!S.persona) {
    toast("ペルソナを選択してください", "error");
    return;
  }
  if (CHAT.streaming) return;

  const inputEl = document.getElementById("chat-input");
  let rawInput;
  if (retry) {
    // Find last user message
    const msgs = document.querySelectorAll(".chat-msg.user .chat-bubble");
    rawInput = msgs.length > 0 ? msgs[msgs.length - 1].textContent : "";
    if (!rawInput) {
      toast("再送するメッセージがありません", "error");
      return;
    }
  } else {
    rawInput = inputEl.value.trim();
  }
  let message = rawInput;
  if (!message && CHAT.attachments.length === 0) return;
  if (!message) message = "";

  const sendBtn = document.getElementById("chat-send-btn");
  const cancelBtn = document.getElementById("chat-cancel-btn");
  const statusEl = document.getElementById("chat-status");

  // Base64エンコードされた画像を収集
  const images = [];
  // Append attachment references to message
  if (CHAT.attachments.length > 0) {
    const TEXT_EXTS = new Set([
      "txt",
      "csv",
      "json",
      "py",
      "js",
      "ts",
      "md",
      "yaml",
      "yml",
      "toml",
      "ini",
      "cfg",
      "sh",
      "bash",
      "html",
      "css",
      "xml",
      "log",
      "sql",
      "rs",
      "go",
      "java",
      "cpp",
      "c",
      "h",
    ]);
    const attachParts = [];
    for (const att of CHAT.attachments) {
      const ext = att.filename.split(".").pop().toLowerCase();
      const isText = TEXT_EXTS.has(ext);
      if (isText) {
        try {
          const res = await fetch(att.url);
          const content = await res.text();
          attachParts.push(
            "\n\n--- 添付: " + att.filename + " ---\n" + content + "\n---",
          );
        } catch (_e) {
          attachParts.push("\n[添付ファイル: " + att.workspace_path + "]");
        }
      } else if (
        att.mime_type &&
        att.mime_type.startsWith("image/") &&
        att.file
      ) {
        // FileReaderでBase64に変換
        const base64 = await new Promise((resolve, reject) => {
          const reader = new FileReader();
          reader.onload = () => resolve(reader.result.split(",")[1]); // data:URLプレフィックス除去
          reader.onerror = () => reject(new Error("画像読込失敗"));
          reader.readAsDataURL(att.file);
        });
        images.push({
          filename: att.filename,
          mime_type: att.mime_type,
          base64_data: base64,
        });
      } else {
        attachParts.push("\n[添付ファイル: " + att.workspace_path + "]");
      }
    }
    if (attachParts.length > 0) {
      message = message + attachParts.join("");
    }
  }

  inputEl.value = "";
  inputEl.style.height = "auto";
  // Save attachment info before clearing
  const attNames = CHAT.attachments.map((a) => a.filename);
  CHAT.attachments = [];
  const attArea = document.getElementById("chat-attachments");
  if (attArea) attArea.innerHTML = "";

  // Show user message with filename display
  const displayMsg =
    rawInput ||
    (attNames.length > 0
      ? '<i data-lucide="paperclip"></i> ' + attNames.join(", ")
      : "");
  const timeStr = new Date().toLocaleTimeString("ja-JP", {
    hour: "2-digit",
    minute: "2-digit",
  });
  appendChatMessage("user", displayMsg, timeStr);
  showTypingIndicator();

  CHAT.streaming = true;
  CHAT.abortController = new AbortController();
  sendBtn.style.display = "none";
  if (cancelBtn) cancelBtn.style.display = "";
  statusEl.textContent = "応答中...";

  const sessionId = getChatSessionId();
  let assistantText = "";
  let assistantBubble = null;
  let assistantDiv = null;

  try {
    const response = await fetch("/api/chat/" + encodeURIComponent(S.persona), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        message: message,
        session_id: sessionId,
        images: images.length > 0 ? images : undefined,
        debug: document.getElementById("chat-debug-mode")?.checked || false,
      }),
      signal: CHAT.abortController.signal,
    });

    if (!response.ok) {
      throw new Error("HTTP " + response.status);
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    let streamDone = false;

    removeTypingIndicator();

    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });

      const lines = buffer.split("\n");
      buffer = lines.pop(); // keep incomplete line

      for (const line of lines) {
        if (!line.startsWith("data: ")) continue;
        let evt;
        try {
          evt = JSON.parse(line.slice(6));
        } catch {
          continue;
        }

        if (evt.type === "text_delta") {
          if (!assistantDiv) {
            const container = document.getElementById("chat-messages");
            assistantDiv = document.createElement("div");
            assistantDiv.className = "chat-msg assistant";
            assistantBubble = document.createElement("div");
            assistantBubble.className = "chat-bubble";
            const timeDiv = document.createElement("div");
            timeDiv.className = "chat-time";
            timeDiv.textContent = new Date().toLocaleTimeString("ja-JP", {
              hour: "2-digit",
              minute: "2-digit",
            });
            assistantDiv.appendChild(assistantBubble);
            assistantDiv.appendChild(timeDiv);
            container.appendChild(assistantDiv);
          }
          assistantText += evt.content;
          // F1: stream as plain text for performance; render markdown on done
          assistantBubble.textContent = assistantText;
          document.getElementById("chat-messages").scrollTop =
            document.getElementById("chat-messages").scrollHeight;
        } else if (evt.type === "tool_call") {
          const sbEnabled = document.getElementById(
            "chat-sandbox-enabled",
          )?.checked;
          if (FILE_OP_TOOLS.has(evt.name) && sbEnabled) {
            handleFileToolCall(evt);
          } else {
            appendToolEvent("tool_call", evt);
          }
          statusEl.innerHTML =
            '<i data-lucide="wrench"></i> ' + esc(evt.name) + " を実行中...";
        } else if (evt.type === "tool_result") {
          const sbEnabled = document.getElementById(
            "chat-sandbox-enabled",
          )?.checked;
          if (!FILE_OP_TOOLS.has(evt.name) || !sbEnabled) {
            appendToolEvent("tool_result", evt);
          }
          statusEl.textContent = "応答中...";
        } else if (evt.type === "memory_activity") {
          updateMemoryPanel(evt.retrieved, evt.saved, undefined);
          setTimeout(() => loadChatCommitments(), 300);
        } else if (evt.type === "inventory_update") {
          updateEquipmentPanel(evt.update);
        } else if (evt.type === "reflection_start") {
          showReflectionStart();
        } else if (evt.type === "reflection_done") {
          updateReflectionPanel(evt.insights);
        } else if (evt.type === "session_summarized") {
          showSessionSummarized(evt.summary);
        } else if (evt.type === "context_compressed") {
          showContextCompressed(evt);
        } else if (evt.type === "image_gen_start") {
          showImageGenSpinner(evt);
        } else if (evt.type === "image_gen_result") {
          showImageGenResult(evt);
        } else if (evt.type === "error") {
          removeTypingIndicator();
          toast("エラー: " + evt.message, "error");
          statusEl.textContent = "";
          streamDone = true;
          break;
        } else if (evt.type === "debug_info") {
          console.debug("[debug_info received]", Object.keys(evt));
          renderDebugPanel(assistantDiv, evt);
        } else if (evt.type === "done") {
          // F1: final Markdown render
          if (assistantBubble && assistantText) {
            assistantBubble.innerHTML = safeMarkdown(assistantText);
            // メッセージ内の画像にクリックイベント追加
            assistantBubble.querySelectorAll("img").forEach((img) => {
              img.style.cssText =
                "max-width:100%;border-radius:8px;cursor:pointer;margin:8px 0;";
              img.addEventListener("click", () =>
                openMediaViewer(img.src, "image"),
              );
            });
          }
          statusEl.textContent = "";
        }
      }
      if (streamDone) break;
    }
  } catch (e) {
    removeTypingIndicator();
    if (e.name !== "AbortError") {
      toast("送信失敗: " + e.message, "error");
    }
    statusEl.textContent = "";
  } finally {
    CHAT.streaming = false;
    CHAT.abortController = null;
    sendBtn.style.display = "";
    if (cancelBtn) cancelBtn.style.display = "none";
    inputEl.focus();
    // Fallback: render markdown if stream ended without 'done' event
    if (
      assistantBubble &&
      assistantText &&
      assistantBubble.textContent === assistantText
    ) {
      assistantBubble.innerHTML = safeMarkdown(assistantText);
      assistantBubble.querySelectorAll("img").forEach((img) => {
        img.style.cssText =
          "max-width:100%;border-radius:8px;cursor:pointer;margin:8px 0;";
        img.addEventListener("click", () => openMediaViewer(img.src, "image"));
      });
    }
  }
}

// Chat input auto-resize and keyboard handler
document.addEventListener("DOMContentLoaded", () => {
  const input = document.getElementById("chat-input");
  if (!input) return;
  input.addEventListener("keydown", (e) => {
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
      } else if (val.startsWith("/code ") && S.persona) {
        handleSlashCommand("sandbox", {
          code: val.slice(6).trim(),
          language: "python",
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
  });
  input.addEventListener("input", () => {
    input.style.height = "auto";
    input.style.height = Math.min(input.scrollHeight, 160) + "px";
    // Show command popup when typing /
    if (input.value.startsWith("/")) {
      showCommandPopup(input);
    } else {
      hideCommandPopup();
    }
  });
  // File drag-and-drop on chat input
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
});

// Reload chat config when persona changes
window.__chatPersonaWatcher = setInterval(() => {
  const sel = document.getElementById("persona-select");
  if (!sel) return;
  if (!sel._chatBound) {
    sel._chatBound = true;
    sel.addEventListener("change", () => {
      // DOM reset + history restore is handled by base.py's loadTab() → loadChat() → restoreChatHistory()
      // Do NOT call clearChatHistory() here — it would destroy the session ID and break history
      if (S.tab === "chat") {
        loadChatConfig();
        loadChatCommitments();
      }
    });
    clearInterval(window.__chatPersonaWatcher);
  }
}, 500);

const FILE_OP_TOOLS = new Set([
  "edit",
  "create",
  "view",
  "bash",
  "powershell",
  "str_replace_editor",
  "write_file",
  "read_file",
  "delete_file",
  "list_files",
  "glob",
  "grep",
]);

function updateEquipmentPanel(update) {
  const list = document.getElementById("memory-equipment-list");
  if (!list) return;
  if (!update) return;

  // Build equipment display from update data
  const equipped = update.equip || {};
  const unequipped = update.unequip || [];
  const added = update.add_items || [];

  let html = "";
  const entries = Object.entries(equipped).filter(function (e) {
    return e[1] != null && e[1] !== "";
  });
  if (entries.length > 0) {
    html +=
      '<div style="font-size:0.75rem;font-weight:600;color:var(--text-muted);margin-bottom:4px;"><i data-lucide="shield" style="width:12px;height:12px;vertical-align:middle;margin-right:4px;"></i>装備中</div>';
    for (const [slot, item] of entries) {
      const slotIcon =
        {
          top: "shirt",
          bottom: "footprints",
          shoes: "footprints",
          outer: "jacket",
          accessories: "gem",
          head: "crown",
        }[slot] || "circle";
      const slotLabel =
        {
          top: "上",
          bottom: "下",
          shoes: "靴",
          outer: "アウター",
          accessories: "アクセ",
          head: "頭",
        }[slot] || slot;
      html +=
        '<div style="font-size:0.73rem;padding:2px 0;display:flex;justify-content:space-between;align-items:center;">' +
        '<span style="display:inline-flex;align-items:center;gap:4px;"><i data-lucide="' +
        slotIcon +
        '" style="width:11px;height:11px;opacity:0.7;"></i>' +
        slotLabel +
        "</span><span>" +
        esc(String(item)) +
        "</span></div>";
    }
  }
  if (unequipped.length > 0) {
    html +=
      '<div style="font-size:0.7rem;opacity:0.6;margin-top:4px;">外した: ' +
      unequipped
        .map(function (i) {
          return esc(String(i));
        })
        .join(", ") +
      "</div>";
  }
  if (added.length > 0) {
    html +=
      '<div style="font-size:0.7rem;opacity:0.6;margin-top:2px;">追加: ' +
      added
        .map(function (i) {
          return esc(String(i));
        })
        .join(", ") +
      "</div>";
  }

  if (html) {
    list.innerHTML = html;
    // Re-render Lucide icons in the equipment panel
    setTimeout(() => {
      if (typeof lucide !== "undefined") lucide.createIcons();
    }, 10);
  }
}

function handleFileToolCall(evt) {
  const icons = {
    edit: '<i data-lucide="pencil"></i>',
    create: '<i data-lucide="edit-3"></i>',
    view: '<i data-lucide="eye"></i>',
    bash: '<i data-lucide="settings"></i>',
    powershell: '<i data-lucide="settings"></i>',
    str_replace_editor: '<i data-lucide="pencil"></i>',
    delete_file: '<i data-lucide="trash-2"></i>',
    list_files: '<i data-lucide="folder-open"></i>',
    write_file: '<i data-lucide="edit-3"></i>',
    read_file: '<i data-lucide="eye"></i>',
    glob: '<i data-lucide="search"></i>',
    grep: '<i data-lucide="search"></i>',
  };
  const icon = icons[evt.name] || '<i data-lucide="wrench"></i>';
  const detail =
    evt.input?.path ||
    evt.input?.file_path ||
    evt.input?.command ||
    evt.input?.pattern ||
    evt.input?.glob ||
    "";
  sandboxLog(
    icon +
      " " +
      evt.name +
      (detail ? ": " + String(detail).substring(0, 60) : ""),
    "system",
  );
}

function sandboxLog(text, type = "") {
  if (
    typeof isCodingAgentOpen === "function" &&
    isCodingAgentOpen() &&
    typeof caAppendOutput === "function"
  ) {
    caAppendOutput(text + "\n", type === "stderr" ? "stderr" : "stdout");
  }
}

function onSandboxEnabledChange() {
  const enabled = document.getElementById("chat-sandbox-enabled")?.checked;
  if (
    !enabled &&
    typeof isCodingAgentOpen === "function" &&
    isCodingAgentOpen()
  ) {
    closeCodingAgent();
  }
}

/* ── Sandbox: Add artifact to tab ── */
function sandboxAddArtifact(base64png, label) {
  const list = document.getElementById("sandbox-artifacts-list");
  if (!list) return;
  // Clear placeholder
  const placeholder = list.querySelector('div[style*="text-muted"]');
  if (placeholder) placeholder.remove();

  const thumb = document.createElement("div");
  thumb.className = "artifact-thumb";
  const img = document.createElement("img");
  img.src = "data:image/png;base64," + base64png;
  img.alt = label || "artifact";
  img.onclick = () => window.open(img.src, "_blank");
  const lbl = document.createElement("div");
  lbl.className = "artifact-thumb-label";
  lbl.textContent = label || new Date().toLocaleTimeString();
  thumb.appendChild(img);
  thumb.appendChild(lbl);
  list.appendChild(thumb);
}

/* ── Code block Run button ── */
async function sandboxRunBlock(code, language, resultEl, runBtn) {
  if (!S.persona) return;
  if (typeof openCodingAgent === "function") {
    openCodingAgent({ code, language });
    if (resultEl) {
      resultEl.className = "hljs-run-result stdout";
      resultEl.textContent = "▶ Coding Agent で開きました";
      resultEl.style.display = "block";
    }
    if (runBtn) runBtn.textContent = "▶ Run";
    return;
  }
  runBtn.disabled = true;
  runBtn.innerHTML = '<i data-lucide="clock"></i>';
  resultEl.className = "hljs-run-result running";
  resultEl.textContent = "実行中...";
  resultEl.style.display = "block";
  try {
    const resp = await api(
      "/api/chat/" + encodeURIComponent(S.persona) + "/sandbox/execute",
      {
        method: "POST",
        body: JSON.stringify({ code, language }),
      },
    );
    const out = (resp.stdout || "").trim();
    const err = (resp.stderr || "").trim();
    if (err) {
      resultEl.className = "hljs-run-result stderr";
      resultEl.textContent = err;
    } else {
      resultEl.className = "hljs-run-result stdout";
      resultEl.textContent = out || "(出力なし)";
    }
    if (resp.artifacts && resp.artifacts.length > 0) {
      resp.artifacts.forEach((a, i) => {
        const img = document.createElement("img");
        img.src = "data:image/png;base64," + a;
        img.className = "hljs-artifact-img";
        img.title = "クリックで拡大";
        img.onclick = () => window.open(img.src, "_blank");
        resultEl.parentNode.insertBefore(img, resultEl.nextSibling);
        sandboxAddArtifact(a, "chart-" + new Date().toLocaleTimeString());
      });
    }
    sandboxLog(
      "▶ [" +
        language +
        "] " +
        code.split("\n")[0].substring(0, 60) +
        (code.includes("\n") ? "..." : ""),
      "system",
    );
    if (out) out.split("\n").forEach((l) => l && sandboxLog(l, "success"));
    if (err) err.split("\n").forEach((l) => l && sandboxLog(l, "stderr"));
  } catch (ex) {
    resultEl.className = "hljs-run-result stderr";
    resultEl.textContent = "Error: " + ex.message;
  } finally {
    runBtn.disabled = false;
    runBtn.textContent = "▶ Run";
  }
}

/* ── Image Generation ── */
let _imageGenSpinnerId = null;

function showImageGenSpinner(evt) {
  const container = findChatLogContainer();
  if (!container) return;

  const spinner = document.createElement("div");
  spinner.className = "chat-image-gen-spinner";
  spinner.innerHTML = '<div class="spinner"></div> ';
  spinner.innerHTML +=
    "画像を生成中... (" + esc(evt.provider) + ", " + evt.n + "枚)";

  _imageGenSpinnerId = "image-gen-spinner-" + Date.now();
  spinner.id = _imageGenSpinnerId;
  container.appendChild(spinner);

  scrollToBottom(container);
}

function showImageGenResult(evt) {
  const container = findChatLogContainer();
  if (!container) return;

  // スピナーを削除
  if (_imageGenSpinnerId) {
    const spinner = document.getElementById(_imageGenSpinnerId);
    if (spinner) spinner.remove();
    _imageGenSpinnerId = null;
  }

  if (!evt.images || !evt.images.length) return;

  evt.images.forEach(function (img) {
    const card = document.createElement("div");
    card.className = "chat-image-gen-card";

    const imgEl = document.createElement("img");
    imgEl.src = "data:image/png;base64," + img.base64;
    imgEl.alt = img.revised_prompt || "生成画像";
    imgEl.title = img.revised_prompt || "";
    imgEl.onclick = function () {
      if (typeof openMediaViewer === "function") {
        openMediaViewer(imgEl.src, "image");
      } else {
        window.open(imgEl.src, "_blank");
      }
    };

    const meta = document.createElement("div");
    meta.className = "image-gen-meta";

    // 改訂プロンプトがあれば表示（先頭80文字）
    const rp = img.revised_prompt || "";
    if (rp) {
      const promptSpan = document.createElement("span");
      promptSpan.textContent =
        rp.length > 80 ? rp.substring(0, 80) + "..." : rp;
      promptSpan.style.fontStyle = "italic";
      meta.appendChild(promptSpan);
    }

    const sizeSpan = document.createElement("span");
    sizeSpan.textContent = evt.provider + " · " + (img.size || "");
    meta.appendChild(sizeSpan);

    card.appendChild(imgEl);
    card.appendChild(meta);
    container.appendChild(card);
  });

  scrollToBottom(container);
}

function findChatLogContainer() {
  const chatLog = document.getElementById("chat-messages");
  if (chatLog) {
    return chatLog;
  }
  return document.getElementById("chat-log");
}

function scrollToBottom(container) {
  if (!container) return;
  container.scrollTop = container.scrollHeight;
}

/* ── Markdown code block rendering with syntax highlighting ── */
function renderCodeBlock(lang, code) {
  const sandboxEnabled = document.getElementById(
    "chat-sandbox-enabled",
  )?.checked;
  const runnable =
    sandboxEnabled && lang && lang !== "text" && lang !== "output";
  const escaped = esc(code);
  // Try highlight.js
  let highlighted = escaped;
  try {
    if (typeof hljs !== "undefined" && lang && hljs.getLanguage(lang)) {
      highlighted = hljs.highlight(code, { language: lang }).value;
    } else if (typeof hljs !== "undefined") {
      highlighted = hljs.highlightAuto(code).value;
    }
  } catch (_) {
    /* fallback to plain */
  }

  const uid = "codeblock-" + Math.random().toString(36).slice(2);
  // Build the wrapper HTML without inline onclick
  const wrapper = document.createElement("div");
  wrapper.className = "hljs-block-wrapper";
  wrapper.innerHTML =
    '<div class="hljs-block-header">' +
    '<span class="hljs-lang-badge">' +
    esc(lang || "") +
    "</span>" +
    '<div class="hljs-block-actions">' +
    '<button class="hljs-copy-btn"><i data-lucide="clipboard-list"></i> Copy</button>' +
    (runnable
      ? '<button class="hljs-run-btn"><i data-lucide="play"></i> Run</button>'
      : "") +
    "</div>" +
    "</div>" +
    '<pre style="margin:0;padding:8px 10px;background:#0d1117;overflow-x:auto;"><code class="hljs language-' +
    esc(lang || "") +
    '">' +
    highlighted +
    "</code></pre>" +
    '<div class="hljs-run-result" style="display:none;"></div>';

  // Attach event listeners via addEventListener (no inline onclick)
  const copyBtn = wrapper.querySelector(".hljs-copy-btn");
  if (copyBtn) {
    copyBtn.addEventListener("click", function () {
      navigator.clipboard.writeText(code).then(function () {
        toast("コピーしました", "success");
      });
    });
  }
  if (runnable) {
    const runBtn = wrapper.querySelector(".hljs-run-btn");
    const resultEl = wrapper.querySelector(".hljs-run-result");
    if (runBtn && resultEl) {
      runBtn.addEventListener("click", function () {
        sandboxRunBlock(code, lang || "python", resultEl, runBtn);
      });
    }
  }

  return wrapper.outerHTML;
}

/* =================================================================
   TB07: PERSONA PORTRAIT
   ================================================================= */
const EMOTION_COLORS_PORTRAIT = {
  joy: "#fbbf24",
  sadness: "#60a5fa",
  anger: "#f87171",
  fear: "#a78bfa",
  surprise: "#fb923c",
  disgust: "#6ee7b7",
  love: "#ec4899",
  neutral: "#94a3b8",
  anticipation: "#F59E0B",
  trust: "#10B981",
  anxiety: "#8B5CF6",
  excitement: "#EC4899",
  frustration: "#DC2626",
  nostalgia: "#92400E",
  pride: "#F97316",
  shame: "#BE185D",
  guilt: "#78350F",
  loneliness: "#1E3A5F",
  contentment: "#065F46",
  curiosity: "#0891B2",
  awe: "#5B21B6",
  relief: "#34D399",
  happiness: "#fbbf24",
  calm: "#2dd4bf",
};

async function loadPortrait() {
  if (!S.persona) return;
  const container = document.getElementById("portrait-container");
  const img = document.getElementById("portrait-img");
  const placeholder = document.getElementById("portrait-placeholder");
  const status = document.getElementById("portrait-status");
  if (!container || !img || !placeholder || !status) return;

  status.textContent = "";
  status.className = "";

  try {
    const data = await api("/api/portrait/" + encodeURIComponent(S.persona));
    if (data.image_base64) {
      setPortraitImage(data.image_base64, data.emotion);
    } else if (data.fallback_emoji) {
      placeholder.textContent = data.fallback_emoji;
      placeholder.style.fontSize = "2.5rem";
    }
  } catch (_e) {
    // Portrait API unavailable — keep default placeholder
  }
}

function setPortraitImage(base64, emotion) {
  const container = document.getElementById("portrait-container");
  const img = document.getElementById("portrait-img");
  const placeholder = document.getElementById("portrait-placeholder");
  const status = document.getElementById("portrait-status");
  if (!container || !img) return;

  img.src = "data:image/png;base64," + base64;
  img.style.display = "block";
  if (placeholder) placeholder.style.display = "none";
  img.classList.remove("fade-in");
  void img.offsetWidth; // trigger reflow
  img.classList.add("fade-in");
  if (status) {
    status.textContent = "";
    status.className = "";
  }

  // Set emotion border color
  if (emotion && EMOTION_COLORS_PORTRAIT[emotion]) {
    container.classList.add("has-emotion");
    container.style.setProperty(
      "--portrait-emotion-color",
      EMOTION_COLORS_PORTRAIT[emotion],
    );
  } else {
    container.classList.remove("has-emotion");
    container.style.removeProperty("--portrait-emotion-color");
  }
}

function onPortraitClick() {
  const img = document.getElementById("portrait-img");
  if (img && img.style.display !== "none" && img.src) {
    openMediaViewer(img.src, "image");
  }
}

// SSE listener for portrait.generated events
window.addEventListener("portrait-generated", function (e) {
  try {
    const data = typeof e.detail === "string" ? JSON.parse(e.detail) : e.detail;
    if (data.image_base64) {
      setPortraitImage(data.image_base64, data.emotion);
      toast("🎨 ポートレートが更新されました", "info");
    }
  } catch (_err) {
    /* ignore parse errors */
  }
});

/* =================================================================
   TE04: TTS AUDIO PLAYBACK
   ================================================================= */
let _ttsAbortController = null;

async function playTts(btn, text) {
  if (!S.persona || !text) return;
  // If already playing, stop
  if (btn.classList.contains("playing")) {
    btn.classList.remove("playing");
    btn.innerHTML = '<i data-lucide="volume-2"></i>';
    if (typeof lucide !== "undefined") lucide.createIcons();
    if (_ttsAbortController) {
      _ttsAbortController.abort();
      _ttsAbortController = null;
    }
    return;
  }

  // Strip markdown-like formatting for TTS
  const plainText = text
    .replace(/```[\s\S]*?```/g, "コードブロック")
    .replace(/`([^`]+)`/g, "$1")
    .replace(/[*_~>#-]/g, "")
    .replace(/\[([^\]]+)\]\([^)]+\)/g, "$1")
    .trim();
  if (!plainText) return;

  btn.innerHTML = '<span class="tts-spinner"></span>';
  btn.disabled = true;

  try {
    const resp = await api("/api/tts/" + encodeURIComponent(S.persona), {
      method: "POST",
      body: JSON.stringify({ text: plainText }),
    });
    if (resp.ok && resp.audio_base64) {
      btn.classList.add("playing");
      btn.innerHTML = '<i data-lucide="volume-2"></i>';
      btn.disabled = false;
      if (typeof lucide !== "undefined") lucide.createIcons();

      const audioUrl =
        "data:audio/" + (resp.format || "wav") + ";base64," + resp.audio_base64;
      const audio = new Audio(audioUrl);
      audio.onended = function () {
        btn.classList.remove("playing");
        btn.innerHTML = '<i data-lucide="volume-2"></i>';
        if (typeof lucide !== "undefined") lucide.createIcons();
      };
      audio.onerror = function () {
        btn.classList.remove("playing");
        btn.innerHTML = '<i data-lucide="volume-2"></i>';
        if (typeof lucide !== "undefined") lucide.createIcons();
        console.error("[TTS] Audio playback error");
      };
      audio.play().catch(function (err) {
        console.error("[TTS] Play failed:", err);
        btn.classList.remove("playing");
        btn.innerHTML = '<i data-lucide="volume-2"></i>';
        if (typeof lucide !== "undefined") lucide.createIcons();
      });
    } else {
      console.warn("[TTS] Synthesis failed:", resp.error || "unknown");
      btn.innerHTML = '<i data-lucide="volume-2"></i>';
      btn.disabled = false;
      if (typeof lucide !== "undefined") lucide.createIcons();
    }
  } catch (e) {
    console.error("[TTS] Request error:", e.message);
    btn.innerHTML = '<i data-lucide="volume-2"></i>';
    btn.disabled = false;
    if (typeof lucide !== "undefined") lucide.createIcons();
  }
}
