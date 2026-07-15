;/* =================================================================
   CHAT PORTRAIT — Persona portrait loading + display
   Extracted from chat.js (Phase 3c)
   ================================================================= */
(function(N) {
"use strict";
var S = window.S;

async function loadPortrait() {
  if (!S.persona) return;
  const container = document.getElementById("portrait-container");
  const img = document.getElementById("portrait-img");
  const placeholder = document.getElementById("portrait-placeholder");
  const status = document.getElementById("portrait-status");
  if (!container || !img || !placeholder || !status) return;

  status.textContent = "";
  status.className = "";

  try {
    const data = await api("/api/portrait/" + encodeURIComponent(S.persona));
    if (data.image_base64) {
      setPortraitImage(data.image_base64, data.emotion);
    } else if (data.fallback_emoji) {
      placeholder.textContent = data.fallback_emoji;
      placeholder.style.fontSize = "2.5rem";
    }
  } catch (e) {
    console.error("[loadPortrait] failed:", e);
    placeholder.textContent = "😐";
    placeholder.style.fontSize = "2.5rem";
    status.textContent = "";
    status.className = "";
  }
}

function setPortraitImage(base64, emotion) {
  const container = document.getElementById("portrait-container");
  const img = document.getElementById("portrait-img");
  const placeholder = document.getElementById("portrait-placeholder");
  const status = document.getElementById("portrait-status");
  if (!container || !img) return;

  img.src = "data:image/png;base64," + base64;
  img.style.display = "block";
  if (placeholder) placeholder.style.display = "none";
  img.classList.remove("fade-in");
  void img.offsetWidth; // trigger reflow
  img.classList.add("fade-in");
  if (status) {
    status.textContent = "";
    status.className = "";
  }

  // Set emotion border color
  if (emotion && EMOTION_COLORS[emotion]) {
    container.classList.add("has-emotion");
    container.style.setProperty(
      "--portrait-emotion-color",
      EMOTION_COLORS[emotion],
    );
  } else {
    container.classList.remove("has-emotion");
    container.style.removeProperty("--portrait-emotion-color");
  }
}

function onPortraitClick() {
  const img = document.getElementById("portrait-img");
  if (img && img.style.display !== "none" && img.src) {
    openMediaViewer(img.src, "image");
  }
}

N.Chat.portrait = {
  load: loadPortrait,
};

window.loadPortrait = loadPortrait;
window.setPortraitImage = setPortraitImage;
window.onPortraitClick = onPortraitClick;

})(window.Nous);
