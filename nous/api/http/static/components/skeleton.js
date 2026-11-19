/* =================================================================
   SKELETON LOADING COMPONENT — N.Components.skeleton
   ================================================================= */
;(function(N) {
"use strict";

var C = N.Core;
var safeSetHTML = C.safeSetHTML;

/* ── Registration store (tabId → skeleton HTML) ── */
var _registry = {};

/* ── Default skeleton HTML for each tab (used when no registration) ──
   #93: only non-self-managed tabs need a default here — self-managed
   tabs never reach the lookup (show() returns early via data-self-managed). */
var _defaults = {
  overview:
    '<div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4 mb-6">' +
    '<div class="skeleton skeleton-card glass"></div>'.repeat(4) +
    '</div><div class="grid grid-cols-1 lg:grid-cols-2 gap-6">' +
    '<div class="skeleton glass" style="height:200px"></div>'.repeat(2) +
    "</div>",
  memories:
    '<div class="skeleton skeleton-line mb-4" style="height:48px"></div>' +
    '<div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">' +
    '<div class="skeleton skeleton-card glass"></div>'.repeat(6) +
    "</div>",
  settings:
    '<div class="skeleton glass mb-4" style="height:160px"></div>'.repeat(3),
};

/* ── Tabs that manage their own loading state (should not be skeleton-replaced) ──
   #93: read from the nav button's data-self-managed (emitted by
   dashboard.py) — this static copy of the list is gone. */

/* ── Register a custom skeleton config for a tab ── */
function register(tabId, config) {
  _registry[tabId] = config;
}

/* ── Content container of a tab panel — the [id$="-content"] convention.
   #93: single definition (show() and base.js renderNoPersona share it).
   Two contracts, kept apart on purpose:
   (a) renderNoPersona must NOT fall back to the panel root — the content-less
       panels (chat/wiki/activity/timeline) manage their own DOM and a root
       fallback would wipe it (see base.test.js "0 personas" case).
   (b) show() DOES keep the root fallback for legacy behavior: a content-less
       panel without selfManaged still swaps its root to a skeleton on switch.
       Currently unreachable (all content-less tabs are selfManaged in
       dashboard.py) but preserved for compatibility.
   :scope > — content divs are direct children of their section; a descendant
   query could hit nested ids like #block-modal-content first. If a content div
   is ever nested deeper in a non-selfManaged panel, panelContentEl returns
   null and show() would skeleton the whole panel root — keep -content divs
   direct children, or make the tab selfManaged. */
function panelContentEl(panelId) {
  var container = document.getElementById("tab-" + panelId);
  return container ? container.querySelector(':scope > [id$="-content"]') : null;
}

/* ── Show skeleton for a given tab ── */
function show(tabId) {
  var navBtn = Array.from(document.querySelectorAll(".tab-btn")).find(function(b) { return b.dataset.tab === tabId; }) || null;
  if (navBtn && navBtn.dataset.selfManaged) return;

  /* Check registration first, then default */
  var skeletonHtml = _registry[tabId] || _defaults[tabId] ||
    '<div class="skeleton skeleton-card glass"></div>';

  /* Legacy fallback for (b): content-less panel still skeletons its root — see contract note above. */
  var content = panelContentEl(tabId) || document.getElementById("tab-" + tabId);
  if (!content) return;
  safeSetHTML(content, skeletonHtml);
}

/* ── Skeleton card HTML ── */
function skeletonCard() {
  return '<div class="glass p-6"><div class="skeleton skeleton-title"></div><div class="skeleton skeleton-text" style="width:80%"></div><div class="skeleton skeleton-text" style="width:60%"></div></div>';
}

/* ── Generate n skeleton cards ── */
function skeletonList(n) {
  var html = "";
  for (var i = 0; i < n; i++) {
    html += skeletonCard();
  }
  return html;
}

/* ── Error card with retry support (CSP-safe: delegation, no inline onclick) ── */
var _retrySeq = 0;
var _retryRegistry = {};
function errorCard(message, retryFn) {
  var html =
    '<div class="glass p-6 text-center skeleton-error-card"><p><i data-lucide="alert-triangle"></i></p><p>' +
    C.esc(message || "") +
    "</p>";
  if (typeof retryFn === "function") {
    _retrySeq += 1;
    var rid = "retry-" + _retrySeq + "-" + Date.now().toString(36);
    _retryRegistry[rid] = retryFn;
    html +=
      '<button type="button" class="glass-btn" data-skeleton-retry="' + rid + '"><i data-lucide="refresh-cw"></i> Retry</button>';
  }
  html += "</div>";
  return html;
}

/* ── Empty state display ── */
function emptyState(icon, title, description) {
  icon = icon || "inbox";
  title = title || "";
  description = description || "";
  return (
    '<div class="empty-state"><div class="empty-state-icon"><i data-lucide="' +
    C.esc(icon) +
    '"></i></div>' +
    (title ? '<div class="empty-state-text">' + C.esc(title) + "</div>" : "") +
    (description
      ? '<div style="font-size:0.85rem;color:var(--text-muted);margin-top:4px">' +
        C.esc(description) +
        "</div>"
      : "") +
    "</div>"
  );
}

/* ── Export ── */
if (typeof document !== "undefined" && !show._delegated) {
  show._delegated = true;
  document.addEventListener("click", function (e) {
    var btn = e.target && e.target.closest ? e.target.closest("[data-skeleton-retry]") : null;
    if (!btn) return;
    var rid = btn.getAttribute("data-skeleton-retry");
    var fn = rid && _retryRegistry[rid];
    if (typeof fn === "function") {
      try { fn(); } finally { delete _retryRegistry[rid]; }
    }
  });
}

/* ── Export ── */
N.Components.skeleton = {
  register: register,
  show: show,
  card: skeletonCard,
  list: skeletonList,
  errorCard: errorCard,
  emptyState: emptyState,
  panelContentEl: panelContentEl,
};

})(window.Nous);
