;/* =================================================================
   CHAT TTS — Voice connection, model config, test playback, TTS playback
   Redesigned for per-persona Irodori server configuration
   ================================================================= */
(function(N) {
"use strict";
var S = window.S;

let _connectionCheckTimer = null;
let _playbackSession = null;    // { audio, btn, seekBar, interval } | null
let _autoplayUnlocked = false;
let _autoTtsAbort = null;       // AbortController for auto-play requests

/* ── Autoplay priming — unlock audio context on user gesture ── */
function _unlockAutoplay() {
  if (_autoplayUnlocked) return;
  _autoplayUnlocked = true;
  var silent = new Audio("data:audio/wav;base64,UklGRiQAAABXQVZFZm10IBAAAAABAAEARKwAAIhYAQACABAAZGF0YQAAAAA=");
  silent.play().then(function() { silent.pause(); }).catch(function() {});
}

/* ── Connection status indicator ── */
function _setStatus(state, text) {
  var el = document.getElementById("chat-voice-status");
  if (!el) return;
  el.className = "voice-status-" + state;
  var textEl = el.querySelector(".voice-status-text");
  if (textEl) textEl.textContent = text;
}

/* ── Debounce helper ── */
function _debounce(fn, ms) {
  var timer;
  return function() {
    clearTimeout(timer);
    timer = setTimeout(fn, ms);
  };
}

/* ── Volume helper ── */
function _getVolume() {
  var volEl = document.getElementById("chat-voice-volume");
  return volEl ? parseFloat(volEl.value) : 1.0;
}

/* ── Strip markdown for TTS ── */
function _stripMarkdown(text) {
  return text
    .replace(/```[\s\S]*?```/g, "コードブロック")
    .replace(/`([^`]+)`/g, "$1")
    .replace(/[*_~>#-]/g, "")
    .replace(/\[([^\]]+)\]\([^)]+\)/g, "$1")
    .replace(/「[^」]*」/g, "")
    .replace(/（[^）]*）/g, "")
    .replace(/[―─—]/g, "...")
    .trim();
}

/* ── Seekbar management ── */
function _createSeekBar(containerDiv) {
  var existing = containerDiv.querySelector(".tts-seekbar");
  if (existing) existing.remove();
  var bar = document.createElement("input");
  bar.type = "range";
  bar.className = "tts-seekbar";
  bar.min = "0";
  bar.max = "100";
  bar.value = "0";
  bar.style.width = "100%";
  bar.style.accentColor = "var(--accent-purple)";
  // 親div（chat-msg-actionsの外側、chat-bubbleのすぐ下）に挿入
  var actions = containerDiv.querySelector(".chat-msg-actions");
  if (actions) {
    actions.insertAdjacentElement("afterend", bar);
  } else {
    containerDiv.appendChild(bar);
  }
  return bar;
}

function _startSeekBar(audio, bar) {
  return setInterval(function() {
    if (!audio.duration || isNaN(audio.duration)) return;
    bar.max = audio.duration;
    bar.value = audio.currentTime;
  }, 50);
}

/* ── Session cleanup — single entry point ── */
function _endSession(reason) {
  var session = _playbackSession;
  if (!session) return;
  if (session.interval) clearInterval(session.interval);
  if (session.seekBar) session.seekBar.remove();
  var prompt = document.querySelector(".tts-play-prompt");
  if (prompt) prompt.remove();
  if (session.btn) {
    session.btn.classList.remove("playing");
    session.btn.innerHTML = '<i data-lucide="volume-2"></i>';
    if (typeof lucide !== "undefined") lucide.createIcons();
  }
  _playbackSession = null;
}

/* ── Play prompt for autoplay-blocked audio ── */
function _showPlayPrompt(containerDiv, audio, btn) {
  var prompt = document.createElement("div");
  prompt.className = "tts-play-prompt";
  prompt.textContent = "▶ タップで再生";
  prompt.onclick = function() {
    prompt.remove();
    audio.play().then(function() {
      if (!containerDiv.querySelector(".tts-seekbar")) {
        var seekBar = _createSeekBar(containerDiv);
        seekBar.oninput = function() { audio.currentTime = parseFloat(this.value); };
        var interval = _startSeekBar(audio, seekBar);
        if (_playbackSession) {
          _playbackSession.seekBar = seekBar;
          _playbackSession.interval = interval;
        }
      }
      if (btn) {
        btn.classList.add("playing");
        btn.innerHTML = '<i data-lucide="pause"></i>';
        if (typeof lucide !== "undefined") lucide.createIcons();
      }
    }).catch(function(err2) {
      console.error("[TTS] Play prompt failed:", err2);
      _endSession("play-prompt-failed");
    });
  };
  containerDiv.appendChild(prompt);
}

function _removeSeekBar() {
  _endSession("remove-seekbar");
}

/* ── Common audio setup ── */
function _setupAudio(audio, audioUrl, btn, containerDiv) {
  if (_playbackSession) _endSession("new-audio");
  
  audio.volume = _getVolume();
  var session = { audio: audio, btn: btn || null, seekBar: null, interval: null };
  
  if (containerDiv) {
    var seekBar = _createSeekBar(containerDiv);
    seekBar.oninput = function() {
      audio.currentTime = parseFloat(this.value);
    };
    session.seekBar = seekBar;
    session.interval = _startSeekBar(audio, seekBar);
  }
  
  // btn再生中状態
  if (btn) {
    btn.classList.add("playing");
    btn.innerHTML = '<i data-lucide="pause"></i>';
    btn.disabled = false;
    if (typeof lucide !== "undefined") lucide.createIcons();
  }
  
  audio.onended = function() {
    _endSession("ended");
  };
  
  audio.onerror = function() {
    console.error("[TTS] Audio playback error");
    _endSession("error");
  };
  
  _playbackSession = session;
  
  audio.play().catch(function(err) {
    console.warn("[TTS] Autoplay blocked:", err.message);
    if (containerDiv) {
      _showPlayPrompt(containerDiv, audio, btn);
    } else {
      _endSession("autoplay-blocked");
    }
  });
}

/* ── Check TTS server connection ── */
async function checkVoiceConnection() {
  if (!S.persona) return;
  _setStatus("checking", "接続確認中...");
  try {
    var resp = await api("/api/tts/" + encodeURIComponent(S.persona) + "/health");
    if (resp.ok && resp.connected) {
      _setStatus("connected", "接続中 — " + (resp.url || ""));
      // Auto-fill model if empty and models available
      var modelInput = document.getElementById("chat-voice-model");
      if (modelInput && !modelInput.value && resp.models && resp.models.length > 0) {
        modelInput.value = resp.models[0].id;
      }
    } else {
      var errMsg = resp.error || "サーバーに接続できません";
      _setStatus("disconnected", "未接続 — " + errMsg);
    }
  } catch (e) {
    _setStatus("disconnected", "未接続 — " + e.message);
  }
}

/* ── Test playback ── */
async function testVoicePlayback() {
  if (!S.persona) return;
  var statusEl = document.getElementById("chat-voice-test-status");
  if (statusEl) statusEl.textContent = "合成中...";
  try {
    var urlInput = document.getElementById("chat-voice-url");
    var modelInput = document.getElementById("chat-voice-model");
    var body = { text: "こんにちは、音声合成のテストです。正常に動作しています。" };
    if (modelInput && modelInput.value) {
      body.voice = modelInput.value;
    }
    var resp = await api("/api/tts/" + encodeURIComponent(S.persona), {
      method: "POST",
      body: JSON.stringify(body),
    });
    if (resp.audio_base64) {
      if (statusEl) statusEl.textContent = "再生中...";
      var audioUrl = resp.audio_url || ("data:audio/" + (resp.format || "wav") + ";base64," + resp.audio_base64);
      var audio = new Audio(audioUrl);
      audio.volume = _getVolume();
      audio.onended = function () {
        if (statusEl) statusEl.textContent = "✓ 完了";
        setTimeout(function () { if (statusEl) statusEl.textContent = ""; }, 3000);
      };
      audio.onerror = function () {
        if (statusEl) statusEl.textContent = "再生エラー";
      };
      audio.play().catch(function (err) {
        console.error("[Voice test] Play failed:", err);
        if (statusEl) statusEl.textContent = "再生エラー: " + err.message;
      });
    } else {
      if (statusEl) statusEl.textContent = "エラー: " + (resp.error || "不明");
    }
  } catch (e) {
    console.error("[Voice test] Error:", e);
    if (statusEl) statusEl.textContent = "エラー: " + e.message;
  }
}

/* ── Auto-play TTS on response ── */
function autoPlayTts(text) {
  if (!S.persona || !text) return;
  // Cancel any pending auto-play request
  if (_autoTtsAbort) _autoTtsAbort.abort();
  _autoTtsAbort = new AbortController();
  // Skip if already playing
  if (_playbackSession && _playbackSession.audio && !_playbackSession.audio.paused) return;

  // Strip markdown for TTS
  var plainText = _stripMarkdown(text);
  if (!plainText) return;

  var modelInput = document.getElementById("chat-voice-model");
  var body = { text: plainText };
  if (modelInput && modelInput.value) {
    body.voice = modelInput.value;
  }

  api("/api/tts/" + encodeURIComponent(S.persona), {
    method: "POST",
    body: JSON.stringify(body),
    signal: _autoTtsAbort.signal,
  })
    .then(function (resp) {
      if (resp.audio_base64) {
        var audioUrl = resp.audio_url || ("data:audio/" + (resp.format || "wav") + ";base64," + resp.audio_base64);
        var audio = new Audio(audioUrl);
        // Find the last assistant message for seekbar + TTS button
        var msgEls = document.querySelectorAll("#chat-messages .chat-msg");
        var msgEl = msgEls.length ? msgEls[msgEls.length - 1] : null;
        var ttsBtn = msgEl ? msgEl.querySelector(".chat-tts-btn") : null;
        _setupAudio(audio, audioUrl, ttsBtn, msgEl);
      }
    })
    .catch(function (e) {
      console.warn("[AutoTTS] Request failed:", e.message);
    });
}

/* ── Inline TTS playback (chat bubble button) ── */
async function playTts(btn, text) {
  if (!S.persona || !text) return;
  
  // 一時停止中の再開
  if (_playbackSession && _playbackSession.btn === btn && btn.classList.contains("playing")) {
    if (_playbackSession.audio.paused) {
      _playbackSession.audio.play();
      btn.innerHTML = '<i data-lucide="pause"></i>';
      if (typeof lucide !== "undefined") lucide.createIcons();
      return;
    }
  }
  
  // 再生中の一時停止
  if (_playbackSession && _playbackSession.btn === btn && !_playbackSession.audio.paused) {
    _playbackSession.audio.pause();
    btn.innerHTML = '<i data-lucide="play"></i>';
    if (typeof lucide !== "undefined") lucide.createIcons();
    return;
  }
  
  // 別の音声再生中は停止
  if (_playbackSession && _playbackSession.btn !== btn) {
    _endSession("other-audio");
  }
  
  // Strip markdown
  const plainText = _stripMarkdown(text);
  if (!plainText) return;
  
  btn.innerHTML = '<span class="tts-spinner"></span>';
  btn.disabled = true;
  
  try {
    var modelInput = document.getElementById("chat-voice-model");
    var body = { text: plainText };
    if (modelInput && modelInput.value) body.voice = modelInput.value;
    const resp = await api("/api/tts/" + encodeURIComponent(S.persona), {
      method: "POST",
      body: JSON.stringify(body),
    });
    if (resp.audio_base64) {
      const audioUrl = resp.audio_url || ("data:audio/" + (resp.format || "wav") + ";base64," + resp.audio_base64);
      const audio = new Audio(audioUrl);
      _setupAudio(audio, audioUrl, btn, btn.closest(".chat-msg"));
    } else {
      console.warn("[TTS] Synthesis failed:", resp.error || "unknown");
      btn.innerHTML = '<i data-lucide="volume-2"></i>';
      btn.disabled = false;
      if (typeof lucide !== "undefined") lucide.createIcons();
    }
  } catch (e) {
    console.error("[TTS] Request error:", e.message);
    btn.innerHTML = '<i data-lucide="volume-2"></i>';
    btn.disabled = false;
    if (typeof lucide !== "undefined") lucide.createIcons();
  }
}

/* ── Initialize: auto-check on section expand, debounce on URL change ── */
function initVoiceSection() {
  var section = document.getElementById("chat-voice-section");
  if (!section) return;

  // Check connection when details is toggled open
  section.addEventListener("toggle", function() {
    if (section.open) {
      checkVoiceConnection();
    }
  });

  // Prime autoplay on first user gesture
  ["click", "keydown", "touchstart"].forEach(function(ev) {
    document.addEventListener(ev, _unlockAutoplay, { once: true, passive: true });
  });

  // Debounced connection check when URL input changes
  var urlInput = document.getElementById("chat-voice-url");
  if (urlInput) {
    var debouncedCheck = _debounce(checkVoiceConnection, 500);
    urlInput.addEventListener("input", debouncedCheck);
  }

  // Real-time volume update: sync slider changes to currently playing audio
  var volSlider = document.getElementById("chat-voice-volume");
  if (volSlider) {
    volSlider.addEventListener("input", function() {
      if (_playbackSession && _playbackSession.audio) {
        _playbackSession.audio.volume = parseFloat(this.value);
      }
    });
  }
}

// Auto-init when DOM is ready
if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", initVoiceSection);
} else {
  initVoiceSection();
}

N.Chat.tts = {
  checkConnection: checkVoiceConnection,
  test: testVoicePlayback,
  play: playTts,
  autoPlay: autoPlayTts,
};

window.checkVoiceConnection = checkVoiceConnection;
window.testVoicePlayback = testVoicePlayback;
window.playTts = playTts;
window.autoPlayTts = autoPlayTts;

})(window.Nous);
