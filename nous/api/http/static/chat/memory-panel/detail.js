/* =================================================================
   CHAT MEMORY PANEL DETAIL — goal/promise panel detail modal
   Chunk 5/5 of chat-memory-panel.js. Namespace:
   N.Chat.memoryPanel.openPanelDetail / closePanelDetail.
   Depends on: components/mem-modal.js (memories/reflections route
   through the unified modal), chat-settings-image.js (fmtDateTime).
   ================================================================= */
;(function(N) {
var C = N.Core;
var api = C.api, esc = C.esc, toast = C.toast, safeSetHTML = C.safeSetHTML;
var showConfirm = C.showConfirm, showAlert = C.showAlert;
var truncate = C.truncate, relativeTime = C.relativeTime, fmtDate = C.fmtDate, fmtDateTime = C.fmtDateTime;
"use strict";
var S = window.S;

// ------------------------------------------------------------------
// Panel detail modal — goal / promise detail.
// Reuses the mem-modal vocabulary (.mem-modal-overlay / .mem-modal /
// mem-modal-row / ov-modal-actions) — zero new CSS. Goal/promise rows
// get 完了/削除 actions routed through the existing [data-mem-action]
// delegation (completeGoal → goal_manage achieve; deleteCard →
// DELETE /api/memories — promises are goals tagged goal/active/
// interpersonal, so both paths apply unchanged). Retrieved/saved/
// reflection rows go through the unified N.Components.memModal:
// complete key → open(key) (fresh fetch), partial data →
// openMemory(partial). Reflections carry full memory keys, so they
// open the rich memory modal, not this one.
// Non-blocking: focus + Escape + backdrop click + focus restore.
// ------------------------------------------------------------------
var _panelDetailOpener = null;
var PANEL_KIND_LABELS = { goal: "目標", promise: "約束" };

function _panelTagsHtml(tags) {
  return (tags || []).map(function (t) {
    var F = N.Features && N.Features.Memories;
    return F && typeof F.tagChipHtml === "function"
      ? F.tagChipHtml(t) : esc(t);
  }).join(" ");
}

function _panelAttrs(card) {
  return {
    key: card.getAttribute("data-key") || "",
    content: card.getAttribute("data-content") || "",
    importance: parseFloat(card.getAttribute("data-importance")),
    tags: (card.getAttribute("data-tags") || "").split(",").filter(Boolean),
    created_at: card.getAttribute("data-created") || null,
  };
}

function _panelDetailHTML(kind, item) {
  var h = '<div class="mem-modal">';
  h += '<div class="mem-modal-header"><div>';
  h += '<div class="mem-modal-kicker">' + esc(PANEL_KIND_LABELS[kind] || kind) + "</div>";
  if (item.key) {
    h += '<div class="mem-key-row"><span class="mem-key-mono">' + esc(item.key) + "</span></div>";
  }
  h += "</div>";
  h += '<button type="button" class="mem-modal-close" data-panel-detail-close aria-label="閉じる"><i data-lucide="x"></i></button>';
  h += "</div>";
  h += '<div class="mem-modal-body">' + esc(item.content || "") + "</div>";
  if (item.tags && item.tags.length) {
    h += '<div class="mem-modal-row"><span class="mem-modal-key">Tags</span><span>' +
      _panelTagsHtml(item.tags) + "</span></div>";
  }
  if (item.created_at) {
    h += '<div class="mem-modal-row"><span class="mem-modal-key">Created</span><span>' +
      esc(fmtDateTime(item.created_at)) + "</span></div>";
  }
  if (kind === "goal" || kind === "promise") {
    h += '<div class="ov-modal-actions">';
    h += '<button type="button" class="glass-btn glass-btn-success" data-mem-action="complete" data-mem-key="' +
      esc(item.key) + '" data-mem-content="' + esc((item.content || "").substring(0, 50)) + '">完了</button>';
    h += '<button type="button" class="glass-btn glass-btn-danger" data-mem-action="delete" data-mem-key="' +
      esc(item.key) + '">削除</button>';
    h += "</div>";
  }
  h += "</div>";
  return h;
}

function _panelDetailKeyHandler(e) {
  if (e.key === "Escape") closePanelDetail();
}

function openPanelDetail(card) {
  if (!card || !card.getAttribute) return;
  var kind = card.getAttribute("data-panel-kind");
  var item = _panelAttrs(card);
  // Reflections are memories (they carry a full memory key), so they go
  // through the unified memModal like memory rows — the sparse panel
  // modal is only for goal/promise, which are not memories.
  if (!kind || kind === "memory" || kind === "reflection") {
    if (item.key) N.Components.memModal.open(item.key);
    else N.Components.memModal.openMemory({
      content: item.content,
      importance: isNaN(item.importance) ? 0.5 : item.importance,
      tags: item.tags,
    });
    return;
  }
  var overlay = document.getElementById("panel-detail-overlay");
  if (!overlay) {
    overlay = document.createElement("div");
    overlay.id = "panel-detail-overlay";
    overlay.className = "mem-modal-overlay";
    overlay.setAttribute("role", "dialog");
    overlay.setAttribute("aria-modal", "true");
    document.body.appendChild(overlay);
    overlay.addEventListener("click", function (e) {
      if (e.target === overlay) closePanelDetail();
    });
  }
  overlay.setAttribute("aria-label", PANEL_KIND_LABELS[kind] || "詳細");
  _panelDetailOpener = document.activeElement;
  safeSetHTML(overlay, _panelDetailHTML(kind, item));
  // Force a reflow between insert and .show — same-frame open would
  // skip the fade/scale transition entirely (fresh element never got
  // a first paint at its hidden state).
  void overlay.offsetWidth;
  overlay.classList.add("show");
  document.removeEventListener("keydown", _panelDetailKeyHandler);
  document.addEventListener("keydown", _panelDetailKeyHandler);
  var closeBtn = overlay.querySelector("[data-panel-detail-close]");
  if (closeBtn) {
    closeBtn.addEventListener("click", function () { closePanelDetail(); });
    closeBtn.focus();
  }
  if (typeof N.Core.refreshIcons === "function") N.Core.refreshIcons();
}

function closePanelDetail() {
  var overlay = document.getElementById("panel-detail-overlay");
  if (!overlay || !overlay.classList.contains("show")) return;
  overlay.classList.remove("show");
  document.removeEventListener("keydown", _panelDetailKeyHandler);
  if (_panelDetailOpener && typeof _panelDetailOpener.focus === "function") {
    try { _panelDetailOpener.focus(); } catch (_) {}
  }
  _panelDetailOpener = null;
}
// ------------------------------------------------------------------
// Expose on N.Chat.memoryPanel (chunk 5/5 — panel detail modal)
// ------------------------------------------------------------------
Object.assign(N.Chat.memoryPanel, {
  openPanelDetail: openPanelDetail,
  closePanelDetail: closePanelDetail,
});
})(window.Nous);
