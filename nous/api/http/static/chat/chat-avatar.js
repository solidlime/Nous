/* =================================================================
   CHAT AVATAR — Integrates N.Avatar engine into chat sidebar panel

   Handles: init, config fetch, resize, toggle, localStorage persistence.
   T4 (avatar config API) is parallel — this module has safe defaults
   so it works before config endpoint exists.
   ================================================================= */
;(function(N) {
"use strict";

var S = window.S;
var LS_KEY_WIDTH = "nous_avatar_width";
var LS_KEY_VISIBLE = "nous_avatar_visible";

// --- Defaults (used when config endpoint unavailable) ---
var DEFAULTS = {
  enabled: false,
  panelWidth: 220,
  mouthMode: "toggle",
};

// --- State ---
var _panelEl = null;
var _containerEl = null;
var _resizeHandle = null;
var _toggleBtn = null;
var _resizeState = null; // { startX, startWidth }

// ------------------------------------------------------------------
// Config fetch (with fallback)
// ------------------------------------------------------------------

async function fetchAvatarConfig(persona) {
  if (!persona) return Object.assign({}, DEFAULTS);
  try {
    var resp = await fetch("/api/chat/" + encodeURIComponent(persona) + "/config");
    if (!resp.ok) return Object.assign({}, DEFAULTS);
    var data = await resp.json();
    var cfg = data.avatar || data.config && data.config.avatar || {};
    return {
      enabled: cfg.enabled === true,
      panelWidth: typeof cfg.panel_width === "number" ? cfg.panel_width : DEFAULTS.panelWidth,
      mouthMode: cfg.mouth_mode || DEFAULTS.mouthMode,
    };
  } catch (_) {
    return Object.assign({}, DEFAULTS);
  }
}

// ------------------------------------------------------------------
// localStorage helpers
// ------------------------------------------------------------------

function getSavedWidth() {
  var v = localStorage.getItem(LS_KEY_WIDTH);
  if (v) {
    var n = parseInt(v, 10);
    if (!isNaN(n) && n >= 120 && n <= 400) return n;
  }
  return null;
}

function saveWidth(w) {
  localStorage.setItem(LS_KEY_WIDTH, String(w));
}

function getSavedVisible() {
  return localStorage.getItem(LS_KEY_VISIBLE);
}

function saveVisible(v) {
  localStorage.setItem(LS_KEY_VISIBLE, v ? "1" : "0");
}

// ------------------------------------------------------------------
// Resize (pointer events)
// ------------------------------------------------------------------

function onResizeStart(e) {
  if (e.button !== 0) return; // left click only
  e.preventDefault();
  _resizeState = { startX: e.clientX, startWidth: _panelEl.offsetWidth };
  _resizeHandle.classList.add("active");
  document.addEventListener("pointermove", onResizeMove);
  document.addEventListener("pointerup", onResizeEnd);
}

function onResizeMove(e) {
  if (!_resizeState) return;
  var dx = e.clientX - _resizeState.startX;
  var newWidth = Math.min(400, Math.max(120, _resizeState.startWidth + dx));
  _panelEl.style.width = newWidth + "px";
}

function onResizeEnd() {
  if (!_resizeState) return;
  var finalWidth = _panelEl.offsetWidth;
  saveWidth(finalWidth);
  _resizeHandle.classList.remove("active");
  _resizeState = null;
  document.removeEventListener("pointermove", onResizeMove);
  document.removeEventListener("pointerup", onResizeEnd);
}

// ------------------------------------------------------------------
// Toggle visibility
// ------------------------------------------------------------------

function setPanelVisible(visible) {
  if (!_panelEl) return;
  _panelEl.style.display = visible ? "flex" : "none";
  saveVisible(visible);
  // Update toggle button icon
  if (_toggleBtn) {
    var icon = _toggleBtn.querySelector("i, svg");
    if (icon) {
      icon.setAttribute("data-lucide", visible ? "eye" : "eye-off");
      if (N.Core && N.Core.refreshIcons) N.Core.refreshIcons();
    }
  }
}

function togglePanel() {
  var isVisible = _panelEl && _panelEl.style.display !== "none";
  setPanelVisible(!isVisible);
}

// ------------------------------------------------------------------
// Initialization
// ------------------------------------------------------------------

async function initAvatar() {
  _panelEl = document.getElementById("avatar-panel");
  _containerEl = document.getElementById("avatar-container");
  _resizeHandle = document.getElementById("avatar-resize-handle");
  _toggleBtn = document.getElementById("avatar-toggle-btn");

  if (!_panelEl || !_containerEl) return;

  // Bind resize handle
  if (_resizeHandle) {
    _resizeHandle.addEventListener("pointerdown", onResizeStart);
  }

  // Bind toggle button
  if (_toggleBtn) {
    _toggleBtn.addEventListener("click", togglePanel);
  }

  // Fetch config
  var persona = S && S.persona;
  var config = await fetchAvatarConfig(persona);

  // Apply saved width (localStorage overrides config)
  var savedWidth = getSavedWidth();
  var width = savedWidth || config.panelWidth || DEFAULTS.panelWidth;
  _panelEl.style.width = width + "px";

  // Apply visibility: localStorage overrides config
  var savedVisible = getSavedVisible();
  var visible;
  if (savedVisible !== null) {
    visible = savedVisible === "1";
  } else {
    visible = config.enabled;
  }

  // Initialize avatar engine
  if (N.Avatar) {
    N.Avatar.init(_containerEl, {
      baseUrl: "",
      persona: persona || "",
      enabled: visible,
      panelWidth: width,
      mouthMode: config.mouthMode || DEFAULTS.mouthMode,
      onError: function(err) {
        console.warn("[chat-avatar] engine error:", err.message);
      },
    });
  }

  // Show/hide panel
  setPanelVisible(visible);
}

// ------------------------------------------------------------------
// Public API (expose for external hooks: T5/T6)
// ------------------------------------------------------------------

N.Chat.avatar = {
  init: initAvatar,
  toggle: togglePanel,
  setVisible: setPanelVisible,
  /** Call from TTS hook: startTalking/stopTalking */
  startTalking: function() { if (N.Avatar) N.Avatar.startTalking(); },
  stopTalking: function() { if (N.Avatar) N.Avatar.stopTalking(); },
  /** Call from emotion hook: setEmotion(name, intensity) */
  setEmotion: function(emotion, intensity) { if (N.Avatar) N.Avatar.setEmotion(emotion, intensity); },
};

// ------------------------------------------------------------------
// Hook into chat load
// ------------------------------------------------------------------

var _origLoadChat = null;
if (N.Chat.core && N.Chat.core.loadChat) {
  _origLoadChat = N.Chat.core.loadChat;
  N.Chat.core.loadChat = async function() {
    await _origLoadChat.call(this);
    initAvatar();
  };
}

})(window.Nous);
