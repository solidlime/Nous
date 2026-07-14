;/* =================================================================
   CHAT VOICE — Web Speech API voice input
   Extracted from chat.js (Phase 3c)
   ================================================================= */
(function(N) {
"use strict";

let _voiceRecognition = null;

function toggleVoiceInput() {
  const btn = document.getElementById("chat-voice-btn");
  if (!("webkitSpeechRecognition" in window || "SpeechRecognition" in window)) {
    toast("お使いのブラウザは音声入力に対応していません", "error");
    return;
  }
  const SpeechRecognition =
    window.SpeechRecognition || window.webkitSpeechRecognition;
  if (_voiceRecognition) {
    _voiceRecognition.stop();
    _voiceRecognition = null;
    if (btn) {
      btn.innerHTML = '<i data-lucide="mic"></i>';
      btn.style.color = "";
    }
    return;
  }
  _voiceRecognition = new SpeechRecognition();
  _voiceRecognition.lang = "ja-JP";
  _voiceRecognition.interimResults = false;
  _voiceRecognition.continuous = false;
  if (btn) {
    btn.innerHTML = '<i data-lucide="circle-dot"></i>';
    btn.style.color = "var(--accent-red)";
  }
  _voiceRecognition.onresult = (event) => {
    const transcript = event.results[0][0].transcript;
    const inputEl = document.getElementById("chat-input");
    if (inputEl) {
      inputEl.value = (inputEl.value ? inputEl.value + " " : "") + transcript;
      inputEl.dispatchEvent(new Event("input"));
    }
    _voiceRecognition = null;
    if (btn) {
      btn.innerHTML = '<i data-lucide="mic"></i>';
      btn.style.color = "";
    }
  };
  _voiceRecognition.onerror = () => {
    toast("音声認識エラー", "error");
    _voiceRecognition = null;
    if (btn) {
      btn.innerHTML = '<i data-lucide="mic"></i>';
      btn.style.color = "";
    }
  };
  _voiceRecognition.onend = () => {
    if (btn) {
      btn.innerHTML = '<i data-lucide="mic"></i>';
      btn.style.color = "";
    }
  };
  _voiceRecognition.start();
}

N.Chat.voice = {
  toggle: toggleVoiceInput,
};

window.toggleVoiceInput = toggleVoiceInput;

})(window.Nous);
