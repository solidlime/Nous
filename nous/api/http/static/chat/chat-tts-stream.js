/* CHAT TTS STREAM — sentence split + queued playback + combine */
(function(N) {
"use strict";
function splitSentencesFallback(text) {
  var parts = String(text || "").split(/(\n+|.*?[。！？!?…]+[」』）)\]]*|.*?[.!?]+(?=\s+[A-Z0-9「『]|$))/g);
  var out = [];
  for (var i = 0; i < parts.length; i++) {
    var s = (parts[i] || "").trim();
    if (s) out.push(s);
  }
  var merged = [];
  for (var j = 0; j < out.length; j++) {
    var cur = out[j];
    if (cur.length < 20 && j + 1 < out.length) { out[j + 1] = cur + " " + out[j + 1]; continue; }
    if (cur.length > 200) {
      var hard = cur.split(/(?<=[、，,])/g);
      var acc = "";
      for (var k = 0; k < hard.length; k++) {
        acc += hard[k];
        if (acc.length >= 100 || k === hard.length - 1) { merged.push(acc.trim()); acc = ""; }
      }
      if (acc.trim()) merged.push(acc.trim());
    } else { merged.push(cur); }
  }
  return merged.filter(Boolean);
}
function splitSentences(text) {
  var src = String(text || "");
  if (!src.trim()) return [];
  try {
    if (typeof Intl !== "undefined" && Intl.Segmenter) {
      var seg = new Intl.Segmenter(undefined, { granularity: "sentence" });
      var raw = [];
      var it = seg.segment(src)[Symbol.iterator]();
      var r;
      while (!(r = it.next()).done) { var s = (r.value.segment || "").trim(); if (s) raw.push(s); }
      if (raw.length) {
        var merged = [];
        for (var i = 0; i < raw.length; i++) {
          var cur = raw[i];
          if (cur.length < 20 && i + 1 < raw.length) { raw[i + 1] = cur + " " + raw[i + 1]; continue; }
          merged.push(cur);
        }
        return merged.filter(Boolean);
      }
    }
  } catch (e) { console.warn("[TTS-stream] Segmenter failed, fallback:", e.message); }
  return splitSentencesFallback(src);
}
N.Chat = N.Chat || {};
N.Chat.ttsStream = N.Chat.ttsStream || {};
N.Chat.ttsStream.splitSentences = splitSentences;
})(window.Nous);
