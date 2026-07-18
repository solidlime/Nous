;/* =================================================================
   CHAT TTS — Voice connection, model config, test playback, TTS playback
   Redesigned for per-persona Irodori server configuration
   ================================================================= */
(function(N) {
"use strict";
var S = window.S;

let _ttsAbortController = null;
let _connectionCheckTimer = null;

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
      var audioUrl = "data:audio/" + (resp.format || "wav") + ";base64," + resp.audio_base64;
      var audio = new Audio(audioUrl);
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
  // Strip markdown for TTS
  var plainText = text
    .replace(/```[\s\S]*?```/g, "コードブロック")
    .replace(/`([^`]+)`/g, "$1")
    .replace(/[*_~>#-]/g, "")
    .replace(/\[([^\]]+)\]\([^)]+\)/g, "$1")
    .trim();
  if (!plainText) return;

  var modelInput = document.getElementById("chat-voice-model");
  var body = { text: plainText };
  if (modelInput && modelInput.value) {
    body.voice = modelInput.value;
  }

  api("/api/tts/" + encodeURIComponent(S.persona), {
    method: "POST",
    body: JSON.stringify(body),
  })
    .then(function (resp) {
    if (resp.audio_base64) {
        var audioUrl = "data:audio/" + (resp.format || "wav") + ";base64," + resp.audio_base64;
        var audio = new Audio(audioUrl);
        audio.play().catch(function (err) {
          console.warn("[AutoTTS] Play failed:", err.message);
        });
      }
    })
    .catch(function (e) {
      console.warn("[AutoTTS] Request failed:", e.message);
    });
}

/* ── Inline TTS playback (chat bubble button) ── */
async function playTts(btn, text) {
  if (!S.persona || !text) return;
  // If already playing, stop
  if (btn.classList.contains("playing")) {
    btn.classList.remove("playing");
    btn.innerHTML = '<i data-lucide="volume-2"></i>';
    if (typeof lucide !== "undefined") lucide.createIcons();
    if (_ttsAbortController) {
      _ttsAbortController.abort();
      _ttsAbortController = null;
    }
    return;
  }

  // Strip markdown-like formatting for TTS
  const plainText = text
    .replace(/```[\s\S]*?```/g, "コードブロック")
    .replace(/`([^`]+)`/g, "$1")
    .replace(/[*_~>#-]/g, "")
    .replace(/\[([^\]]+)\]\([^)]+\)/g, "$1")
    .trim();
  if (!plainText) return;

  btn.innerHTML = '<span class="tts-spinner"></span>';
  btn.disabled = true;

  try {
    var modelInput = document.getElementById("chat-voice-model");
    var body = { text: plainText };
    if (modelInput && modelInput.value) {
      body.voice = modelInput.value;
    }
    const resp = await api("/api/tts/" + encodeURIComponent(S.persona), {
      method: "POST",
      body: JSON.stringify(body),
    });
    const audioBase64 = resp.audio_base64;
    if (audioBase64) {
      btn.classList.add("playing");
      btn.innerHTML = '<i data-lucide="volume-2"></i>';
      btn.disabled = false;
      if (typeof lucide !== "undefined") lucide.createIcons();

      const audioUrl =
        "data:audio/" + (resp.format || "wav") + ";base64," + audioBase64;
      const audio = new Audio(audioUrl);
      audio.onended = function () {
        btn.classList.remove("playing");
        btn.innerHTML = '<i data-lucide="volume-2"></i>';
        if (typeof lucide !== "undefined") lucide.createIcons();
      };
      audio.onerror = function () {
        btn.classList.remove("playing");
        btn.innerHTML = '<i data-lucide="volume-2"></i>';
        if (typeof lucide !== "undefined") lucide.createIcons();
        console.error("[TTS] Audio playback error");
      };
      audio.play().catch(function (err) {
        console.error("[TTS] Play failed:", err);
        btn.classList.remove("playing");
        btn.innerHTML = '<i data-lucide="volume-2"></i>';
        if (typeof lucide !== "undefined") lucide.createIcons();
      });
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

  // Debounced connection check when URL input changes
  var urlInput = document.getElementById("chat-voice-url");
  if (urlInput) {
    var debouncedCheck = _debounce(checkVoiceConnection, 500);
    urlInput.addEventListener("input", debouncedCheck);
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
