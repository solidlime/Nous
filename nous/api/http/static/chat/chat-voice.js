;/* =================================================================
   CHAT VOICE — Web Speech API voice input
   Extracted from chat.js (Phase 3c)
   ================================================================= */
(function(N) {
"use strict";
var C = N.Core;
var esc = C.esc, toast = C.toast, safeSetHTML = C.safeSetHTML;

let _voiceRecognition = null;
let _voiceBaseText = "";

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
    _voiceBaseText = "";
    if (btn) {
      safeSetHTML(btn, '<i data-lucide="mic"></i>');
      btn.style.color = "";
    }
    return;
  }
  _voiceRecognition = new SpeechRecognition();
  _voiceRecognition.lang = "ja-JP";
  _voiceRecognition.interimResults = true;
  _voiceRecognition.continuous = true;
  if (btn) {
    safeSetHTML(btn, '<i data-lucide="circle-dot"></i>');
    btn.style.color = "var(--accent-red)";
  }
  _voiceRecognition.onresult = (event) => {
    const inputEl = document.getElementById("chat-input");
    if (!inputEl) return;
    let interimText = "";
    let finalText = "";
    for (let i = event.resultIndex; i < event.results.length; i++) {
      const result = event.results[i];
      if (result.isFinal) {
        finalText += result[0].transcript;
      } else {
        interimText += result[0].transcript;
      }
    }
    if (finalText) {
      _voiceBaseText += (_voiceBaseText ? " " : "") + finalText;
    }
    inputEl.value = _voiceBaseText + (interimText ? " " + interimText : "");
    inputEl.dispatchEvent(new Event("input"));
  };
  _voiceRecognition.onerror = () => {
    toast("音声認識エラー", "error");
    _voiceRecognition = null;
    if (btn) {
      safeSetHTML(btn, '<i data-lucide="mic"></i>');
      btn.style.color = "";
    }
  };
  _voiceRecognition.onend = () => {
    _voiceRecognition = null;
    if (btn) {
      safeSetHTML(btn, '<i data-lucide="mic"></i>');
      btn.style.color = "";
    }
  };
  _voiceRecognition.start();
}

N.Chat.voice = {
  toggle: toggleVoiceInput,
};

})(window.Nous);
