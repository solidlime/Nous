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

/* ── Body state bars for modals ── */
function renderBodyStateBars(bodyState) {
  if (!bodyState) return "";
  var keys = Object.keys(bodyState).filter(
    function (k) { return BODY_LABELS[k] && bodyState[k] != null; }
  );
  if (keys.length === 0) return "";
  var html =
    '<div class="mem-modal-row"><span class="mem-modal-key">Body</span><span style="display:flex;flex-direction:column;gap:6px;flex:1">';
  keys.forEach(function (k) {
    var val = bodyState[k];
    var color = BODY_BAR_COLORS[k] || BODY_BAR_COLORS.fatigue;
    var label = BODY_LABELS[k];
    var pct = Math.round(val * 100);
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

/* ── Emotion bar for modals ── */
function renderEmotionBars(emotion, emotion_intensity) {
  if (!emotion) return "";
  var pct = Math.round((emotion_intensity || 0) * 100);
  if (pct <= 0) return "";
  var color = EMOTION_BAR_COLORS[emotion] || EMOTION_BAR_COLORS.neutral;
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

/* ── Compact emotion badges for list/card views ── */
function renderEmotionBadges(emotion, emotion_intensity) {
  if (!emotion) return "";
  var pct = Math.round((emotion_intensity || 0) * 100);
  var color = EMOTION_COLORS[emotion] || "#94a3b8";
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
  renderEmotionBadges: renderEmotionBadges,
  renderBodyStateCompact: renderBodyStateCompact,
};

})(window.Nous);
