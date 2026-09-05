/* =================================================================
   SKELETON LOADING COMPONENT — N.Components.skeleton
   ================================================================= */
;(function(N) {
"use strict";

var C = N.Core;
var safeSetHTML = C.safeSetHTML;

/* ── Registration store (tabId → skeleton HTML) ── */
var _registry = {};

/* ── Default skeleton HTML for each tab (used when no registration) ── */
var _defaults = {
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
  activity: '<div class="skeleton glass" style="height:300px"></div>',
};

/* ── Tabs that manage their own loading state (should not be skeleton-replaced) ── */
var _selfManaged = new Set([
  "graph",
  "import-export",
  "personas",
  "chat",
  "timeline",
  "activity",
]);

/* ── Register a custom skeleton config for a tab ── */
function register(tabId, config) {
  _registry[tabId] = config;
}

/* ── Show skeleton for a given tab ── */
function show(tabId) {
  var container = document.getElementById("tab-" + tabId);
  if (!container) return;

  /* Self-managed tabs handle their own loading */
  if (_selfManaged.has(tabId)) return;

  /* Check registration first, then default */
  var skeletonHtml = _registry[tabId] || _defaults[tabId] ||
    '<div class="skeleton skeleton-card glass"></div>';

  var content = container.querySelector('[id$="-content"]') || container;
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
};

})(window.Nous);
