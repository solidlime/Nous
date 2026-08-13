/* =================================================================
   AVATAR ENGINE — PNGTuber avatar display for N.Avatar namespace

   Pure logic (URL resolution, emotion mapping, state) separated from
   DOM rendering (img src swap) for reusability in WebUI and Tauri.
   ================================================================= */
;(function(N) {
"use strict";

// ------------------------------------------------------------------
// Pure Logic — testable without DOM
// ------------------------------------------------------------------

/**
 * Build image URL from base, persona, and filename.
 * @param {string} baseUrl - Server origin (e.g. "" or "http://localhost:26262")
 * @param {string} persona - Persona name
 * @param {string} filename - Image filename (e.g. "base.png", "expr_joy.png")
 * @returns {string} Full URL
 */
function buildImageUrl(baseUrl, persona, filename) {
  return baseUrl + "/api/chat/" + encodeURIComponent(persona) + "/persona/avatar/" + filename;
}

/**
 * Map emotion name to filename.
 * @param {string} emotion
 * @returns {string} Filename (e.g. "base.png" for neutral, "expr_joy.png" for joy)
 */
function emotionToFilename(emotion) {
  if (!emotion || emotion === "neutral") return "base.png";
  return "expr_" + emotion + ".png";
}

// Mouth level thresholds (5 levels: mouth_0..mouth_4).
// Rising: level L -> L+1 requires ratio >= UP_TH[L]  (L = 0..3)
// Falling: level L -> L-1 requires ratio < DOWN_TH[L-1]  (L = 1..4)
var MOUTH_UP_TH = [0.2, 0.4, 0.6, 0.8];
var MOUTH_DOWN_TH = [0.15, 0.35, 0.55, 0.75];

/**
 * Quantize an open ratio (0.0-1.0) to a mouth level (0-4) with hysteresis.
 * One step per call: rises to L+1 when ratio >= upTh[L], falls to L-1 when
 * ratio < downTh[L-1]. Clamped to 0..4. Prevents flicker near thresholds.
 * @param {number} ratio - Open ratio 0.0-1.0
 * @param {number} prevLevel - Current mouth level (0-4)
 * @returns {number} New mouth level (0-4)
 */
function mouthRatioToLevel(ratio, prevLevel) {
  var level = (typeof prevLevel === "number" && !isNaN(prevLevel)) ? prevLevel : 0;
  if (level < 0) level = 0;
  if (level > 4) level = 4;
  if (typeof ratio !== "number" || isNaN(ratio)) ratio = 0;
  if (level < 4 && ratio >= MOUTH_UP_TH[level]) return level + 1;
  if (level > 0 && ratio < MOUTH_DOWN_TH[level - 1]) return level - 1;
  return level;
}

/**
 * Select which file to display based on current state.
 * Priority: mouth_<level> (talking) > look_<dir>.png (idle, turned) >
 *           hair_<n>.png (idle, front) > expr_<emotion>.png > base.png.
 * Every layer falls through to the next when its file is not loaded.
 * @param {object} state - Avatar state
 * @returns {string} Filename to display
 */
function selectDisplayFile(state) {
  // 1. Talking: mouth takes priority (mouth_<level>, stepping down until loaded)
  if (state.talking && state.mouthLevel > 0) {
    for (var l = state.mouthLevel; l >= 1; l--) {
      var mouthFile = "mouth_" + l + ".png";
      var mouthEntry = state.cache[mouthFile];
      if (mouthEntry && mouthEntry.loaded && !mouthEntry.error) {
        return mouthFile;
      }
    }
  }
  // 2. Idle look: face turned left/right (front uses base/hair layer instead)
  if (!state.talking && state.lookEnabled !== false &&
      (state.look === "left" || state.look === "right")) {
    var lookFile = "look_" + state.look + ".png";
    var lookEntry = state.cache[lookFile];
    if (lookEntry && lookEntry.loaded && !lookEntry.error) {
      return lookFile;
    }
  }
  // 3. Idle bob: hair sway frame (front view)
  if (!state.talking && state.bobEnabled !== false &&
      typeof state.hairFrame === "number" && state.hairFrame >= 0 && state.hairFrame <= 2) {
    var hairFile = "hair_" + state.hairFrame + ".png";
    var hairEntry = state.cache[hairFile];
    if (hairEntry && hairEntry.loaded && !hairEntry.error) {
      return hairFile;
    }
  }
  // 4. Emotion file if loaded and not errored
  var emotionFile = emotionToFilename(state.emotion);
  var emotionEntry = state.cache[emotionFile];
  if (emotionEntry && emotionEntry.loaded && !emotionEntry.error) {
    return emotionFile;
  }
  // 5. Fallback
  return "base.png";
}

// ------------------------------------------------------------------
// Look (face turn) & Bob (hair sway) — idle animations
// ------------------------------------------------------------------

// Look sequence: [state, durationMs] pairs. Cycle: front -> left -> front -> right -> front.
// Front 1200ms + left 900ms + front 1200ms + right 900ms = 4200ms (~3-5s per requirement).
var LOOK_SEQUENCE = [
  ["front", 1200],
  ["left", 900],
  ["front", 1200],
  ["right", 900],
];

// Hair bob: frame duration in ms, 3 frames looping (hair_0/1/2).
var HAIR_FRAME_MS = 200;

/**
 * Idle look state from elapsed time: 'front' | 'left' | 'right'.
 * Walks LOOK_SEQUENCE in a loop. Invalid time/start degrades to the
 * start of the cycle (front).
 * @param {number} t - Current timestamp (ms)
 * @param {number} lookStartTime - Animation start timestamp (ms)
 * @returns {string} Look state
 */
function lookFrameAt(t, lookStartTime) {
  if (typeof t !== "number" || isNaN(t)) return "front";
  var start = (typeof lookStartTime === "number" && !isNaN(lookStartTime)) ? lookStartTime : t;
  var elapsed = t - start;
  if (elapsed < 0) elapsed = 0;
  var cycle = 0;
  for (var i = 0; i < LOOK_SEQUENCE.length; i++) cycle += LOOK_SEQUENCE[i][1];
  var pos = elapsed % cycle;
  for (var j = 0; j < LOOK_SEQUENCE.length; j++) {
    pos -= LOOK_SEQUENCE[j][1];
    if (pos < 0) return LOOK_SEQUENCE[j][0];
  }
  return "front";
}

/**
 * Idle hair frame (0-2) from elapsed time, looping hair_0/1/2.
 * @param {number} t - Current timestamp (ms)
 * @param {number} hairStartTime - Animation start timestamp (ms)
 * @returns {number} Hair frame 0|1|2
 */
function hairFrameAt(t, hairStartTime) {
  if (typeof t !== "number" || isNaN(t)) return 0;
  var start = (typeof hairStartTime === "number" && !isNaN(hairStartTime)) ? hairStartTime : t;
  var elapsed = t - start;
  if (elapsed < 0) elapsed = 0;
  return Math.floor(elapsed / HAIR_FRAME_MS) % 3;
}

// ------------------------------------------------------------------
// Image Preloader
// ------------------------------------------------------------------

/**
 * Preload an image and track in cache.
 * @param {object} state - Avatar state (cache, baseUrl, persona, onError)
 * @param {string} filename - Image filename to preload
 * @param {function} callback - Called with cache entry { loaded, error }
 * @param {function} [createImage] - Factory for Image element (injectable for testing)
 * @param {boolean} [quiet] - Suppress onError on failure (optional assets)
 * @returns {object} Cache entry
 */
function preloadImage(state, filename, callback, createImage, quiet) {
  if (state.cache[filename]) {
    callback(state.cache[filename]);
    return state.cache[filename];
  }

  var entry = { loaded: false, error: false };
  state.cache[filename] = entry;

  var factory = createImage || function() { return new Image(); };
  var img = factory();
  var url = buildImageUrl(state.baseUrl, state.persona, filename);

  img.onload = function() {
    entry.loaded = true;
    callback(entry);
  };
  img.onerror = function() {
    entry.error = true;
    if (!quiet && state.onError) {
      state.onError(new Error("Failed to load avatar image: " + filename));
    }
    callback(entry);
  };
  img.src = url;

  return entry;
}

/**
 * Preload mouth_<level>.png if not already cached.
 * @param {object} state - Avatar state
 * @param {number} level - Mouth level 1-4
 * @param {function} callback - Called when load resolves (cached or fetched)
 */
function preloadMouthLevel(state, level, callback) {
  var filename = "mouth_" + level + ".png";
  if (state.cache[filename]) {
    callback(state.cache[filename]);
    return;
  }
  preloadImage(state, filename, callback);
}

// ------------------------------------------------------------------
// State Factory
// ------------------------------------------------------------------

function createAvatarState(options) {
  return {
    baseUrl: options.baseUrl || "",
    persona: options.persona || "",
    emotion: "neutral",
    intensity: 1.0,
    talking: false,
    mouthLevel: 0,
    lookEnabled: options.lookEnabled !== false,
    bobEnabled: options.bobEnabled !== false,
    look: "front",
    hairFrame: 0,
    lookStartTime: null,
    hairStartTime: null,
    cache: {},   // filename -> { loaded: bool, error: bool }
    onError: options.onError || null,
  };
}

// ------------------------------------------------------------------
// DOM Renderer
// ------------------------------------------------------------------

/**
 * Create a renderer that manages an img element inside a container.
 * @param {HTMLElement|null} element - Container element
 * @returns {object} Renderer with render() and clear()
 */
function createRenderer(element) {
  var img = null;

  if (element) {
    img = element.querySelector("img");
    if (!img) {
      img = document.createElement("img");
      img.alt = "Avatar";
      img.setAttribute("role", "img");
      element.appendChild(img);
    }
  }

  return {
    render: function(filename, state) {
      if (!img || !state) return;
      var url = buildImageUrl(state.baseUrl, state.persona, filename);
      if (img.getAttribute("src") !== url) {
        img.setAttribute("src", url);
      }
    },
    clear: function() {
      if (img) {
        img.removeAttribute("src");
        img = null;
      }
    },
    getImg: function() { return img; },
  };
}

// ------------------------------------------------------------------
// Public API
// ------------------------------------------------------------------

var _state = null;
var _renderer = null;

// ------------------------------------------------------------------
// Idle Animation Driver (setInterval; rAF is overkill for 100ms ticks)
// ------------------------------------------------------------------

var ANIM_INTERVAL_MS = 100;
var _animTimer = null;

function noop() {}

/**
 * Advance look/bob state from the clock and re-render.
 * Paused (held at front / frozen frame) while talking — mouth takes priority.
 * Look/hair assets are preloaded quietly on the first idle tick; missing
 * assets silently fall back to emotion/base.
 */
function tickAnimation() {
  if (!_state) return;
  var now = Date.now();
  if (_state.talking) {
    _state.look = "front";
  } else {
    if (_state.lookEnabled) {
      if (_state.lookStartTime == null) _state.lookStartTime = now;
      _state.look = lookFrameAt(now, _state.lookStartTime);
      preloadImage(_state, "look_left.png", noop, null, true);
      preloadImage(_state, "look_right.png", noop, null, true);
    }
    if (_state.bobEnabled) {
      if (_state.hairStartTime == null) _state.hairStartTime = now;
      _state.hairFrame = hairFrameAt(now, _state.hairStartTime);
      preloadImage(_state, "hair_0.png", noop, null, true);
      preloadImage(_state, "hair_1.png", noop, null, true);
      preloadImage(_state, "hair_2.png", noop, null, true);
    }
  }
  _renderer.render(selectDisplayFile(_state), _state);
}

function startAnimTimer() {
  if (_animTimer != null) return;
  _animTimer = setInterval(tickAnimation, ANIM_INTERVAL_MS);
}

function stopAnimTimer() {
  if (_animTimer != null) {
    clearInterval(_animTimer);
    _animTimer = null;
  }
}

var avatar = {

  // Expose pure functions for unit testing
  _buildImageUrl: buildImageUrl,
  _emotionToFilename: emotionToFilename,
  _selectDisplayFile: selectDisplayFile,
  _preloadImage: preloadImage,
  _mouthRatioToLevel: mouthRatioToLevel,
  _lookFrameAt: lookFrameAt,
  _hairFrameAt: hairFrameAt,
  _getState: function() { return _state; },

  /**
   * Initialize the avatar engine.
   * @param {HTMLElement|null} element - Container for the avatar image (null = no DOM)
   * @param {object} options - { baseUrl, persona, enabled, panelWidth, mouthMode,
   *                            lookEnabled (default true), bobEnabled (default true), onError }
   * @returns {object} avatar (for chaining)
   */
  init: function(element, options) {
    options = options || {};
    _state = createAvatarState(options);
    _renderer = createRenderer(element);

    // Preload base image, then render
    preloadImage(_state, "base.png", function() {
      if (_state) {
        _renderer.render(selectDisplayFile(_state), _state);
      }
    });

    // Idle animation driver (look/bob); no-op when both disabled
    if (_state.lookEnabled || _state.bobEnabled) {
      startAnimTimer();
    }

    return this;
  },

  /**
   * Set the current emotion and intensity.
   * @param {string} emotion - Emotion name (e.g. "joy", "sad", "neutral")
   * @param {number} intensity - 0.0 to 1.0 (default 1.0)
   */
  setEmotion: function(emotion, intensity) {
    if (!_state) return;
    _state.emotion = emotion || "neutral";
    _state.intensity = typeof intensity === "number" ? intensity : 1.0;

    var filename = emotionToFilename(_state.emotion);
    preloadImage(_state, filename, function() {
      if (_state) {
        _renderer.render(selectDisplayFile(_state), _state);
      }
    });
  },

  /**
   * Start talking — preload mouth_1..4, keep current mouth level (default 2).
   */
  startTalking: function() {
    if (!_state) return;
    _state.talking = true;
    // Keep current level; default to mid level (2) if not set
    if (_state.mouthLevel < 1) _state.mouthLevel = 2;

    // Preload all mouth levels; mouth_open.png is legacy — replaced by mouth_3.png
    for (var l = 1; l <= 4; l++) {
      preloadMouthLevel(_state, l, function() {
        if (_state && _state.talking) {
          _renderer.render(selectDisplayFile(_state), _state);
        }
      });
    }
  },

  /**
   * Stop talking — revert to emotion/base image.
   */
  stopTalking: function() {
    if (!_state) return;
    _state.talking = false;
    _state.mouthLevel = 0;
    _renderer.render(selectDisplayFile(_state), _state);
  },

  /**
   * Set mouth openness directly (0.0–1.0).
   * Quantized to 5 levels (0-4) with hysteresis to prevent flicker.
   * @param {number} openRatio - 0.0 (closed) to 1.0 (open)
   */
  setMouth: function(openRatio) {
    if (!_state) return;
    var ratio = (typeof openRatio === "number" && !isNaN(openRatio)) ? openRatio : 0;
    var newLevel = mouthRatioToLevel(ratio, _state.mouthLevel);
    if (newLevel !== _state.mouthLevel) {
      _state.mouthLevel = newLevel;
      _renderer.render(selectDisplayFile(_state), _state);
    }
  },

  /**
   * Destroy the avatar instance and clean up DOM.
   */
  destroy: function() {
    stopAnimTimer();
    if (_renderer) _renderer.clear();
    _state = null;
    _renderer = null;
  },
};

N.Avatar = avatar;

})(window.Nous);
