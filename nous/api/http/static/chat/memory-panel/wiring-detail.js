/* =================================================================
   CHAT MEMORY PANEL WIRING-DETAIL — fire detail modal viewer
   Chunk 4/5 of chat-memory-panel.js. Namespace:
   N.Chat.memoryPanel.openWiringDetail / closeWiringDetail.
   Depends on: memory-panel/wiring.js (N.Chat.memoryPanel._wiring),
   components/memory-card.js, chat-settings-image.js (fmtDateTime).
   ================================================================= */
;(function(N) {
var C = N.Core;
var api = C.api, esc = C.esc, toast = C.toast, safeSetHTML = C.safeSetHTML;
var showConfirm = C.showConfirm, showAlert = C.showAlert;
var truncate = C.truncate, relativeTime = C.relativeTime, fmtDate = C.fmtDate, fmtDateTime = C.fmtDateTime;
"use strict";
var S = window.S;

// Internal cross-chunk table registered by memory-panel/wiring.js.
var W = (N.Chat.memoryPanel && N.Chat.memoryPanel._wiring) || {};

// ------------------------------------------------------------------
// Fire detail modal — reuses the .ov-modal system (sanitizer-safe:
// class-based markup + data-fill bars via memoryCard.applyDataStyles).
// Non-blocking viewer: focus + Escape + overlay click + focus restore.
// ------------------------------------------------------------------
var _wiringDetailOpener = null;

function _wiringFindEvent(key) {
  for (var i = 0; i < W.events.length; i++) {
    if (W.events[i].source === key || W.events[i].target === key) {
      return W.events[i];
    }
  }
  return null;
}

function _wiringDetailHTML(key, mem, ev, failed) {
  var h = '<div class="ov-modal wide">';
  h += '<div class="wiring-detail-head">';
  if (ev) {
    h += '<span class="wiring-kind-badge">' +
      esc(W.kinds[ev.kind] || String(ev.kind)) + "</span>";
    var w = Number(ev.weight);
    if (isFinite(w)) {
      h += '<span class="mem-bar-pct">weight ' + esc(w.toFixed(2)) + "</span>";
    }
  }
  h += '<button type="button" class="mem-modal-close" data-action="wiring-close" aria-label="閉じる"><i data-lucide="x"></i></button>';
  h += "</div>";
  h += '<div class="wiring-detail-content">';
  if (mem && mem.content) {
    h += '<div class="wiring-detail-text">' + esc(W.summary(mem)) + "</div>";
  } else if (failed) {
    h += '<div class="memory-empty">記憶の詳細を取得できませんでした</div>';
  } else {
    h += '<div class="memory-empty">読み込み中…</div>';
  }
  h += "</div>";
  if (mem) {
    h += '<div class="mem-modal-row"><span class="mem-modal-key">種別</span><span class="badge badge-purple">' +
      esc(mem.kind || "memory") + "</span></div>";
    h += N.Components.memoryCard.renderImportanceBars(mem.importance);
    var tags = mem.tags || [];
    if (tags.length) {
      h += '<div class="mem-modal-row"><span class="mem-modal-key">Tags</span><span class="wiring-detail-tags">' +
        tags.map(function (t) {
          return N.Features.Memories.tagChipHtml(t);
        }).join("") + "</span></div>";
    }
    var rel = mem.related_keys || [];
    if (rel.length) {
      h += '<div class="mem-modal-row"><span class="mem-modal-key">関連</span><span class="wiring-detail-tags">' +
        rel.map(function (rk) {
          return '<span class="wiring-detail-chip" title="' + esc(rk) + '">' +
            esc(W.keyShort(rk)) + "</span>";
        }).join("") + "</span></div>";
    }
    if (mem.created_at) {
      h += '<div class="mem-modal-row"><span class="mem-modal-key">Created</span><span>' +
        esc(fmtDateTime(mem.created_at)) + "</span></div>";
    }
    if (mem.updated_at && mem.updated_at !== mem.created_at) {
      h += '<div class="mem-modal-row"><span class="mem-modal-key">Updated</span><span>' +
        esc(fmtDateTime(mem.updated_at)) + "</span></div>";
    }
  }
  if (ev && (ev.source || ev.target)) {
    h += '<div class="mem-modal-row"><span class="mem-modal-key">Edge</span><span class="mem-key-mono wiring-edge-detail">' +
      esc(ev.source + " → " + ev.target) + "</span></div>";
  }
  h += "</div>";
  return h;
}

function _wiringPaintDetail(overlay, key, ev, mem, failed) {
  safeSetHTML(overlay, _wiringDetailHTML(key, mem, ev, failed));
  W.applyFills(overlay);
  // Close button closes via delegation (data-action="wiring-close").
  if (typeof N.Core.refreshIcons === "function") N.Core.refreshIcons();
}

function openWiringDetail(key) {
  if (!key) return;
  var overlay = document.getElementById("wiring-detail-overlay");
  if (!overlay) {
    overlay = document.createElement("div");
    overlay.id = "wiring-detail-overlay";
    overlay.className = "ov-modal-overlay";
    overlay.setAttribute("role", "dialog");
    overlay.setAttribute("aria-modal", "true");
    overlay.setAttribute("aria-label", "発火した記憶の詳細");
    document.body.appendChild(overlay);
    overlay.addEventListener("click", function (e) {
      if (e.target === overlay) closeWiringDetail();
    });
  }
  var ev = _wiringFindEvent(key);
  _wiringDetailOpener = document.activeElement;
  _wiringPaintDetail(overlay, key, ev, W.memCache[key] || null, false);
  overlay.classList.add("active");
  var closeBtn = overlay.querySelector("[data-wiring-close]");
  if (closeBtn) closeBtn.focus();
  if (!W.memCache[key] && !W.memFailed[key]) {
    var repaint = function () {
      var ov = document.getElementById("wiring-detail-overlay");
      if (ov && ov.classList.contains("active")) {
        _wiringPaintDetail(ov, key, _wiringFindEvent(key), W.memCache[key] || null, true);
      }
    };
    if (W.memPending[key]) W.memPending[key].then(repaint);
    else W.ensureMemories([{ source: key, target: "" }], repaint);
  }
}

function closeWiringDetail() {
  var overlay = document.getElementById("wiring-detail-overlay");
  if (overlay) overlay.classList.remove("active");
  if (_wiringDetailOpener && typeof _wiringDetailOpener.focus === "function") {
    try { _wiringDetailOpener.focus(); } catch (_) {}
  }
  _wiringDetailOpener = null;
}

// CSP delegation moved to core/delegation.js:
//   click  [data-wiring-open]        → openWiringDetail (edge modal)
//   click  [data-action=wiring-open-memory] → N.Components.memModal.open
//   click  [data-action=wiring-close] → closeWiringDetail
//   keydown Escape (overlay open)    → closeWiringDetail
//   keydown Enter/Space on rows      → openWiringDetail
// ------------------------------------------------------------------
// Expose on N.Chat.memoryPanel (chunk 4/5 — fire detail modal)
// ------------------------------------------------------------------
Object.assign(N.Chat.memoryPanel, {
  openWiringDetail: openWiringDetail,
  closeWiringDetail: closeWiringDetail,
});
})(window.Nous);
