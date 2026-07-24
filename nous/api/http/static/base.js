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

/* ── Delegate to N.Components.memoryCard (defined in components/memory-card.js) ── */
function renderBodyStateBars(bodyState) {
  return N.Components.memoryCard.renderBodyStateBars(bodyState);
}
window.renderBodyStateBars = renderBodyStateBars;

function renderEmotionBars(emotion, emotion_intensity) {
  return N.Components.memoryCard.renderEmotionBars(emotion, emotion_intensity);
}
window.renderEmotionBars = renderEmotionBars;

function renderEmotionBadges(emotion, emotion_intensity) {
  return N.Components.memoryCard.renderEmotionBadges(emotion, emotion_intensity);
}
window.renderEmotionBadges = renderEmotionBadges;

function renderBodyStateCompact(bodyState) {
  return N.Components.memoryCard.renderBodyStateCompact(bodyState);
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
/* ── Delegate to N.Components.chart (defined in components/chart.js) ── */
function destroyChart(id) {
  N.Components.chart.destroy(id);
}
window.destroyChart = destroyChart;
function chartOpts(extra) {
  return N.Components.chart.defaults(extra);
}
window.chartOpts = chartOpts;

/* =================================================================
   SKELETON HELPERS
   ================================================================= */
/* ── Delegate to N.Components.skeleton (defined in components/skeleton.js) ── */
function skeletonCard() {
  return N.Components.skeleton.card();
}
function errorCard(msg) {
  return N.Components.skeleton.errorCard(msg);
}
window.errorCard = errorCard;

/* =================================================================
   SKELETON LOADING
   ================================================================= */
/* ── Delegate to N.Components.skeleton (defined in components/skeleton.js) ── */
function showSkeleton(tabId) {
  N.Components.skeleton.show(tabId);
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
    // Bridge: bi-directional sync — S reads/writes go through store
    window.Nous.Core.store.syncFrom(S);
  }

  // Theme
  applyTheme();

  // Load personas
  try {
    const data = await api("/api/personas");
    const personas = data.personas || [];
    const sel = document.getElementById("persona-select");
    safeSetHTML(sel, "");
    if (personas.length === 0) {
      safeSetHTML(sel, '<option value="">No personas found</option>');
      safeSetHTML(document.getElementById("overview-content"),
        '<div class="empty-state"><div class="empty-state-icon"><i data-lucide="user-plus"></i></div>' +
        '<div class="empty-state-text">Personasタブでペルソナを作成してください。</div>' +
        '<button class="empty-state-cta" onclick="switchTab(\'personas\')"><i data-lucide="user-plus"></i> ペルソナを作成</button></div>');
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

  // ── Hamburger menu (mobile) ──
  function buildHamburgerMenu() {
    var existing = document.getElementById("hamburger-btn");
    if (existing) return; // already built

    var headerControls = document.querySelector(".header-controls");
    if (!headerControls) return;

    // Hamburger button
    var hamBtn = document.createElement("button");
    hamBtn.id = "hamburger-btn";
    hamBtn.className = "glass-btn hamburger-btn";
    hamBtn.setAttribute("aria-label", "Toggle navigation");
    hamBtn.setAttribute("aria-expanded", "false");
    hamBtn.setAttribute("role", "button");
    hamBtn.setAttribute("tabindex", "0");
    safeSetHTML(hamBtn, '<i data-lucide="menu"></i>');
    headerControls.insertBefore(hamBtn, headerControls.firstChild);

    // Backdrop
    var backdrop = document.createElement("div");
    backdrop.id = "nav-backdrop";
    backdrop.className = "nav-backdrop";

    // Drawer
    var drawer = document.createElement("nav");
    drawer.id = "nav-drawer";
    drawer.className = "nav-drawer";
    drawer.setAttribute("role", "navigation");
    drawer.setAttribute("aria-label", "Mobile navigation");

    var drawerHeader = document.createElement("div");
    drawerHeader.className = "nav-drawer-header";
    safeSetHTML(drawerHeader, '<span style="font-weight:600;font-size:1rem;color:var(--text-primary)"><i data-lucide="layout-dashboard"></i> Pages</span>' +
      '<button id="nav-drawer-close" class="glass-btn" style="padding:6px 10px;min-height:44px;min-width:44px" aria-label="Close navigation"><i data-lucide="x"></i></button>');
    drawer.appendChild(drawerHeader);

    // Build menu items from existing tab buttons
    var tabBtns = document.querySelectorAll(".tab-btn");
    var menuList = document.createElement("div");
    menuList.className = "nav-drawer-items";
    tabBtns.forEach(function(btn) {
      var item = document.createElement("button");
      item.className = "nav-drawer-item";
      item.setAttribute("data-tab", btn.dataset.tab);
      item.setAttribute("role", "menuitem");
      item.textContent = btn.textContent.trim();
      item.addEventListener("click", function() {
        switchTab(btn.dataset.tab);
        closeNavDrawer();
      });
      menuList.appendChild(item);
    });
    drawer.appendChild(menuList);
    document.body.appendChild(backdrop);
    document.body.appendChild(drawer);

    // Open / close
    hamBtn.addEventListener("click", openNavDrawer);
    hamBtn.addEventListener("keydown", function(e) {
      if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        openNavDrawer();
      }
    });
    document.getElementById("nav-drawer-close").addEventListener("click", closeNavDrawer);
    backdrop.addEventListener("click", closeNavDrawer);

    function openNavDrawer() {
      backdrop.classList.add("visible");
      drawer.classList.add("open");
      hamBtn.setAttribute("aria-expanded", "true");
      document.body.style.overflow = "hidden";
      setTimeout(function() {
        document.getElementById("nav-drawer-close").focus();
      }, 100);
    }

    function closeNavDrawer() {
      backdrop.classList.remove("visible");
      drawer.classList.remove("open");
      hamBtn.setAttribute("aria-expanded", "false");
      document.body.style.overflow = "";
      hamBtn.focus();
    }

    window._closeNavDrawer = closeNavDrawer;

    // Escape closes drawer
    document.addEventListener("keydown", function _drawerEsc(e) {
      if (e.key === "Escape" && drawer.classList.contains("open")) {
        closeNavDrawer();
      }
    });
  }
  buildHamburgerMenu();

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

    // Arrow key tab navigation (Left / Right)
    if (e.key === "ArrowLeft" || e.key === "ArrowRight") {
      const tabBtns = document.querySelectorAll('.tab-btn[role="tab"]');
      let currentIdx = -1;
      tabBtns.forEach((btn, i) => {
        if (btn === document.activeElement) currentIdx = i;
      });
      if (currentIdx === -1) return;
      e.preventDefault();
      const nextIdx = e.key === "ArrowRight"
        ? (currentIdx + 1) % tabBtns.length
        : (currentIdx - 1 + tabBtns.length) % tabBtns.length;
      tabBtns[nextIdx].focus();
      switchTab(tabBtns[nextIdx].dataset.tab);
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
  safeSetHTML(overlay,
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
    "</div></div>");
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
    safeSetHTML(modal, '\
      <div style="background:var(--bg-secondary);border-radius:16px;padding:24px;min-width:360px;box-shadow:0 20px 60px rgba(0,0,0,0.3)">\
        <h2 style="margin:0 0 4px 0;font-size:1.2rem"><i data-lucide="user-plus"></i> Create Persona</h2>\
        <p style="color:var(--text-muted);font-size:0.85rem;margin:0 0 16px 0">Enter a name for the new persona.</p>\
        <form onsubmit="return submitCreatePersona(event)" style="display:flex;flex-direction:column;gap:12px">\
          <input id="new-persona-name" type="text" placeholder="e.g. assistant, friend, scholar" class="glass-input" style="width:100%;padding:10px" required autofocus>\
          <div style="display:flex;gap:8px;justify-content:flex-end">\
            <button type="button" class="glass-btn" onclick="closeCreatePersonaModal()">Cancel</button>\
            <button type="submit" class="glass-btn" style="background:var(--accent-purple);color:white">Create</button>\
          </div>\
        </form>\
      </div>');
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
