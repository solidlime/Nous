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
(function(N) {
"use strict";
var T = N.Chat.ttsStream;
var _stream = null;
function _postTts(stream, persona, text, voice, emotion, caption) {
  var body = { text: text };
  if (voice) body.voice = voice;
  if (emotion) body.emotion = emotion;
  if (caption) body.caption = caption;
  return N.Core.api("/api/tts/" + encodeURIComponent(persona), { method: "POST", body: JSON.stringify(body) }).then(function(resp) {
    if (stream !== _stream || stream.stopped) return resp; // #9: stale/superseded stream — drop side effects
    if (resp && !stream.firstResolved) {
      stream.firstResolved = true;
      if (resp.caption) { stream.caption = resp.caption; stream.emotion = resp.emotion || stream.emotion; }
      _flushHeld(stream); // #4: tone confirmed (or off-mode) — release held sentences
    }
    return resp;
  });
}
function _nextSentence(stream, sentence) {
  // #1/#2: single numbering authority for onDelta and finish.
  var idx = stream.sent;
  stream.sent++;
  stream.doneTexts.push(sentence);
  return idx;
}
function _send(stream, idx, sentence) {
  var cur = stream;
  var p = _postTts(cur, cur.persona, sentence, _voiceInput(), cur.emotion, cur.caption).then(function(resp) {
    if (cur !== _stream || cur.stopped) return resp;
    if (resp && resp.audio_url && cur.doneTexts[idx] === sentence) { // #5: drop superseded arrivals
      cur.files[idx] = resp.audio_url.split("/").pop();
    }
    return resp;
  });
  cur.all.push(p); // #3: completion tracking, never shifted
  cur.pending.push({ promise: p, idx: idx, sentence: sentence }); // playback queue
  _pump(cur);
}
function _voiceInput() {
  var modelInput = document.getElementById("chat-voice-model");
  return (modelInput && modelInput.value) ? modelInput.value : undefined;
}
function _enqueue(stream, sentence) {
  var idx = _nextSentence(stream, sentence);
  if (!stream.closing && idx > 0 && !stream.firstResolved) {
    stream.held.push({ idx: idx, sentence: sentence }); // #4: hold until tone confirmed
    return idx;
  }
  _send(stream, idx, sentence);
  return idx;
}
function _flushHeld(stream) {
  if (stream.flushed) return;
  stream.flushed = true;
  var held = stream.held;
  stream.held = [];
  for (var i = 0; i < held.length; i++) _send(stream, held[i].idx, held[i].sentence);
}
function _commonPrefix(a, b) {
  var n = 0;
  while (n < a.length && n < b.length && a[n] === b[n]) n++;
  return n;
}
function _stripForTts(text) {
  // Shared impl lives in chat-tts.js (same strip as the legacy one-shot path).
  var t = String(text || "");
  try {
    var f = N.Chat && N.Chat.tts && N.Chat.tts.stripMarkdown;
    if (typeof f === "function") t = f(text);
  } catch (e) {}
  // Punctuation-only residue (e.g. "." left by a stripped tag) speaks nothing.
  if (!/[\p{L}\p{N}]/u.test(t)) return "";
  return t;
}
function _advance(stream, sens, includeLast) {
  // Sanitize AFTER split (splitSentences itself is frozen): doneTexts and
  // the prefix check below both use this stripped array, so numbering and
  // the _send arrival guard stay consistent. Empties take no index.
  var clean = [];
  for (var i = 0; i < sens.length; i++) {
    var t = _stripForTts(sens[i]);
    if (t) clean.push(t);
  }
  sens = clean;
  // Positional enqueue over the prefix-verified range [k, end): entries
  // before k matched doneTexts, so nothing already sent is re-enqueued —
  // including textually identical repeats, which are distinct positions.
  var k = _commonPrefix(sens, stream.doneTexts);
  if (k > 0 && k < stream.doneTexts.length) {
    // Genuine boundary shift: the tail was superseded (it can never be
    // unsent, but in-flight arrivals self-discard via the _send guard).
    // k==0 with history means a fresh segment (tool-call bubble reset),
    // so it must NOT truncate — those sentences are still in flight.
    stream.doneTexts.length = k;
    stream.sent = k;
    stream.files.length = k;
  }
  var end = includeLast ? sens.length : sens.length - 1;
  for (var i = k; i < end; i++) _enqueue(stream, sens[i]);
}
T.startStream = function(persona) {
  if (N.Chat.tts && N.Chat.tts._endSession) { try { N.Chat.tts._endSession("stream-start"); } catch (e) {} }
  if (_stream) { try { T.stop(); } catch (e) {} } // #9: invalidate prior stream first
  _stream = { persona: persona, sent: 0, doneTexts: [], pending: [], all: [], held: [], files: [], audio: null, stopped: false, playing: false, caption: null, emotion: null, firstResolved: false, flushed: false, closing: false };
  return _stream;
};
T.onDelta = function(fullText) {
  var stream = _stream;
  if (!stream || stream.stopped) return;
  _advance(stream, T.splitSentences(fullText), false);
};
function _pump(stream) {
  stream = stream || _stream;
  if (!stream || stream.playing || stream.stopped) return;
  var entry = stream.pending.shift();
  if (!entry) return;
  stream.playing = true;
  entry.promise.then(function(resp) {
    if (stream.stopped || stream !== _stream) { stream.playing = false; return; }
    if (resp && resp.audio_url && stream.doneTexts[entry.idx] === entry.sentence) {
      var a = new Audio(resp.audio_url);
      stream.audio = a;
      a.onended = function() { stream.playing = false; _pump(stream); };
      a.onerror = function() { stream.playing = false; _pump(stream); };
      a.play().catch(function() { stream.playing = false; _pump(stream); });
    } else { stream.playing = false; _pump(stream); }
  }).catch(function() { stream.playing = false; if (stream === _stream && !stream.stopped) _pump(stream); });
}
T.finish = function(allText, msgEl) {
  var stream = _stream;
  if (!stream) return Promise.resolve(null);
  stream.closing = true;
  _flushHeld(stream);
  _advance(stream, T.splitSentences(allText), true);
  return Promise.allSettled(stream.all).then(function() { // #3: wait for ALL, not the shifted queue
    if (stream !== _stream) return { ok: false, error: "superseded" }; // #9
    if (stream.stopped) return { ok: false, error: "stopped" };
    var missing = [];
    for (var i = 0; i < stream.sent; i++) { if (!stream.files[i]) missing.push(i); }
    if (missing.length) {
      if (typeof console !== "undefined") console.warn("[TTS-stream] missing sentences, skip combine:", missing.join(","));
      return { ok: false, error: "missing sentences: " + missing.join(",") }; // #3: no silent partial combine
    }
    var files = stream.files.filter(Boolean);
    if (!files.length) return null;
    var modelInput = document.getElementById("chat-voice-model");
    var body = { files: files, fullText: allText };
    if (modelInput && modelInput.value) body.voice = modelInput.value;
    if (stream.emotion) body.emotion = stream.emotion;
    if (stream.caption) body.caption = stream.caption;
    return N.Core.api("/api/tts/" + encodeURIComponent(stream.persona) + "/combine", { method: "POST", body: JSON.stringify(body) }).then(function(resp) {
      if (stream === _stream && resp && resp.audio_url && msgEl) { msgEl.dataset.ttsCacheUrl = resp.audio_url; }
      return resp || null;
    }).catch(function(e) { console.warn("[TTS-stream] combine failed:", e.message); return null; });
  });
};
T.stop = function() {
  var stream = _stream;
  if (!stream) return;
  stream.stopped = true; // #9: late resolutions self-discard, _pump halts
  stream.pending = [];
  stream.held = [];
  try { if (stream.audio) stream.audio.pause(); } catch (e) {}
};
})(window.Nous);
