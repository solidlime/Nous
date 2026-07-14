/* =================================================================
   STATE
   ================================================================= */
const S = {
  persona: null,
  tab: localStorage.getItem("mmcp-tab") || "overview",
  charts: {},
  mem: { page: 1, tag: "", q: "", perPage: 20 },
  statusPoll: null,
  dashCache: null,
  initTime: Date.now(),
};

const CHART_COLORS = [
  "#a78bfa",
  "#f472b6",
  "#60a5fa",
  "#34d399",
  "#fbbf24",
  "#fb923c",
  "#f87171",
  "#2dd4bf",
  "#a3e635",
  "#e879f9",
];
const EMOTION_COLORS = {
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

const EMOTION_BAR_COLORS = {
  joy: "linear-gradient(90deg,#fbbf24,#fcd34d)",
  sadness: "linear-gradient(90deg,#60a5fa,#93c5fd)",
  anger: "linear-gradient(90deg,#ef4444,#fca5a5)",
  fear: "linear-gradient(90deg,#a855f7,#c4b5fd)",
  disgust: "linear-gradient(90deg,#22c55e,#86efac)",
  surprise: "linear-gradient(90deg,#ec4899,#f9a8d4)",
  love: "linear-gradient(90deg,#fb7185,#fda4af)",
  trust: "linear-gradient(90deg,#14b8a6,#5eead4)",
  anticipation: "linear-gradient(90deg,#f97316,#fdba74)",
  curiosity: "linear-gradient(90deg,#6366f1,#a5b4fc)",
  neutral: "linear-gradient(90deg,#9ca3af,#d1d5db)",
  excitement: "linear-gradient(90deg,#f59e0b,#fbbf24)",
  pride: "linear-gradient(90deg,#818cf8,#a5b4fc)",
  shame: "linear-gradient(90deg,#fb7185,#fda4af)",
  nostalgia: "linear-gradient(90deg,#a78bfa,#c4b5fd)",
  anxiety: "linear-gradient(90deg,#f87171,#fca5a5)",
  contentment: "linear-gradient(90deg,#86efac,#bbf7d0)",
  frustration: "linear-gradient(90deg,#fb923c,#fdba74)",
  loneliness: "linear-gradient(90deg,#94a3b8,#cbd5e1)",
  awe: "linear-gradient(90deg,#c084fc,#e9d5ff)",
  relief: "linear-gradient(90deg,#6ee7b7,#a7f3d0)",
};

const BODY_BAR_COLORS = {
  fatigue: "linear-gradient(90deg,#f87171,#fca5a5)",
  warmth: "linear-gradient(90deg,#f9a8d4,#fda4af)",
  arousal: "linear-gradient(90deg,#a78bfa,#c4b5fd)",
  heart_rate: "linear-gradient(90deg,#ef4444,#fca5a5)",
  pain: "linear-gradient(90deg,#f59e0b,#fcd34d)",
};

const BODY_LABELS = {
  fatigue: '<i data-lucide="flame"></i> Fatigue',
  warmth: '<i data-lucide="flower"></i> Warmth',
  arousal: '<i data-lucide="zap"></i> Arousal',
  heart_rate: '<i data-lucide="heart-pulse"></i> Heart',
  pain: '<i data-lucide="activity"></i> Pain',
};

function renderBodyStateBars(bodyState) {
  if (!bodyState) return "";
  const keys = Object.keys(bodyState).filter(
    (k) => BODY_LABELS[k] && bodyState[k] != null,
  );
  if (keys.length === 0) return "";
  let html =
    '<div class="mem-modal-row"><span class="mem-modal-key">Body</span><span style="display:flex;flex-direction:column;gap:6px;flex:1">';
  keys.forEach(function (k) {
    const val = bodyState[k];
    const color = BODY_BAR_COLORS[k] || BODY_BAR_COLORS.fatigue;
    const label = BODY_LABELS[k];
    const pct = Math.round(val * 100);
    html += '<div style="display:flex;align-items:center;gap:8px">';
    html +=
      '<span style="font-size:0.75rem;color:var(--text-muted);min-width:70px">' +
      label +
      "</span>";
    html +=
      '<div style="flex:1;height:5px;background:rgba(255,255,255,0.1);border-radius:3px;overflow:hidden">';
    html +=
      '<div style="height:100%;width:' +
      pct +
      "%;background:" +
      color +
      ';border-radius:3px"></div>';
    html += "</div>";
    html +=
      '<span style="font-size:0.75rem;color:var(--text-muted);min-width:32px;text-align:right">' +
      pct +
      "%</span>";
    html += "</div>";
  });
  html += "</span></div>";
  return html;
}

function renderEmotionBars(emotion, emotion_intensity) {
  if (!emotion) return "";
  const pct = Math.round((emotion_intensity || 0) * 100);
  if (pct <= 0) return "";
  const color = EMOTION_BAR_COLORS[emotion] || EMOTION_BAR_COLORS.neutral;
  return (
    '<div class="mem-modal-row"><span class="mem-modal-key">Emotion</span><span style="display:flex;flex-direction:column;gap:6px;flex:1">' +
    '<div style="display:flex;align-items:center;gap:8px">' +
    '<span style="font-size:0.75rem;color:var(--text-muted);min-width:70px;text-transform:capitalize">' +
    esc(emotion) +
    "</span>" +
    '<div style="flex:1;height:5px;background:rgba(255,255,255,0.1);border-radius:3px;overflow:hidden">' +
    '<div style="height:100%;width:' +
    pct +
    "%;background:" +
    color +
    ';border-radius:3px"></div>' +
    "</div>" +
    '<span style="font-size:0.75rem;color:var(--text-muted);min-width:32px;text-align:right">' +
    pct +
    "%</span>" +
    "</div></span></div>"
  );
}

/* Compact emotion badges for list/card views */
function renderEmotionBadges(emotion, emotion_intensity) {
  if (!emotion) return "";
  const pct = Math.round((emotion_intensity || 0) * 100);
  const color = EMOTION_COLORS[emotion] || "#94a3b8";
  return (
    '<span style="font-size:0.65rem;display:inline-block;padding:1px 5px;border-radius:3px;background:' +
    color +
    "22;color:" +
    color +
    ";border:1px solid " +
    color +
    '44;margin-right:3px">' +
    esc(emotion) +
    " " +
    pct +
    "%</span>"
  );
}

/* Compact body state indicator for list/card views - shows all 5 metrics */
function renderBodyStateCompact(bodyState) {
  if (!bodyState) return "";
  const keys = Object.keys(bodyState).filter(function (k) {
    return BODY_LABELS[k] && bodyState[k] != null && bodyState[k] > 0;
  });
  if (keys.length === 0) return "";
  let html = '<span style="font-size:0.65rem;color:var(--text-muted)">';
  keys.forEach(function (k) {
    const val = bodyState[k];
    const pct = Math.round(val * 100);
    const emoji = BODY_LABELS[k].split(" ")[0];
    html += emoji + pct + "% ";
  });
  html += "</span>";
  return html;
}

/* =================================================================
   UTILITIES
   ================================================================= */
function esc(s) {
  if (!s) return "";
  const d = document.createElement("div");
  d.textContent = String(s);
  return d.innerHTML.replace(/"/g, "&quot;");
}
function truncate(s, n) {
  return s && s.length > n ? s.slice(0, n) + "..." : s || "";
}
function relativeTime(iso) {
  if (!iso) return "--";
  const diff = Date.now() - new Date(iso).getTime();
  if (diff < 0) return "just now";
  if (diff < 60000) return Math.floor(diff / 1000) + "s ago";
  if (diff < 3600000) return Math.floor(diff / 60000) + "m ago";
  if (diff < 86400000) return Math.floor(diff / 3600000) + "h ago";
  return Math.floor(diff / 86400000) + "d ago";
}
function fmtDate(iso) {
  if (!iso) return "--";
  return new Date(iso).toLocaleDateString("ja-JP", {
    month: "short",
    day: "numeric",
  });
}

/* Persona storage helpers — write to both keys for backward compatibility */
function getStoredPersona() {
  return (
    localStorage.getItem("mmcp-persona") ||
    localStorage.getItem("selected_persona") ||
    null
  );
}
function setStoredPersona(persona) {
  localStorage.setItem("mmcp-persona", persona);
  localStorage.setItem("selected_persona", persona);
}

/* =================================================================
   TOAST NOTIFICATIONS
   ================================================================= */
function toast(msg, type = "info") {
  const c = document.getElementById("toast-container");
  const t = document.createElement("div");
  t.className = "toast toast-" + type;
  t.textContent = msg;
  c.appendChild(t);
  setTimeout(() => t.remove(), 3200);
}

/* =================================================================
   GLASS CONFIRM / ALERT MODAL (23.6)
   ================================================================= */
function showConfirm(message, onConfirm, onCancel) {
  // Promise-based: showConfirm(msg) returns Promise<boolean>
  if (typeof onConfirm !== "function") {
    return new Promise(function (resolve) {
      showConfirm(message, function () { resolve(true); }, function () { resolve(false); });
    });
  }
  var triggerEl = document.activeElement;
  var overlay = document.createElement("div");
  overlay.className = "confirm-overlay";
  overlay.setAttribute("role", "dialog");
  overlay.setAttribute("aria-modal", "true");
  overlay.innerHTML =
    '<div class="confirm-modal">' +
    '<h3 id="confirm-title">確認</h3>' +
    "<p>" +
    esc(message).replace(/\n/g, "<br>") +
    "</p>" +
    '<div class="confirm-modal-actions">' +
    '<button class="glass-btn" id="confirm-cancel-btn">キャンセル</button>' +
    '<button class="glass-btn glass-btn-danger" id="confirm-ok-btn">OK</button>' +
    "</div></div>";
  overlay.setAttribute("aria-labelledby", "confirm-title");
  document.body.appendChild(overlay);
  requestAnimationFrame(() => overlay.classList.add("show"));

  // Focus the OK button immediately
  var okBtn = document.getElementById("confirm-ok-btn");
  if (okBtn) okBtn.focus();

  function cleanup() {
    overlay.classList.remove("show");
    setTimeout(() => overlay.remove(), 220);
    // Return focus to trigger element
    if (triggerEl && triggerEl.focus) triggerEl.focus();
  }
  okBtn.onclick = function () {
    cleanup();
    if (onConfirm) onConfirm();
  };
  document.getElementById("confirm-cancel-btn").onclick = function () {
    cleanup();
    if (onCancel) onCancel();
  };
  overlay.addEventListener("click", function (e) {
    if (e.target === overlay) {
      cleanup();
      if (onCancel) onCancel();
    }
  });
  // Focus trap
  overlay.addEventListener("keydown", function (e) {
    if (e.key === "Escape") {
      e.stopPropagation();
      cleanup();
      if (onCancel) onCancel();
      return;
    }
    if (e.key === "Tab") {
      var focusable = overlay.querySelectorAll(
        'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])'
      );
      if (focusable.length === 0) return;
      var first = focusable[0];
      var last = focusable[focusable.length - 1];
      if (e.shiftKey && document.activeElement === first) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault();
        first.focus();
      }
    }
  });
}
function showAlert(message) {
  var triggerEl = document.activeElement;
  var overlay = document.createElement("div");
  overlay.className = "confirm-overlay";
  overlay.setAttribute("role", "alertdialog");
  overlay.setAttribute("aria-modal", "true");
  overlay.innerHTML =
    '<div class="confirm-modal">' +
    '<h3 id="alert-title">通知</h3>' +
    "<p>" +
    esc(message).replace(/\n/g, "<br>") +
    "</p>" +
    '<div class="confirm-modal-actions">' +
    '<button class="glass-btn glass-btn-success" id="alert-ok-btn">OK</button>' +
    "</div></div>";
  overlay.setAttribute("aria-labelledby", "alert-title");
  document.body.appendChild(overlay);
  requestAnimationFrame(() => overlay.classList.add("show"));
  var okBtn = document.getElementById("alert-ok-btn");
  if (okBtn) okBtn.focus();
  function cleanup() {
    overlay.classList.remove("show");
    setTimeout(() => overlay.remove(), 220);
    if (triggerEl && triggerEl.focus) triggerEl.focus();
  }
  okBtn.onclick = cleanup;
  overlay.addEventListener("click", function (e) {
    if (e.target === overlay) cleanup();
  });
  overlay.addEventListener("keydown", function (e) {
    if (e.key === "Escape") {
      e.stopPropagation();
      cleanup();
    }
    if (e.key === "Tab") {
      e.preventDefault();
      okBtn.focus();
    }
  });
}

/* =================================================================
   SSE REAL-TIME EVENTS
   ================================================================= */
function connectSSE(persona) {
  // 古い SSE のリスナーを削除してから閉じる（リーク防止）
  if (S._sse) {
    try {
      if (S._sse._sseHandlers) {
        for (const [ev, fn] of Object.entries(S._sse._sseHandlers)) {
          S._sse.removeEventListener(ev, fn);
        }
      }
      S._sse.onerror = null;
      S._sse.close();
    } catch (e) {
      console.warn("[SSE] close failed:", e.message);
    }
  }
  S._sseBackoff = 5000;
  const es = new EventSource(
    "/api/events/" +
      encodeURIComponent(persona) +
      "?topics=memory,context,portrait,emotion,body",
  );
  es._sseHandlers = {};

  es._sseHandlers["memory.created"] = function handleMemoryCreated(e) {
    try {
      const d = JSON.parse(e.data);
      toast(
        "\ud83d\udcdd \u65b0\u3057\u3044\u8a18\u61b6: " +
          (d.content_preview || "...").substring(0, 50),
        "info",
      );
    } catch (e) {
      console.warn("[SSE parse] memory.created:", e.message);
    }
  };
  es.addEventListener("memory.created", es._sseHandlers["memory.created"]);

  es._sseHandlers["memory.updated"] = function handleMemoryUpdated(e) {
    try {
      const d = JSON.parse(e.data);
      toast(
        "\ud83d\udd04 \u8a18\u61b6\u66f4\u65b0: " +
          (d.content_preview || "...").substring(0, 50),
        "info",
      );
    } catch (e) {
      console.warn("[SSE parse] memory.updated:", e.message);
    }
  };
  es.addEventListener("memory.updated", es._sseHandlers["memory.updated"]);

  es._sseHandlers["memory.deleted"] = function handleMemoryDeleted(e) {
    try {
      const d = JSON.parse(e.data);
      toast(
        "\ud83d\uddd1 \u8a18\u61b6\u524a\u9664: " +
          (d.content_preview || "...").substring(0, 50),
        "info",
      );
    } catch (e) {
      console.warn("[SSE parse] memory.deleted:", e.message);
    }
  };
  es.addEventListener("memory.deleted", es._sseHandlers["memory.deleted"]);

  es.addEventListener("context.updated", function (e) {
    toast(
      "\ud83d\udc64 \u30b3\u30f3\u30c6\u30ad\u30b9\u30c8\u66f4\u65b0\u3055\u308c\u307e\u3057\u305f",
      "info",
    );
  });

  es.addEventListener("context.emotion_changed", function (e) {
    try {
      const d = JSON.parse(e.data);
      if (d.emotion) {
        toast(
          "\ud83d\ude0c \u611f\u60c5\u5909\u66f4: " +
            d.emotion +
            " (" +
            Math.round((d.emotion_intensity || 0) * 100) +
            "%)",
          "info",
        );
        window.dispatchEvent(
          new CustomEvent("emotion-changed", { detail: d }),
        );
      }
    } catch (e) {
      console.warn("[SSE parse] context.emotion_changed:", e.message);
    }
  });

  es.addEventListener("context.body_state_changed", function (e) {
    try {
      const d = JSON.parse(e.data);
      if (d.states) {
        const labels = {
          fatigue: "\U0001f525",
          warmth: "\U0001f33c",
          arousal: "\u26a1",
          heart_rate: "\ud83d\udc93",
          pain: "\U0001f4aa",
        };
        const parts = Object.entries(d.states)
          .filter(function (_a) {
            var _b = _a, k = _b[0], v = _b[1];
            return v != null;
          })
          .map(function (_a) {
            var _b = _a, k = _b[0], v = _b[1];
            return (
              (labels[k] || k) + " " + Math.round(Number(v) * 100) + "%"
            );
          });
        if (parts.length) {
          toast("\U0001f9a0 \u4f53\u8abf\u5909\u66f4: " + parts.join(" "), "info");
        }
        window.dispatchEvent(
          new CustomEvent("body-state-changed", { detail: d }),
        );
      }
    } catch (e) {
      console.warn("[SSE parse] context.body_state_changed:", e.message);
    }
  });

  // TB07: Portrait generation SSE events
  es._sseHandlers["portrait.generate_start"] = function handlePortraitGenerateStart(e) {
    try {
      const d = JSON.parse(e.data);
      if (typeof window.handlePortraitGenerateStart === 'function') {
        window.handlePortraitGenerateStart(d);
      }
    } catch (err) {
      console.warn("[SSE parse] portrait.generate_start:", err.message);
    }
  };
  es.addEventListener(
    "portrait.generate_start",
    es._sseHandlers["portrait.generate_start"],
  );

  es._sseHandlers["portrait.generate_complete"] = function handlePortraitGenerateComplete(e) {
    try {
      const d = JSON.parse(e.data);
      if (typeof window.handlePortraitGenerateComplete === 'function') {
        window.handlePortraitGenerateComplete(d);
      }
    } catch (err) {
      console.warn("[SSE parse] portrait.generate_complete:", err.message);
    }
  };
  es.addEventListener(
    "portrait.generate_complete",
    es._sseHandlers["portrait.generate_complete"],
  );

  es._sseHandlers["portrait.generate_error"] = function handlePortraitGenerateError(e) {
    try {
      const d = JSON.parse(e.data);
      if (typeof window.handlePortraitGenerateError === 'function') {
        window.handlePortraitGenerateError(d);
      }
    } catch (err) {
      console.warn("[SSE parse] portrait.generate_error:", err.message);
    }
  };
  es.addEventListener(
    "portrait.generate_error",
    es._sseHandlers["portrait.generate_error"],
  );

  es.onerror = function handleSSEError() {
    S._sse = null;
    var backoff = S._sseBackoff || 5000;
    S._sseBackoff = Math.min(backoff * 2, 60000);
    setTimeout(function () {
      if (S.persona) connectSSE(S.persona);
    }, backoff);
  };
  S._sse = es;
}

/* =================================================================
   API HELPER
   ================================================================= */
async function api(path, opts = {}) {
  try {
    const resp = await fetch(path, {
      headers: { "Content-Type": "application/json", ...opts.headers },
      ...opts,
    });
    if (!resp.ok) {
      const err = await resp.json().catch(() => ({ error: resp.statusText }));
      throw new Error(err.error || resp.statusText);
    }
    return await resp.json();
  } catch (e) {
    console.error("API error:", path, e);
    throw e;
  }
}

/* =================================================================
   CHART HELPERS
   ================================================================= */
function destroyChart(id) {
  if (S.charts[id]) {
    S.charts[id].destroy();
    delete S.charts[id];
  }
}
function chartOpts(extra = {}) {
  const color =
    getComputedStyle(document.documentElement)
      .getPropertyValue("--text-muted")
      .trim() || "#94a3b8";
  return {
    responsive: true,
    maintainAspectRatio: false,
    plugins: {
      legend: { labels: { color, font: { size: 11 } } },
      ...extra.plugins,
    },
    scales: extra.scales
      ? Object.fromEntries(
          Object.entries(extra.scales).map(([k, v]) => [
            k,
            {
              ...v,
              ticks: { color, ...(v.ticks || {}) },
              grid: { color: "rgba(167,139,250,0.08)", ...(v.grid || {}) },
            },
          ]),
        )
      : undefined,
  };
}

/* =================================================================
   SKELETON HELPERS
   ================================================================= */
function skeletonCard() {
  return '<div class="glass p-6"><div class="skeleton skeleton-title"></div><div class="skeleton skeleton-text" style="width:80%"></div><div class="skeleton skeleton-text" style="width:60%"></div></div>';
}
function errorCard(msg) {
  return (
    '<div class="glass p-6 text-center" style="color:var(--accent-red)"><p style="font-size:1.2rem;margin-bottom:8px"><i data-lucide="alert-triangle"></i></p><p>' +
    esc(msg) +
    "</p></div>"
  );
}

/* =================================================================
   THEME TOGGLE
   ================================================================= */
function applyTheme() {
  const dark = localStorage.getItem("mmcp-dark") !== "false";
  document.documentElement.className = dark ? "dark" : "light";
  document.getElementById("dark-toggle").innerHTML = dark
    ? '<i data-lucide="moon"></i>'
    : '<i data-lucide="sun"></i>';
  if (typeof lucide !== "undefined") lucide.createIcons();
  // Re-render charts for color update
  Object.values(S.charts).forEach((c) => c.update());
}
function toggleTheme() {
  const isDark = document.documentElement.classList.contains("dark");
  localStorage.setItem("mmcp-dark", isDark ? "false" : "true");
  applyTheme();
}

/* =================================================================
   SKELETON LOADING
   ================================================================= */
function showSkeleton(tabId) {
  const container = document.getElementById("tab-" + tabId);
  if (!container) return;
  const skeletons = {
    overview:
      '<div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4 mb-6">' +
      '<div class="skeleton skeleton-card glass"></div>'.repeat(4) +
      '</div><div class="grid grid-cols-1 lg:grid-cols-2 gap-6">' +
      '<div class="skeleton glass" style="height:200px"></div>'.repeat(2) +
      "</div>",
    analytics:
      '<div class="skeleton skeleton-chart glass mb-6"></div>' +
      '<div class="grid grid-cols-1 md:grid-cols-2 gap-4">' +
      '<div class="skeleton glass" style="height:200px"></div>'.repeat(2) +
      "</div>",
    memories:
      '<div class="skeleton skeleton-line mb-4" style="height:48px"></div>' +
      '<div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">' +
      '<div class="skeleton skeleton-card glass"></div>'.repeat(6) +
      "</div>",
    settings:
      '<div class="skeleton glass mb-4" style="height:160px"></div>'.repeat(3),
    graph: '<div class="skeleton glass" style="height:600px"></div>',
    "import-export":
      '<div class="skeleton glass mb-4" style="height:200px"></div>' +
      '<div class="skeleton glass" style="height:200px"></div>',
    personas:
      '<div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">' +
      '<div class="skeleton skeleton-card glass"></div>'.repeat(3) +
      "</div>",
    admin: '<div class="skeleton glass" style="height:300px"></div>',
    timeline: '<div class="skeleton glass" style="height:500px"></div>',
  };
  /* graph / import-export / personas / chat / timeline manage their own loading state via
       inner elements (#graph-loading, #persona-grid, #export-preview, #chat-messages, #tl-loading).
       Replacing their innerHTML would destroy those elements and cause
       silent failures in the corresponding load functions. */
  if (
    tabId === "graph" ||
    tabId === "import-export" ||
    tabId === "personas" ||
    tabId === "chat" ||
    tabId === "timeline" ||
    tabId === "activity"
  )
    return;
  const content = container.querySelector('[id$="-content"]') || container;
  content.innerHTML =
    skeletons[tabId] || '<div class="skeleton skeleton-card glass"></div>';
}

/* =================================================================
   TAB SWITCHING
   ================================================================= */
function switchTab(tab) {
  S.tab = tab;
  localStorage.setItem("mmcp-tab", tab);
  document.querySelectorAll(".tab-btn").forEach((b) => {
    const isActive = b.dataset.tab === tab;
    b.classList.toggle("active", isActive);
    b.setAttribute("aria-selected", isActive);
  });
  document.querySelectorAll(".tab-panel").forEach((p) => {
    const isTarget = p.id === "tab-" + tab;
    p.classList.toggle("active", isTarget);
    // Skip animation on subsequent tab switches
    if (isTarget && S._tabSwitchCount > 0) {
      p.classList.add("no-first-anim");
    } else if (isTarget) {
      p.classList.remove("no-first-anim");
    }
  });
  S._tabSwitchCount = (S._tabSwitchCount || 0) + 1;
  showSkeleton(tab);
  loadTab(tab);
  // Lucide.createIcons() skips already-rendered <i> tags, so this is safe to call broadly
  setTimeout(() => {
    if (typeof lucide !== "undefined") lucide.createIcons();
  }, 100);
}
function loadTab(tab) {
  if (!S.persona && tab !== "settings" && tab !== "personas") return;
  var fn;
  switch (tab) {
    case "overview":
      fn = typeof loadOverview === 'function' ? loadOverview : null;
      break;
    case "analytics":
      fn = typeof loadAnalytics === 'function' ? loadAnalytics : null;
      break;
    case "memories":
      fn = typeof loadMemories === 'function' ? loadMemories : null;
      break;
    case "graph":
      fn = typeof loadGraph === 'function' ? loadGraph : null;
      break;
    case "import-export":
      fn = typeof loadImportExport === 'function' ? loadImportExport : null;
      break;
    case "personas":
      fn = typeof loadPersonas === 'function' ? loadPersonas : null;
      break;
    case "settings":
      fn = typeof loadSettings === 'function' ? loadSettings : null;
      break;
    case "chat":
      fn = typeof loadChat === 'function' ? loadChat : null;
      break;
    case "activity":
      fn = typeof loadActivity === 'function'
        ? function () { loadActivity(true); }
        : null;
      break;
    case "admin":
      fn = typeof loadAdmin === 'function' ? loadAdmin : null;
      break;
  }
  if (fn) {
    fn();
  } else {
    document.addEventListener('DOMContentLoaded', function deferTab() {
      if (tab === "activity") {
        if (typeof loadActivity === 'function') loadActivity(true);
      } else {
        var deferFn = typeof window['load' + tab.charAt(0).toUpperCase() + tab.slice(1)] === 'function'
          ? window['load' + tab.charAt(0).toUpperCase() + tab.slice(1)]
          : null;
        if (deferFn) deferFn();
      }
    });
  }
}

/* =================================================================
   MEMORY DETAIL MODAL
   ================================================================= */
function openMemModal(mem) {
  const overlay = document.getElementById("mem-modal-overlay");
  const content = document.getElementById("mem-modal-content");
  const tags = (mem.tags || [])
    .map((t) => '<span class="badge badge-purple">' + esc(t) + "</span>")
    .join(" ");
  var emoHtml = "";
  if (mem.emotion) {
    emoHtml =
      '<span class="badge badge-pink"><i data-lucide="smile"></i> ' +
      esc(mem.emotion) +
      (mem.emotion_intensity != null
        ? " (" + (mem.emotion_intensity * 100).toFixed(0) + "%)"
        : "") +
      "</span>";
  }
  content.innerHTML = `
        <div class="mem-modal-header">
            <div>
                <div style="font-size:0.7rem;color:var(--text-muted);margin-bottom:4px">Memory Key</div>
                <div style="font-family:monospace;font-size:0.85rem;color:var(--accent-purple)">${esc(mem.memory_key)}</div>
            </div>
            <button class="mem-modal-close" onclick="closeMemModal()"><i data-lucide="x"></i></button>
        </div>
        <div class="mem-modal-content">${esc(mem.content)}</div>
        <div>
            ${tags || emoHtml ? `<div class="mem-modal-row"><span class="mem-modal-key">Tags/Emotion</span><span>${tags} ${emoHtml}</span></div>` : ""}
            ${mem.importance != null ? `<div class="mem-modal-row"><span class="mem-modal-key">Importance</span><span style="color:var(--accent-yellow)">${mem.importance.toFixed(2)}</span></div>` : ""}
            ${mem.strength != null ? `<div class="mem-modal-row"><span class="mem-modal-key">Strength</span><span style="color:var(--accent-green)"><i data-lucide="zap"></i>${mem.strength.toFixed(3)}</span></div>` : ""}
            ${mem.privacy_level ? `<div class="mem-modal-row"><span class="mem-modal-key">Privacy</span><span>${esc(mem.privacy_level)}</span></div>` : ""}
            ${mem.source_context ? `<div class="mem-modal-row"><span class="mem-modal-key">Source</span><span style="color:var(--text-muted)">${esc(mem.source_context)}</span></div>` : ""}
            ${mem.created_at ? `<div class="mem-modal-row"><span class="mem-modal-key">Created</span><span><i data-lucide="calendar"></i> ${relativeTime(mem.created_at)} <span style="color:var(--text-muted);font-size:0.75rem">(${new Date(mem.created_at).toLocaleString("ja-JP")})</span></span></div>` : ""}
            ${mem.state_snapped_at && mem.state_snapped_at !== mem.created_at ? `<div class="mem-modal-row"><span class="mem-modal-key">State</span><span><i data-lucide="camera"></i> ${relativeTime(mem.state_snapped_at)} <span style="color:var(--text-muted);font-size:0.75rem">(${new Date(mem.state_snapped_at).toLocaleString("ja-JP")})</span></span></div>` : ""}
            ${mem.updated_at ? `<div class="mem-modal-row"><span class="mem-modal-key">Updated</span><span><i data-lucide="calendar"></i> ${relativeTime(mem.updated_at)}</span></div>` : ""}
            ${mem.body_state ? renderBodyStateBars(mem.body_state) : ""}
            ${mem.emotion ? renderEmotionBars(mem.emotion, mem.emotion_intensity) : ""}
        </div>`;
  overlay.classList.add("show");
  document.addEventListener("keydown", _memModalKeyHandler);
}
function closeMemModal() {
  const overlay = document.getElementById("mem-modal-overlay");
  if (!overlay || !overlay.classList.contains("show")) return;
  overlay.classList.remove("show");
  document.removeEventListener("keydown", _memModalKeyHandler);
}
function _memModalKeyHandler(e) {
  if (e.key === "Escape") closeMemModal();
}

/* =================================================================
   LAST UPDATE TIMESTAMP
   ================================================================= */
function updateLastTime() {
  const el = document.getElementById("last-update");
  if (el)
    el.textContent =
      "Last: " +
      new Date().toLocaleTimeString("ja-JP", {
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
      });
}

/* =================================================================
   PAGE CLEANUP (beforeunload)
   ================================================================= */
window.addEventListener("beforeunload", function cleanupBeforeUnload() {
  if (S._sse) {
    S._sse.close();
    S._sse = null;
  }
});

/* =================================================================
   INITIALIZATION
   ================================================================= */
async function init() {
  // Initialize centralized store
  if (window.Nous && window.Nous.Core && window.Nous.Core.store) {
    window.Nous.Core.store.init({
      persona: null,
      tab: localStorage.getItem("mmcp-tab") || "overview",
      charts: {},
      mem: { page: 1, tag: "", q: "", perPage: 20 },
      statusPoll: null,
      dashCache: null,
      initTime: Date.now(),
    });
    // Bridge: keep S object for backward compat, backed by store
    (function() {
      var store = window.Nous.Core.store;
      Object.keys(S).forEach(function(k) {
        if (store.get(k) === undefined) store.set(k, S[k]);
      });
    })();
  }

  // Theme
  applyTheme();

  // Load personas
  try {
    const data = await api("/api/personas");
    const personas = data.personas || [];
    const sel = document.getElementById("persona-select");
    sel.innerHTML = "";
    if (personas.length === 0) {
      sel.innerHTML = '<option value="">No personas found</option>';
      document.getElementById("overview-content").innerHTML =
        '<div class="empty-state"><div class="empty-state-icon"><i data-lucide="user-plus"></i></div>' +
        '<div class="empty-state-text">Personasタブでペルソナを作成してください。</div>' +
        '<button class="empty-state-cta" onclick="switchTab(\'personas\')"><i data-lucide="user-plus"></i> ペルソナを作成</button></div>';
      if (typeof lucide !== "undefined") lucide.createIcons();
      return;
    }
    personas.forEach((p) => {
      const opt = document.createElement("option");
      opt.value = p;
      opt.textContent = p;
      sel.appendChild(opt);
    });
    // 優先度: __INITIAL_PERSONA__ > localStorage > personas[0]
    const savedPersona = localStorage.getItem("mmcp-persona");
    let _target = null;
    if (window.__INITIAL_PERSONA__) {
      _target = window.__INITIAL_PERSONA__;
    } else if (
      savedPersona &&
      personas.some((p) => (p.id || p) === savedPersona)
    ) {
      _target = savedPersona;
    } else {
      _target = personas[0]?.id || personas[0];
    }
    S.persona = _target;
    sel.value = _target;
    connectSSE(_target);
    switchTab(S.tab);
  } catch (e) {
    toast("Failed to load personas: " + e.message, "error");
  }

  // Event: Persona change
  document.getElementById("persona-select").onchange = (e) => {
    S.persona = e.target.value;
    setStoredPersona(e.target.value);
    connectSSE(e.target.value);
    S.dashCache = null;
    // Reset pagination/search without losing extended properties from memories.js
    Object.assign(S.mem, {
      page: 1,
      tag: "",
      q: "",
      perPage: 20,
      selectMode: false,
      advOpen: false,
      dateFrom: "",
      dateTo: "",
      searchTags: [],
      emotion: "",
    });
    if (S.mem.selected instanceof Set) S.mem.selected.clear();
    loadTab(S.tab);
  };

  // Event: Tab switch
  document.querySelectorAll(".tab-btn").forEach((btn) => {
    btn.addEventListener("click", () => switchTab(btn.dataset.tab));
  });

  // Event: Theme toggle
  document.getElementById("dark-toggle").onclick = toggleTheme;

  // Global API error handler — toast with retry
  window.addEventListener("api:error", function _handleApiError(e) {
    var d = e.detail;
    if (!d) return;
    var known = N.Core.toastAction || toastAction || null;
    if (typeof known === "function") {
      known(d.message || "API error", "error", "再試行", function() {
        fetch(d.path, { method: "GET" }).then(function(r) {
          if (r.ok) { toast("再試行成功", "success"); }
        }).catch(function() {});
      });
    } else {
      toast(d.message || "API error", "error");
    }
  });

  // Keyboard: tab navigation
  document.addEventListener("keydown", (e) => {
    if (e.altKey && ((e.key >= "1" && e.key <= "9") || e.key === "0")) {
      e.preventDefault();
      const tabs = [
        "overview",
        "analytics",
        "memories",
        "timeline",
        "graph",
        "import-export",
        "personas",
        "chat",
        "settings",
        "admin",
        "activity",
      ];
      const idx = e.key === "0" ? 9 : parseInt(e.key) - 1;
      if (idx < tabs.length) switchTab(tabs[idx]);
    }
  });
}

/* =================================================================
   STAGGERED CARD ANIMATION
   ================================================================= */
function animateCards(container) {
  if (!container) return;
  const cards = container.querySelectorAll(".glass");
  cards.forEach(function (card, i) {
    card.style.opacity = "0";
    card.style.transform = "translateY(16px)";
    setTimeout(function () {
      card.style.transition = "opacity 0.4s ease, transform 0.4s ease";
      card.style.opacity = "1";
      card.style.transform = "translateY(0)";
    }, i * 60);
  });
}

/* =================================================================
   KEYBOARD SHORTCUTS (Ctrl+F / Escape)
   ================================================================= */
document.addEventListener("keydown", function (e) {
  if ((e.ctrlKey || e.metaKey) && e.key === "f") {
    var searchInput = document.querySelector(
      ".tab-panel.active input[data-search]",
    );
    if (!searchInput)
      searchInput = document.querySelector(
        '.tab-panel.active input[type="text"][placeholder*="earch"]',
      );
    if (searchInput) {
      e.preventDefault();
      searchInput.focus();
    }
  }
});

/* =================================================================
   ARIA LABELS ON LOAD
   ================================================================= */
document.addEventListener("DOMContentLoaded", function () {
  document.querySelectorAll(".tab-btn").forEach(function (btn, i) {
    btn.setAttribute("role", "tab");
    btn.setAttribute("aria-label", btn.textContent.trim());
    btn.setAttribute("tabindex", "0");
  });
  document.querySelectorAll(".tab-panel").forEach(function (tab) {
    tab.setAttribute("role", "tabpanel");
  });
  var tablist = document.querySelector(".tab-bar");
  if (tablist) tablist.setAttribute("role", "tablist");
});

// Boot
init();
