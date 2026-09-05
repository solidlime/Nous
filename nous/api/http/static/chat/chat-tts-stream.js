/* CHAT TTS STREAM — single-request SSE relay playback */
(function(N) {
"use strict";
var T = N.Chat.ttsStream = N.Chat.ttsStream || {};
var _stream = null;
function _voiceInput() {
  var el = document.getElementById("chat-voice-model");
  return (el && el.value) ? el.value : undefined;
}
function _strip(text) {
  var t = String(text || "");
  try {
    var f = N.Chat && N.Chat.tts && N.Chat.tts.stripMarkdown;
    if (typeof f === "function") t = f(text);
  } catch (e) {}
  if (!/[\p{L}\p{N}]/u.test(t)) return "";
  return t;
}
function _playNext(stream) {
  if (!stream || stream.stopped || stream.playing) return;
  var url = stream.queue.shift();
  if (!url || stream !== _stream) return;
  stream.playing = true;
  var a = new Audio(url);
  try {
    var g = N.Chat.tts && N.Chat.tts.getVolume;
    a.volume = (typeof g === "function") ? g() : 1.0;
  } catch (_e) {}
  stream.audio = a;
  a.onended = function() { stream.playing = false; _playNext(stream); };
  a.onerror = function() { stream.playing = false; _playNext(stream); };
  try {
    var p = a.play();
    if (p && p.catch) p.catch(function() { stream.playing = false; _playNext(stream); });
  } catch (_e2) { stream.playing = false; _playNext(stream); }
}
T.startStream = function(persona) {
  if (N.Chat.tts && N.Chat.tts._endSession) { try { N.Chat.tts._endSession("stream-start"); } catch (e) {} }
  if (_stream) { try { T.stop(); } catch (_e2) {} }
  _stream = { persona: persona, stopped: false, audio: null, ctrl: null, queue: [], playing: false, done: false };
  return _stream;
};
T.finish = function(allText, msgEl) {
  var stream = _stream;
  if (!stream) return Promise.resolve(null);
  var text = _strip(allText);
  if (!text) return Promise.resolve(null);
  var ctrl = (typeof AbortController !== "undefined") ? new AbortController() : null;
  stream.ctrl = ctrl;
  var body = { text: text };
  var v = _voiceInput();
  if (v) body.voice = v;
  return fetch("/api/tts/" + encodeURIComponent(stream.persona) + "/stream", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    signal: ctrl ? ctrl.signal : undefined
  }).then(function(resp) {
    if (!resp.ok) throw new Error("HTTP " + resp.status);
    var reader = resp.body.getReader();
    var decoder = new TextDecoder();
    var buf = "";
    var result = null;
    function onEvent(obj) {
      if (!obj || stream !== _stream || stream.stopped) return;
      if (obj.type === "tts_chunk" && obj.audio_base64) {
        try {
          var bin = atob(obj.audio_base64);
          var bytes = new Uint8Array(bin.length);
          for (var i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
          stream.queue.push(URL.createObjectURL(new Blob([bytes], { type: "audio/wav" })));
          _playNext(stream);
        } catch (_e) {}
      } else if (obj.type === "tts_done") {
        stream.done = true;
        if (obj.audio_url && msgEl) { try { msgEl.dataset.ttsCacheUrl = obj.audio_url; } catch (_e2) {} }
        result = obj;
      } else if (obj.type === "tts_error") {
        if (typeof console !== "undefined") console.warn("[TTS-stream]", obj.message || "stream error");
      }
    }
    function pump() {
      return reader.read().then(function(r) {
        if (r.done) return result;
        buf += decoder.decode(r.value, { stream: true });
        var lines = buf.split("\n");
        buf = lines.pop();
        for (var i = 0; i < lines.length; i++) {
          if (lines[i].indexOf("data: ") !== 0) continue;
          try { onEvent(JSON.parse(lines[i].slice(6))); } catch (_e) {}
        }
        return pump();
      });
    }
    return pump();
  }).catch(function(e) {
    if (e && e.name === "AbortError") return null;
    if (typeof console !== "undefined") console.warn("[TTS-stream] fetch failed:", e && e.message);
    return null;
  });
};
T.stop = function() {
  var stream = _stream;
  if (!stream) return;
  stream.stopped = true;
  stream.queue = [];
  try { if (stream.ctrl) stream.ctrl.abort(); } catch (e) {}
  try { if (stream.audio) stream.audio.pause(); } catch (_e) {}
};
})(window.Nous);
