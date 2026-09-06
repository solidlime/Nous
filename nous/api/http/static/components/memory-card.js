/* =================================================================
   MEMORY CARD COMPONENT — N.Components.memoryCard
   ================================================================= */
;(function(N) {
"use strict";

var C = N.Core;
var esc = C.esc;
var EMOTION_BAR_COLORS = C.EMOTION_BAR_COLORS;
var EMOTION_COLORS = C.EMOTION_COLORS;
var BODY_BAR_COLORS = C.BODY_BAR_COLORS;
var BODY_LABELS = C.BODY_LABELS;

/* ── Post-render pass for sanitized HTML ──
   safeSetHTML strips style= attributes, so bars travel as data-fill /
   data-color and get their width/background applied here (JS-set styles
   are not sanitized). Call once after inserting generated HTML. */
function applyDataStyles(root) {
  var scope = root || document;
  var fills = scope.querySelectorAll("[data-fill]");
  for (var i = 0; i < fills.length; i++) {
    var el = fills[i];
    el.style.width = el.getAttribute("data-fill") + "%";
    var color = el.getAttribute("data-color");
    if (color) el.style.background = color;
  }
  var badges = scope.querySelectorAll("[data-color-base]");
  for (var j = 0; j < badges.length; j++) {
    var b = badges[j];
    var c = b.getAttribute("data-color-base");
    if (!c) continue;
    b.style.background = c + "22";
    b.style.color = c;
    b.style.border = "1px solid " + c + "44";
  }
  var chips = scope.querySelectorAll("[data-hue]");
  for (var k = 0; k < chips.length; k++) {
    chips[k].style.setProperty("--chip-hue", chips[k].getAttribute("data-hue"));
  }
}

/* Render helpers emit data-fill markup that consumers insert via
   safeSetHTML; schedule one debounced document-wide pass for the next
   frame instead of requiring every consumer to call applyDataStyles. */
var _applyQueued = false;
function scheduleApply() {
  if (_applyQueued) return;
  _applyQueued = true;
  requestAnimationFrame(function () {
    _applyQueued = false;
    applyDataStyles(document);
  });
}

/* ── Body state bars for modals ── */
function renderBodyStateBars(bodyState) {
  if (!bodyState) return "";
  var keys = Object.keys(bodyState).filter(
    function (k) { return BODY_LABELS[k] && bodyState[k] != null; }
  );
  if (keys.length === 0) return "";
  scheduleApply();
  var html =
    '<div class="mem-modal-row"><span class="mem-modal-key">Body</span><span class="mem-bar-stack">';
  keys.forEach(function (k) {
    var val = bodyState[k];
    var color = BODY_BAR_COLORS[k] || BODY_BAR_COLORS.fatigue;
    var label = BODY_LABELS[k];
    var pct = Math.round(val * 100);
    html += '<div class="mem-bar-row">';
    html += '<span class="mem-bar-label">' + label + '</span>';
    html += '<div class="mem-bar-track">';
    html +=
      '<div class="mem-bar-fill" data-fill="' + pct + '" data-color="' + color + '"></div>';
    html += "</div>";
    html += '<span class="mem-bar-pct">' + pct + "%</span>";
    html += "</div>";
  });
  html += "</span></div>";
  return html;
}

/* ── Emotion bar for modals ── */
function renderEmotionBars(emotion, emotion_intensity) {
  if (!emotion) return "";
  var pct = Math.round((emotion_intensity || 0) * 100);
  if (pct <= 0) return "";
  scheduleApply();
  var color = EMOTION_BAR_COLORS[emotion] || EMOTION_BAR_COLORS.neutral;
  return (
    '<div class="mem-modal-row"><span class="mem-modal-key">Emotion</span><span class="mem-bar-stack">' +
    '<div class="mem-bar-row">' +
    '<span class="mem-bar-label">' +
    esc(emotion) +
    "</span>" +
    '<div class="mem-bar-track">' +
    '<div class="mem-bar-fill" data-fill="' + pct + '" data-color="' + color + '"></div>' +
    "</div>" +
    '<span class="mem-bar-pct">' +
    pct +
    "%</span>" +
    "</div></span></div>"
  );
}

/* ── Importance bar for modals (purple→yellow, Memories-modal style) ── */
function renderImportanceBars(importance) {
  if (importance == null) return "";
  scheduleApply();
  return (
    '<div class="mem-modal-row"><span class="mem-modal-key">Importance</span><span class="modal-progress"><span class="modal-progress-bar wide"><span class="modal-progress-fill" data-fill="' +
    Math.round(importance * 100) +
    '" data-color="linear-gradient(90deg,var(--accent-purple),var(--accent-yellow))"></span></span><span class="mem-bar-pct ov-accent-yellow">' +
    importance.toFixed(2) +
    "</span></span></div>"
  );
}

/* ── Compact emotion badges for list/card views ── */
function renderEmotionBadges(emotion, emotion_intensity) {
  if (!emotion) return "";
  var pct = Math.round((emotion_intensity || 0) * 100);
  var color = EMOTION_COLORS[emotion] || "#94a3b8";
  scheduleApply();
  return (
    '<span class="mem-emo-badge" data-color-base="' + color + '">' +
    esc(emotion) +
    " " +
    pct +
    "%</span>"
  );
}

/* ── Compact body state indicator for list/card views ── */
function renderBodyStateCompact(bodyState) {
  if (!bodyState) return "";
  var keys = Object.keys(bodyState).filter(function (k) {
    return BODY_LABELS[k] && bodyState[k] != null && bodyState[k] > 0;
  });
  if (keys.length === 0) return "";
  var html = '<span style="font-size:0.65rem;color:var(--text-muted)">';
  keys.forEach(function (k) {
    var val = bodyState[k];
    var pct = Math.round(val * 100);
    var emoji = BODY_LABELS[k].split(" ")[0];
    html += emoji + pct + "% ";
  });
  html += "</span>";
  return html;
}

/* ── Export ── */
N.Components.memoryCard = {
  renderBodyStateBars: renderBodyStateBars,
  renderEmotionBars: renderEmotionBars,
  renderImportanceBars: renderImportanceBars,
  renderEmotionBadges: renderEmotionBadges,
  renderBodyStateCompact: renderBodyStateCompact,
  applyDataStyles: applyDataStyles,
};

})(window.Nous);
