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
function _postTts(persona, text, voice, emotion, caption) {
  var body = { text: text };
  if (voice) body.voice = voice;
  if (emotion) body.emotion = emotion;
  if (caption) body.caption = caption;
  return N.Core.api("/api/tts/" + encodeURIComponent(persona), { method: "POST", body: JSON.stringify(body) }).then(function(resp) {
    if (resp && _stream && !_stream.caption && resp.caption) { _stream.caption = resp.caption; _stream.emotion = resp.emotion || _stream.emotion; }
    return resp;
  });
}
T.startStream = function(persona) {
  if (N.Chat.tts && N.Chat.tts._endSession) { try { N.Chat.tts._endSession("stream-start"); } catch (e) {} }
  _stream = { persona: persona, sent: 0, doneTexts: [], pending: [], files: [], audio: null, stopped: false, playing: false, caption: null, emotion: null };
  return _stream;
};
T.onDelta = function(fullText) {
  if (!_stream || _stream.stopped) return;
  var sens = T.splitSentences(fullText);
  while (_stream.sent < sens.length - 1) {
    (function(idx, sentence) {
      _stream.sent++;
      _stream.doneTexts.push(sentence);
      var modelInput = document.getElementById("chat-voice-model");
      var voice = modelInput && modelInput.value ? modelInput.value : undefined;
      _stream.pending.push(_postTts(_stream.persona, sentence, voice, _stream.emotion, _stream.caption).then(function(resp) {
        if (resp && resp.audio_url) _stream.files[idx] = resp.audio_url.split("/").pop();
        return resp;
      }));
      _pump();
    })(_stream.doneTexts.length - 1, sens[_stream.sent]);
  }
};
function _pump() {
  if (!_stream || _stream.playing || _stream.stopped) return;
  var next = _stream.pending.shift();
  if (!next) return;
  _stream.playing = true;
  next.then(function(resp) {
    if (_stream.stopped) { _stream.playing = false; return; }
    if (resp && resp.audio_url) {
      var a = new Audio(resp.audio_url);
      _stream.audio = a;
      a.onended = function() { _stream.playing = false; _pump(); };
      a.onerror = function() { _stream.playing = false; _pump(); };
      a.play().catch(function() { _stream.playing = false; _pump(); });
    } else { _stream.playing = false; _pump(); }
  }).catch(function() { _stream.playing = false; _pump(); });
}
T.finish = function(allText, msgEl) {
  if (!_stream) return Promise.resolve(null);
  var sens = T.splitSentences(allText);
  while (_stream.sent < sens.length) {
    (function(idx, sentence) {
      _stream.sent++;
      var modelInput = document.getElementById("chat-voice-model");
      var voice = modelInput && modelInput.value ? modelInput.value : undefined;
      _stream.pending.push(_postTts(_stream.persona, sentence, voice, _stream.emotion, _stream.caption).then(function(resp) {
        if (resp && resp.audio_url) _stream.files[idx] = resp.audio_url.split("/").pop();
        return resp;
      }));
    })(_stream.doneTexts.length, sens[_stream.sent]);
  }
  return Promise.allSettled(_stream.pending).then(function() {
    var files = _stream.files.filter(Boolean);
    if (!files.length) return null;
    var modelInput = document.getElementById("chat-voice-model");
    var body = { files: files, fullText: allText };
    if (modelInput && modelInput.value) body.voice = modelInput.value;
    if (_stream.emotion) body.emotion = _stream.emotion;
    if (_stream.caption) body.caption = _stream.caption;
    return N.Core.api("/api/tts/" + encodeURIComponent(_stream.persona) + "/combine", { method: "POST", body: JSON.stringify(body) }).then(function(resp) {
      if (resp && resp.audio_url && msgEl) { msgEl.dataset.ttsCacheUrl = resp.audio_url; }
      return resp || null;
    }).catch(function(e) { console.warn("[TTS-stream] combine failed:", e.message); return null; });
  });
};
T.stop = function() { if (_stream) { _stream.stopped = true; try { _stream.audio && _stream.audio.pause(); } catch (e) {} } };
})(window.Nous);
