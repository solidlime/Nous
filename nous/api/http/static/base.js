;(function() {

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
window.S = S;

/* =================================================================
   CORE — Import from modules (replaces legacy global definitions)
   ================================================================= */
var C = window.Nous.Core;
var esc = C.esc, toast = C.toast, api = C.api;
var showConfirm = C.showConfirm, showAlert = C.showAlert;
var truncate = C.truncate, relativeTime = C.relativeTime, fmtDate = C.fmtDate;
var applyTheme = C.applyTheme, toggleTheme = C.toggleTheme, connectSSE = C.connectSSE;

/* =================================================================
   CONSTANTS
   ================================================================= */
var CHART_COLORS = C.CHART_COLORS;
var EMOTION_COLORS = C.EMOTION_COLORS;
var EMOTION_BAR_COLORS = C.EMOTION_BAR_COLORS;
var BODY_BAR_COLORS = C.BODY_BAR_COLORS;
var BODY_LABELS = C.BODY_LABELS;
window.CHART_COLORS = CHART_COLORS;
window.EMOTION_COLORS = EMOTION_COLORS;
window.EMOTION_BAR_COLORS = EMOTION_BAR_COLORS;
window.BODY_BAR_COLORS = BODY_BAR_COLORS;
window.BODY_LABELS = BODY_LABELS;

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
window.renderBodyStateBars = renderBodyStateBars;

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
window.renderEmotionBars = renderEmotionBars;

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
window.renderEmotionBadges = renderEmotionBadges;

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
window.renderBodyStateCompact = renderBodyStateCompact;


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
   CHART HELPERS
   ================================================================= */
function destroyChart(id) {
  if (S.charts[id]) {
    S.charts[id].destroy();
    delete S.charts[id];
  }
}
window.destroyChart = destroyChart;
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
              grid: { color: "rgba(0,122,255,0.08)", ...(v.grid || {}) },
            },
          ]),
        )
      : undefined,
  };
}
window.chartOpts = chartOpts;

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
window.errorCard = errorCard;

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
window.switchTab = switchTab;
function loadTab(tab) {
  if (!S.persona && tab !== "settings" && tab !== "personas") return;
  var fn;
   var loaderName = 'load' + tab.charAt(0).toUpperCase() + tab.slice(1);
   fn = typeof window[loaderName] === 'function' ? window[loaderName] : null;
  if (fn) {
    if (tab === "activity") {
      (function () { fn(true); })();
    } else {
      fn();
    }
  } else {
    // Retry after a tick in case loader script hasn't executed yet
    setTimeout(function deferTab() {
      var deferFn = typeof window[loaderName] === 'function' ? window[loaderName] : null;
      if (deferFn) deferFn();
      else console.warn("[loadTab] loader not found:", loaderName);
    }, 10);
  }
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
window.updateLastTime = updateLastTime;

/* =================================================================
   PAGE CLEANUP (beforeunload)
   ================================================================= */
window.addEventListener("beforeunload", function cleanupBeforeUnload() {
  if (C._sse) {
    C._sse.close();
    C._sse = null;
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
    syncDeleteBtn();
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
    syncDeleteBtn();
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

   // Persona delete button — show only when a real persona is selected
  function syncDeleteBtn() {
    var btn = document.getElementById('delete-persona-btn');
    var sel = document.getElementById('persona-select');
    if (btn && sel) {
      btn.style.display = (sel.value && sel.value !== 'None') ? '' : 'none';
    }
  }

   // Event: Theme toggle
  document.getElementById("dark-toggle").onclick = toggleTheme;

  // Global API error handler — toast with retry
  window.addEventListener("api:error", function _handleApiError(e) {
    var d = e.detail;
    if (!d) return;
    var known = C.toastAction || null;
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
window.init = init;

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
window.animateCards = animateCards;

/* =================================================================
   KEYBOARD SHORTCUTS (Ctrl+F / Escape / ? help)
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

/* Keyboard shortcut help overlay — toggle with ? key */
function toggleShortcutHelp() {
  var existing = document.getElementById("shortcut-help-overlay");
  if (existing) {
    existing.remove();
    return;
  }
  var overlay = document.createElement("div");
  overlay.id = "shortcut-help-overlay";
  overlay.className = "shortcut-help-overlay";
  overlay.setAttribute("role", "dialog");
  overlay.setAttribute("aria-label", "Keyboard Shortcuts");
  overlay.innerHTML =
    '<div class="shortcut-help-modal">' +
    '<div class="shortcut-help-header">' +
    '<span>⌨ Keyboard Shortcuts</span>' +
    '<button class="shortcut-help-close" onclick="toggleShortcutHelp()" aria-label="Close shortcuts"><i data-lucide="x"></i></button>' +
    "</div>" +
    '<div class="shortcut-help-body">' +
    "<table>" +
    "<tr><td><kbd>Alt+1</kbd>–<kbd>9</kbd></td><td>Switch tabs</td></tr>" +
    "<tr><td><kbd>Alt+0</kbd></td><td>Switch to Activity tab</td></tr>" +
    "<tr><td><kbd>Ctrl+F</kbd> / <kbd>⌘F</kbd></td><td>Focus search input</td></tr>" +
    "<tr><td><kbd>Esc</kbd></td><td>Close modals / panels</td></tr>" +
    "<tr><td><kbd>?</kbd></td><td>Toggle this help</td></tr>" +
    "</table>" +
    "</div></div>";
  document.body.appendChild(overlay);
  requestAnimationFrame(function () {
    overlay.classList.add("show");
    overlay.querySelector(".shortcut-help-close").focus();
  });
  if (typeof lucide !== "undefined") lucide.createIcons();
}
window.toggleShortcutHelp = toggleShortcutHelp;

/* Global ? key listener for shortcut help */
document.addEventListener("keydown", function (e) {
  /* ? or Shift+/ on US/JP keyboards */
  if (e.key === "?" || (e.key === "/" && e.shiftKey)) {
    /* Don't trigger when focused on input/textarea */
    var tag = document.activeElement && document.activeElement.tagName;
    if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return;
    e.preventDefault();
    toggleShortcutHelp();
  }
});
/* Close shortcut help on Escape */
document.addEventListener("keydown", function (e) {
  if (e.key === "Escape") {
    var overlay = document.getElementById("shortcut-help-overlay");
    if (overlay && overlay.classList.contains("show")) {
      e.preventDefault();
      toggleShortcutHelp();
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

// Boot — defer-safe: wait for all deferred scripts to load
if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", init);
} else {
  init();
}

/* =================================================================
   CREATE PERSONA MODAL
   ================================================================= */
function openCreatePersonaModal() {
  var modal = document.getElementById('create-persona-modal');
  if (!modal) {
    modal = document.createElement('div');
    modal.id = 'create-persona-modal';
    modal.className = 'modal-overlay';
    modal.style.cssText = 'position:fixed;top:0;left:0;right:0;bottom:0;background:rgba(0,0,0,0.5);display:flex;align-items:center;justify-content:center;z-index:9999';
    modal.innerHTML = '\
      <div style="background:var(--bg-card);border-radius:16px;padding:24px;min-width:360px;box-shadow:0 20px 60px rgba(0,0,0,0.3)">\
        <h2 style="margin:0 0 4px 0;font-size:1.2rem"><i data-lucide="user-plus"></i> Create Persona</h2>\
        <p style="color:var(--text-muted);font-size:0.85rem;margin:0 0 16px 0">Enter a name for the new persona.</p>\
        <form onsubmit="return submitCreatePersona(event)" style="display:flex;flex-direction:column;gap:12px">\
          <input id="new-persona-name" type="text" placeholder="e.g. assistant, friend, scholar" class="glass-input" style="width:100%;padding:10px" required autofocus>\
          <div style="display:flex;gap:8px;justify-content:flex-end">\
            <button type="button" class="glass-btn" onclick="closeCreatePersonaModal()">Cancel</button>\
            <button type="submit" class="glass-btn" style="background:var(--accent-purple);color:white">Create</button>\
          </div>\
        </form>\
      </div>';
    document.body.appendChild(modal);
    // Close on overlay click
    modal.addEventListener('click', function(e) {
      if (e.target === modal) closeCreatePersonaModal();
    });
  }
  modal.style.display = 'flex';
  setTimeout(function() {
    var input = document.getElementById('new-persona-name');
    if (input) input.focus();
  }, 100);
}

function closeCreatePersonaModal() {
  var modal = document.getElementById('create-persona-modal');
  if (modal) modal.style.display = 'none';
}

function submitCreatePersona(e) {
  e.preventDefault();
  var nameInput = document.getElementById('new-persona-name');
  var name = nameInput.value.trim();
  if (!name) return false;
  api('/api/personas', {method: 'POST', body: JSON.stringify({name: name})}).then(function(data) {
    closeCreatePersonaModal();
    var sel = document.getElementById('persona-select');
    var exists = Array.from(sel.options).some(function(o) { return o.value === name; });
    if (!exists) {
      var opt = document.createElement('option');
      opt.value = name;
      opt.textContent = name;
      sel.appendChild(opt);
    }
    sel.value = name;
    sel.dispatchEvent(new Event('change', {bubbles: true}));
    if (typeof toast === 'function') toast('Persona "' + name + '" created.', 'success');
    else if (typeof N !== 'undefined' && N.Core && N.Core.toast) N.Core.toast('Persona "' + name + '" created.', 'success');
  }).catch(function(err) {
    if (typeof toast === 'function') toast('Failed: ' + err.message, 'error');
    else if (typeof N !== 'undefined' && N.Core && N.Core.toast) N.Core.toast('Failed: ' + err.message, 'error');
  });
  return false;
}

// Export to global scope
window.openCreatePersonaModal = openCreatePersonaModal;
window.closeCreatePersonaModal = closeCreatePersonaModal;
window.submitCreatePersona = submitCreatePersona;

function deleteCurrentPersona() {
  var sel = document.getElementById('persona-select');
  var name = sel.value;
  if (!name || name === 'None') return;
  if (!confirm('Delete persona "' + name + '"? This cannot be undone.')) return;
  api('/api/personas/' + encodeURIComponent(name), {method: 'DELETE'}).then(function(data) {
    var opt = sel.querySelector('option[value="' + name.replace(/"/g, '\\"') + '"]');
    if (opt) opt.remove();
    var first = sel.options[0];
    if (first) { sel.value = first.value; sel.dispatchEvent(new Event('change', {bubbles: true})); }
    if (typeof N !== 'undefined' && N.Core && N.Core.toast) N.Core.toast('Persona "' + name + '" deleted.', 'success');
  }).catch(function(err) {
    if (typeof N !== 'undefined' && N.Core && N.Core.toast) N.Core.toast('Delete failed: ' + err.message, 'error');
  });
}
window.deleteCurrentPersona = deleteCurrentPersona;

// Escape key closes persona modal
document.addEventListener('keydown', function(e) {
  if (e.key === 'Escape') {
    var modal = document.getElementById('create-persona-modal');
    if (modal && modal.style.display !== 'none') closeCreatePersonaModal();
  }
});
})();
