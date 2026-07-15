;/* =================================================================
   CHAT TTS — Voice model loading, test playback, TTS playback
   Extracted from chat.js (Phase 3c)
   ================================================================= */
(function(N) {
"use strict";
var S = window.S;

let _ttsAbortController = null;

/* ── Voice model loading & test playback ── */
async function loadVoiceModels(selectedId) {
  if (!S.persona) return;
  const select = document.getElementById("chat-voice-model");
  if (!select) return;
  try {
    const resp = await api("/api/tts/" + encodeURIComponent(S.persona) + "/voices");
    if (resp.voices && resp.voices.length > 0) {
      select.innerHTML = "";
      resp.voices.forEach(function (v) {
        var opt = document.createElement("option");
        opt.value = v.id;
        opt.textContent = v.name || v.id;
        select.appendChild(opt);
      });
      // Restore saved selection
      if (selectedId && select.querySelector('option[value="' + selectedId.replace(/"/g, '&quot;') + '"]')) {
        select.value = selectedId;
      }
    } else {
      select.innerHTML = '<option value="">音声モデルが見つかりません</option>';
    }
  } catch (e) {
    console.warn("[Voice] Failed to load models:", e.message);
    select.innerHTML = '<option value="">取得エラー</option>';
  }
}

async function testVoicePlayback() {
  if (!S.persona) return;
  var statusEl = document.getElementById("chat-voice-test-status");
  if (statusEl) statusEl.textContent = "合成中...";
  try {
    var resp = await api("/api/tts/" + encodeURIComponent(S.persona), {
      method: "POST",
      body: JSON.stringify({ text: "こんにちは、テストです。" }),
    });
    if (resp.audio_base64) {
      if (statusEl) statusEl.textContent = "再生中...";
      var audioUrl = "data:audio/" + (resp.format || "wav") + ";base64," + resp.audio_base64;
      var audio = new Audio(audioUrl);
      audio.onended = function () {
        if (statusEl) statusEl.textContent = "完了";
        setTimeout(function () { if (statusEl) statusEl.textContent = ""; }, 2000);
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

  api("/api/tts/" + encodeURIComponent(S.persona), {
    method: "POST",
    body: JSON.stringify({ text: plainText }),
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
    const resp = await api("/api/tts/" + encodeURIComponent(S.persona), {
      method: "POST",
      body: JSON.stringify({ text: plainText }),
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

N.Chat.tts = {
  loadVoices: loadVoiceModels,
  test: testVoicePlayback,
  play: playTts,
  autoPlay: autoPlayTts,
};

window.loadVoiceModels = loadVoiceModels;
window.testVoicePlayback = testVoicePlayback;
window.playTts = playTts;
window.autoPlayTts = autoPlayTts;

})(window.Nous);
