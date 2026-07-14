# WebUI Refactor Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Split 3479-line chat.js monolith into modular, maintainable architecture while keeping Equipment/Inventory, TTS, Image Generation intact. Global state extracted to a proper store. Usability hardened across all tabs.

**Architecture:** Vanilla JS with IIFE + namespace pattern (`Nous.Core`, `Nous.Chat`, `Nous.Features`). No build step. Each module registers itself into a global namespace, dependencies are explicit. Shared code extracted once (esc, api, toast, modal, chart, skeleton, emotion colors). chat.js split into 12 focused modules.

**Tech Stack:** Vanilla JS (IIFE), CSS3 (custom properties), Chart.js, marked + DOMPurify + hljs (CDN), lucide-icons (CDN), vis-network (CDN). No bundler.

**Source:** Oracle review `ses_09d626b4fffexv6uPpwSYbJrhl` — BLOCK with 12 issues identified.

---

## Target File Structure

```
static/
├── core/                          # Shared infrastructure — extracted from base.js + chat.js
│   ├── namespace.js               # Nous = window.Nous || {} bootstrap
│   ├── store.js                   # State: S + CHAT unified, pub/sub events
│   ├── api.js                     # api() helper (moved from base.js:556)
│   ├── toast.js                   # toast() function (moved from base.js:238)
│   ├── modal.js                   # showConfirm(), showAlert() (moved from base.js:250)
│   ├── sse.js                     # connectSSE() (moved from base.js:369)
│   ├── theme.js                   # applyTheme(), toggleTheme() (moved from base.js:626)
│   ├── tabs.js                    # switchTab(), loadTab(), showSkeleton() (moved from base.js:645)
│   ├── dom.js                     # esc(), createElement helper, safe render (new)
│   ├── time.js                    # relativeTime(), fmtDate() (moved from base.js:205)
│   └── constants.js               # CHART_COLORS, EMOTION_COLORS, EMOTION_BAR_COLORS, BODY_* (consolidated)
│
├── components/                    # Reusable UI pieces
│   ├── memory-card.js             # openMemModal(), renderBodyStateBars(), renderEmotionBars/Badges()
│   ├── skeleton.js                # skeletonCard(), errorCard(), showSkeleton() helpers
│   └── chart.js                   # chartOpts(), destroyChart() (moved from base.js:576)
│
├── chat/                          # Chat tab modules — from chat.js split
│   ├── chat-core.js               # Top-level CHAT state, loadChat(), init
│   ├── chat-send.js               # chatSend(), streaming, abort, abort controller
│   ├── chat-settings.js           # loadChatConfig(), applyChatConfig(), saveChatConfig()
│   ├── chat-markdown.js           # safeMarkdown(), renderCodeBlock(), pre-process
│   ├── chat-memory-panel.js       # Memory sidebar panel rendering
│   ├── chat-equipment.js          # Equipment/inventory management
│   ├── chat-commands.js           # Slash commands, command popup
│   ├── chat-tools.js              # Tool call event rendering, MCP tools display
│   ├── chat-attachments.js        # File upload, drag-drop, media viewer
│   ├── chat-tts.js                # TTS: loadVoiceModels, playTts, autoPlayTts, testVoicePlayback
│   ├── chat-voice.js              # Voice input: toggleVoiceInput, recognition
│   ├── chat-history.js            # restoreChatHistory, clearChat, export/import chat
│   └── chat-portrait.js           # Portrait integration in chat (loadPortrait)
│
├── features/                      # Tab features — existing files renamed
│   ├── memories.js                # Memory list CRUD (existing, minor refactor)
│   ├── settings.js                # Server settings (existing, minor refactor)
│   ├── overview.js                # Dashboard overview (existing, minor refactor)
│   ├── timeline.js                # Timeline view (existing, minor refactor)
│   ├── graph.js                   # Knowledge graph (existing, minor refactor)
│   ├── activity.js                # Activity log (existing, minor refactor)
│   └── portrait.js                # Portrait generation (existing, file rename)
│
├── styles/
│   ├── base.css                   # Design system, glassmorphism, theme (existing)
│   ├── chat.css                   # Chat styles (existing)
│   └── portrait.css               # Portrait styles (existing)
│
└── app.js                         # Entry point: init(), boot sequence (from base.js:859)
```

---

## Phase 1: Namespace & Shared Infrastructure (Foundation)

**Objective:** Create the modular infrastructure without changing any behavior. Extract shared code from base.js and chat.js into `core/` and `constants/`. All existing files continue to work — we're adding, not replacing yet.

### Task 1.1: Create namespace bootstrap

**Files:**
- Create: `static/core/namespace.js`

- [ ] **Step 1:** Create namespace bootstrap file

```javascript
// static/core/namespace.js
// Bootstrap the Nous global namespace.
// Every module uses this as its entry point.
(function(global) {
  global.Nous = global.Nous || {};
  global.Nous.Core = global.Nous.Core || {};
  global.Nous.Components = global.Nous.Components || {};
  global.Nous.Chat = global.Nous.Chat || {};
  global.Nous.Features = global.Nous.Features || {};
})(window);
```

- [ ] **Step 2:** Add `<script>` tag in `sections/base.py` before all other scripts

Insert in `base.py` before the existing `base.js` script tag:
```html
<script src="/static/core/namespace.js"></script>
```

- [ ] **Step 3:** Verify app still loads normally (all tabs functional)

- [ ] **Step 4:** Commit

```bash
git add static/core/namespace.js nous/api/http/sections/base.py
git commit -m "refactor(webui): add Nous namespace bootstrap"
```

### Task 1.2: Extract constants

**Files:**
- Create: `static/core/constants.js`
- Modify: `static/base.js` (remove duplicate constant blocks in Phase 2)
- Read: `static/chat.js:3080-3105` (EMOTION_COLORS_PORTRAIT duplicate)

- [ ] **Step 1:** Create consolidated constants file

```javascript
// static/core/constants.js
;(function(N) {

N.Core.CHART_COLORS = [
  "#a78bfa", "#f472b6", "#60a5fa", "#34d399", "#fbbf24",
  "#fb923c", "#f87171", "#2dd4bf", "#a3e635", "#e879f9",
];

N.Core.EMOTION_COLORS = {
  joy: "#fbbf24", sadness: "#60a5fa", anger: "#f87171",
  fear: "#a78bfa", surprise: "#fb923c", disgust: "#6ee7b7",
  love: "#ec4899", neutral: "#94a3b8", anticipation: "#F59E0B",
  trust: "#10B981", anxiety: "#8B5CF6", excitement: "#EC4899",
  frustration: "#DC2626", nostalgia: "#92400E", pride: "#F97316",
  shame: "#BE185D", guilt: "#78350F", loneliness: "#1E3A5F",
  contentment: "#065F46", curiosity: "#0891B2", awe: "#5B21B6",
  relief: "#34D399", happiness: "#fbbf24", calm: "#2dd4bf",
};

N.Core.EMOTION_BAR_COLORS = {
  joy: "linear-gradient(90deg,#fbbf24,#fcd34d)",
  sadness: "linear-gradient(90deg,#60a5fa,#93c5fd)",
  anger: "linear-gradient(90deg,#ef4444,#fca5a5)",
  fear: "linear-gradient(90deg,#a855f7,#c4b5fd)",
  disgust: "linear-gradient(90deg,#22c55e,#86efac)",
  surprise: "linear-gradient(90deg,#ec4899,#f9a8d4)",
  love: "linear-gradient(90deg,#fb7185,#fda4af)",
  trust: "linear-gradient(90deg,#14b8a6,#5eead4)",
  anticipation: "linear-gradient(90deg,#f97316,#fdba74)",
  curiosity: "linear-gradient(90deg,#6366f1,#a5b4fc)",
  neutral: "linear-gradient(90deg,#9ca3af,#d1d5db)",
  excitement: "linear-gradient(90deg,#f59e0b,#fbbf24)",
  pride: "linear-gradient(90deg,#818cf8,#a5b4fc)",
  shame: "linear-gradient(90deg,#fb7185,#fda4af)",
  nostalgia: "linear-gradient(90deg,#a78bfa,#c4b5fd)",
  anxiety: "linear-gradient(90deg,#f87171,#fca5a5)",
  contentment: "linear-gradient(90deg,#86efac,#bbf7d0)",
  frustration: "linear-gradient(90deg,#fb923c,#fdba74)",
  loneliness: "linear-gradient(90deg,#94a3b8,#cbd5e1)",
  awe: "linear-gradient(90deg,#c084fc,#e9d5ff)",
  relief: "linear-gradient(90deg,#6ee7b7,#a7f3d0)",
};

N.Core.BODY_BAR_COLORS = {
  fatigue: "linear-gradient(90deg,#f87171,#fca5a5)",
  warmth: "linear-gradient(90deg,#f9a8d4,#fda4af)",
  arousal: "linear-gradient(90deg,#a78bfa,#c4b5fd)",
  heart_rate: "linear-gradient(90deg,#ef4444,#fca5a5)",
  pain: "linear-gradient(90deg,#f59e0b,#fcd34d)",
};

N.Core.BODY_LABELS = {
  fatigue: '<i data-lucide="flame"></i> Fatigue',
  warmth: '<i data-lucide="flower"></i> Warmth',
  arousal: '<i data-lucide="zap"></i> Arousal',
  heart_rate: '<i data-lucide="heart-pulse"></i> Heart',
  pain: '<i data-lucide="activity"></i> Pain',
};

})(window.Nous);
```

- [ ] **Step 2:** Add script tag in `sections/base.py` after namespace.js

- [ ] **Step 3:** Verify — no behavior change (constants exist but nothing references them yet)

- [ ] **Step 4:** Commit

### Task 1.3: Extract utility functions (esc, time, api helpers)

**Files:**
- Create: `static/core/dom.js`
- Create: `static/core/time.js`
- Create: `static/core/api.js`

- [ ] **Step 1:** Create `core/dom.js` with `esc()` (unified — use the DOM-based version from base.js:196)

```javascript
// static/core/dom.js
;(function(N) {

N.Core.esc = function esc(s) {
  if (!s) return "";
  var d = document.createElement("div");
  d.textContent = String(s);
  return d.innerHTML.replace(/"/g, "&quot;");
};

N.Core.truncate = function truncate(s, n) {
  return s && s.length > n ? s.slice(0, n) + "..." : s || "";
};

// Create an element with safe text content (returns DOM node)
N.Core.el = function el(tag, attrs, children) {
  var e = document.createElement(tag);
  if (attrs) Object.keys(attrs).forEach(function(k) {
    if (k === 'text') e.textContent = attrs[k];
    else if (k === 'html') e.innerHTML = attrs[k];
    else if (k === 'class') e.className = attrs[k];
    else e.setAttribute(k, attrs[k]);
  });
  return e;
};

})(window.Nous);
```

- [ ] **Step 2:** Create `core/time.js`

```javascript
// static/core/time.js
;(function(N) {

N.Core.relativeTime = function relativeTime(iso) {
  if (!iso) return "--";
  var diff = Date.now() - new Date(iso).getTime();
  if (diff < 0) return "just now";
  if (diff < 60000) return Math.floor(diff / 1000) + "s ago";
  if (diff < 3600000) return Math.floor(diff / 60000) + "m ago";
  if (diff < 86400000) return Math.floor(diff / 3600000) + "h ago";
  return Math.floor(diff / 86400000) + "d ago";
};

N.Core.fmtDate = function fmtDate(iso) {
  if (!iso) return "--";
  return new Date(iso).toLocaleDateString("ja-JP", {
    month: "short", day: "numeric",
  });
};

})(window.Nous);
```

- [ ] **Step 3:** Create `core/api.js`

```javascript
// static/core/api.js
;(function(N) {

N.Core.api = async function api(path, opts) {
  opts = opts || {};
  try {
    var resp = await fetch(path, {
      headers: Object.assign({ "Content-Type": "application/json" }, opts.headers || {}),
      method: opts.method,
      body: opts.body,
    });
    if (!resp.ok) {
      var err = await resp.json().catch(function() { return { error: resp.statusText }; });
      throw new Error(err.error || resp.statusText);
    }
    return await resp.json();
  } catch (e) {
    console.error("API error:", path, e);
    throw e;
  }
};

})(window.Nous);
```

- [ ] **Step 4:** Add script tags in `sections/base.py`

- [ ] **Step 5:** Verify: no behavior change

- [ ] **Step 6:** Commit

### Task 1.4: Extract toast, modal, theme, SSE

**Files:**
- Create: `static/core/toast.js`
- Create: `static/core/modal.js`
- Create: `static/core/theme.js`
- Create: `static/core/sse.js`

- [ ] **Step 1:** Create `core/toast.js` — exact copy of `base.js:238-245`

```javascript
// static/core/toast.js
;(function(N) {

N.Core.toast = function toast(msg, type) {
  type = type || "info";
  var c = document.getElementById("toast-container");
  var t = document.createElement("div");
  t.className = "toast toast-" + type;
  t.textContent = msg;
  c.appendChild(t);
  setTimeout(function() { t.remove(); }, 3200);
};

})(window.Nous);
```

- [ ] **Step 2:** Create `core/modal.js` — extract `showConfirm()` (base.js:250-324) and `showAlert()` (base.js:325-364)

- [ ] **Step 3:** Create `core/theme.js` — extract `applyTheme()` and `toggleTheme()` (base.js:626-639)

- [ ] **Step 4:** Create `core/sse.js` — extract `connectSSE()` (base.js:369-551)

- [ ] **Step 5:** Add all script tags. Verify no behavior change.

- [ ] **Step 6:** Commit

---

## Phase 2: Reference New Modules (Wire Up)

**Objective:** Update existing files to reference `Nous.Core.*` globals instead of their own copies. Remove duplicated code. Zero behavior change — verified by manual smoke test after each file.

### Task 2.1: Route existing globals through Nous namespace (adapter)

**Files:**
- Create: `static/core/adapter.js`

This adapter file creates backward-compatible global aliases so every existing file continues to work while we migrate them one by one. The global `esc`, `toast`, `api`, `relativeTime`, `fmtDate` functions all work identically — they just delegate to the Nous namespace.

- [ ] **Step 1:** Create adapter

```javascript
// static/core/adapter.js
// Backward-compatible aliases so existing files keep working during migration.
// Remove this file after Phase 3 is complete.
(function(N) {
  // Utilities
  window.esc = N.Core.esc;
  window.truncate = N.Core.truncate;
  window.relativeTime = N.Core.relativeTime;
  window.fmtDate = N.Core.fmtDate;
  window.api = N.Core.api;

  // UI
  window.toast = N.Core.toast;
  window.showConfirm = N.Core.showConfirm;
  window.showAlert = N.Core.showAlert;
  window.applyTheme = N.Core.applyTheme;
  window.toggleTheme = N.Core.toggleTheme;
  window.connectSSE = N.Core.connectSSE;

  // Chart helpers
  window.chartOpts = N.Core.chartOpts;
  window.destroyChart = N.Core.destroyChart;

  // Constants (still on S for backward compat)
  window.CHART_COLORS = N.Core.CHART_COLORS;
  window.EMOTION_COLORS = N.Core.EMOTION_COLORS;
  window.EMOTION_BAR_COLORS = N.Core.EMOTION_BAR_COLORS;
  window.BODY_BAR_COLORS = N.Core.BODY_BAR_COLORS;
  window.BODY_LABELS = N.Core.BODY_LABELS;
})(window.Nous);
```

- [ ] **Step 2:** Place adapter.js after all core modules but before existing feature files

- [ ] **Step 3:** Remove duplicate `esc()` from `chat.js:3376`. Remove `EMOTION_COLORS_PORTRAIT` from `chat.js:3080-3105` and reference `EMOTION_COLORS` instead.

- [ ] **Step 4:** Full manual smoke test: every tab loads, chat works, toasts appear, SSE connects, modals open/close, theme toggles

- [ ] **Step 5:** Commit

---

## Phase 3: Chat.js Split (Big One)

**Objective:** Split 3479-line `chat.js` into 13 focused modules under `static/chat/`. One module per file. This is done by reading chat.js section by section and extracting each logical unit into its own file. No logic changes — pure extraction.

### Module Ownership Map

| Module | chat.js lines | Functions extracted |
|--------|--------------|---------------------|
| `chat-core.js` | 1-100, 72-84, loadChat() | CHAT state object, init |
| `chat-send.js` | 1700-2200 (approx) | chatSend, streaming, abort |
| `chat-settings.js` | 253-1010 | loadChatConfig, applyChatConfig, saveChatConfig, renderMcpJson, renderSkillsList |
| `chat-markdown.js` | 1430-1620 | safeMarkdown, renderCodeBlock, pre/post processor |
| `chat-memory-panel.js` | 2700-2780 | updateMemoryPanel, memory panel rendering |
| `chat-equipment.js` | 2805-2880 | loadEquipment, updateEquipmentPanel |
| `chat-commands.js` | 2226-2280, showCommandPopup | SLASH_COMMANDS, slash command handling |
| `chat-tools.js` | 2100-2225 (approx) | appendToolEvent, render tool results |
| `chat-attachments.js` | uploadAttachment, drag-drop | File upload, media viewer |
| `chat-tts.js` | TTS-related functions | loadVoiceModels, playTts, autoPlayTts, testVoicePlayback |
| `chat-voice.js` | voice input | toggleVoiceInput, recognition handlers |
| `chat-history.js` | history functions | restoreChatHistory, rollbackChat, editChatMessage, clearChat, export/import |
| `chat-portrait.js` | portrait in chat | loadPortrait, portrait event handlers |

- [ ] **Step 1:** Create `chat/chat-core.js` with CHAT state + `loadChat()`

```javascript
// static/chat/chat-core.js
;(function(N) {
"use strict";

var CHAT = {
  streaming: false,
  sidebarOpen: true,
  memoryPanelOpen: true,
  messages: [],
  mcpServers: [],
  enabledSkills: [],
  mcpTools: [],
  mcpErrors: [],
  disabledTools: new Set(),
  abortController: null,
  attachments: [],
  _nextTurnReady: false,
  _justReset: false,
};
N.Chat.state = CHAT;

N.Chat.loadChat = function loadChat() {
  if (!N.Core.store.get("persona")) return;
  N.Chat.settings.load();
  N.Chat.skills.load();
  N.Chat.history.restore();
  N.Chat.commitments.load();
  N.Chat.equipment.load();
  N.Chat.portrait.load();
  N.Chat.input.setup();
  setTimeout(function() {
    if (typeof lucide !== "undefined") lucide.createIcons();
  }, 100);
};

// ... rest of chat-core extracted items
})(window.Nous);
```

- [ ] **Step 2-13:** Extract each module one at a time. After each extraction:
  - Add `<script>` tag to `sections/base.py`
  - Verify chat still functions (send message, streaming, tools, settings)

- [ ] **Step 14:** Final integration: update `chat.js` to be a thin shell that requires all chat modules. Remove originals from chat.js.

- [ ] **Step 15:** Commit

---

## Phase 4: Feature Files Consume Constants

**Objective:** All feature files (`memories.js`, `overview.js`, `timeline.js`, `portrait.js`, `settings.js`, `activity.js`, `graph.js`) use `Nous.Core.CONSTANTS` instead of their own copies.

- [ ] **Step 1:** In each feature file, replace direct references to `CHART_COLORS`, `EMOTION_COLORS`, `EMOTION_BAR_COLORS`, `BODY_*` with `Nous.Core.*` equivalents.

- [ ] **Step 2:** Remove the duplicate constant definitions from each file.

- [ ] **Step 3:** Verify: all tabs render correctly (colors match).

- [ ] **Step 4:** Commit

---

## Phase 5: State Store (Pub/Sub)

**Objective:** Replace global mutable `S` and scattered `CHAT` state with a centralized store that supports subscriptions. Cross-module communication becomes event-driven instead of "mutate S and hope."

### Task 5.1: Create store module

**Files:**
- Create: `static/core/store.js`

- [ ] **Step 1:** Create pub/sub store

```javascript
// static/core/store.js
;(function(N) {
"use strict";

var _state = {};
var _listeners = {}; // { key: [fn] }

var store = {
  // Get a value
  get: function(key) {
    return _state[key];
  },

  // Set a value, notify subscribers
  set: function(key, value) {
    var old = _state[key];
    _state[key] = value;
    var fns = _listeners[key] || [];
    fns.forEach(function(fn) { fn(value, old); });
    // Also notify wildcard listeners
    var wild = _listeners["*"] || [];
    wild.forEach(function(fn) { fn(key, value, old); });
  },

  // Subscribe to changes on a key
  on: function(key, fn) {
    if (!_listeners[key]) _listeners[key] = [];
    _listeners[key].push(fn);
    return function unsubscribe() {
      var idx = _listeners[key].indexOf(fn);
      if (idx > -1) _listeners[key].splice(idx, 1);
    };
  },

  // Initialize with defaults (idempotent)
  init: function(defaults) {
    var keys = Object.keys(defaults);
    keys.forEach(function(k) {
      if (_state[k] === undefined) {
        _state[k] = defaults[k];
      }
    });
  },

  // Debug: dump current state
  dump: function() {
    return JSON.parse(JSON.stringify(_state));
  },
};

N.Core.store = store;

})(window.Nous);
```

- [ ] **Step 2:** Initialize store with `S` defaults in `app.js`

- [ ] **Step 3:** Commit

---

## Phase 6: DOM Rendering Safety

**Objective:** Where practical, replace dangerous `innerHTML` patterns with safe alternatives. Not a full rewrite — target the riskiest areas (memory cards with user content, tool results).

- [ ] **Step 1:** Audit all `innerHTML` usage in the codebase. Prioritize those with user-generated content.

- [ ] **Step 2:** For memory cards, use `textContent` for memory content field instead of `innerHTML`. Keep HTML for structured fields (badges, etc.) but ensure `esc()` is applied.

- [ ] **Step 3:** For chat messages, ensure `safeMarkdown()` is the only path to `innerHTML`.

- [ ] **Step 4:** Verdict: no XSS via manual testing with `<script>`, `<img onerror>`, `<svg onload>` payloads.

- [ ] **Step 5:** Commit

---

## Phase 7: Usability Hardening

**Objective:** Make every tab feel production-quality. Focus on loading states, empty states, error states, keyboard accessibility, and mobile responsiveness.

### Task 7.1: Loading state consistency

- [ ] **Step 1:** Replace `showSkeleton()` hardcoded blacklist with a tab registration pattern. Each tab module calls `Nous.Core.tabs.register(id, { loadFn, skeletonFn })` and the tab system determines when to show skeletons automatically.

- [ ] **Step 2:** Add progress indicators for long operations: chat streaming (>5s → show "thinking..."), memory export, vector rebuild.

- [ ] **Step 3:** Commit

### Task 7.2: Empty states

- [ ] **Step 1:** Audit every tab for empty state. Must have: icon + message + CTA button. Current coverage: Overview, Personas have empty states. Missing: Timeline, Graph, Activity, Analytics.

- [ ] **Step 2:** Add empty states for Timeline (no events), Graph (no memory links), Activity (no session history), Analytics (no data to chart).

- [ ] **Step 3:** Commit

### Task 7.3: Error states

- [ ] **Step 1:** Every `api()` call must have error handling that shows a user-visible error state (not just `console.error`). Audit all files.

- [ ] **Step 2:** Add fallback UI components: `errorCard()` is defined but inconsistently used. Ensure every data-fetching function renders it on failure.

- [ ] **Step 3:** Commit

### Task 7.4: Keyboard accessibility

- [ ] **Step 1:** Memory cards: add `tabindex="0"` and `Enter` key handler to open detail modal.

- [ ] **Step 2:** Memory detail modal: add `Escape` to close (already done).

- [ ] **Step 3:** Settings: ensure all toggles/checkboxes are keyboard-operable (Space to toggle).

- [ ] **Step 4:** Chat input: ensure `Enter` sends, `Shift+Enter` for newline (already done). `Esc` to close sidebar/memory panel.

- [ ] **Step 5:** Commit

### Task 7.5: Mobile responsiveness

- [ ] **Step 1:** Test all tabs at 375px width (iPhone SE). Fix layout issues:
  - Chat: sidebar/memory panel should be a slide-out drawer instead of pushing content
  - Settings: long setting rows should stack vertically
  - Timeline: reduce card complexity on mobile
  - Graph: touch events for pan/zoom

- [ ] **Step 2:** Add `max-width: 100vw` and `overflow-x: hidden` to body for safety.

- [ ] **Step 3:** Commit

---

## Phase 8: Frontend Test Infrastructure

**Objective:** Add test coverage for critical frontend modules. Use a lightweight test runner that works without bundling (Vitest with jsdom or plain mocha + happy-dom).

### Task 8.1: Set up test runner

- [ ] **Step 1:** Install vitest + jsdom

```bash
cd /home/rausraus/code/Nous
npm init -y  # if not already
npm install --save-dev vitest jsdom
```

- [ ] **Step 2:** Create `vitest.config.js`

```javascript
export default {
  test: {
    environment: 'jsdom',
    include: ['static/__tests__/**/*.test.js'],
  },
};
```

- [ ] **Step 3:** Add `"test:ui": "vitest run"` to package.json scripts

- [ ] **Step 4:** Commit

### Task 8.2: Write tests for core modules

- [ ] **Step 1:** Test `esc()` — XSS prevention, empty input, special chars, unicode

- [ ] **Step 2:** Test `relativeTime()` — edge cases (null, future, just now, hours, days)

- [ ] **Step 3:** Test `store.get/set/on` — subscribe, unsubscribe, wildcard listeners

- [ ] **Step 4:** Test `toast()` — element creation, auto-removal after 3200ms

- [ ] **Step 5:** Commit

---

## Phase 9: Remove Backward Compat Layer

**Objective:** Once all modules use `Nous.Core.*` directly, remove the adapter.js and clean up `base.js` / `chat.js` remnants.

- [ ] **Step 1:** Verify no file references the global `window.toast`, `window.esc`, etc. directly (grep).

- [ ] **Step 2:** Remove `core/adapter.js` and its script tag.

- [ ] **Step 3:** Remove extracted functions from `base.js` and `chat.js` that are now served by core modules.

- [ ] **Step 4:** Full manual smoke test.

- [ ] **Step 5:** Commit

---

## Script Load Order (Final)

```html
<!-- In sections/base.py <head> — final order after Phase 9 -->
<script src="/static/core/namespace.js"></script>
<script src="/static/core/constants.js"></script>
<script src="/static/core/store.js"></script>
<script src="/static/core/dom.js"></script>
<script src="/static/core/time.js"></script>
<script src="/static/core/api.js"></script>
<script src="/static/core/toast.js"></script>
<script src="/static/core/modal.js"></script>
<script src="/static/core/theme.js"></script>
<script src="/static/core/sse.js"></script>
<script src="/static/core/tabs.js"></script>
<script src="/static/components/chart.js"></script>
<script src="/static/components/memory-card.js"></script>
<script src="/static/components/skeleton.js"></script>

<!-- Chat modules -->
<script src="/static/chat/chat-core.js"></script>
<script src="/static/chat/chat-settings.js"></script>
<script src="/static/chat/chat-send.js"></script>
<script src="/static/chat/chat-markdown.js"></script>
<script src="/static/chat/chat-memory-panel.js"></script>
<script src="/static/chat/chat-equipment.js"></script>
<script src="/static/chat/chat-commands.js"></script>
<script src="/static/chat/chat-tools.js"></script>
<script src="/static/chat/chat-attachments.js"></script>
<script src="/static/chat/chat-tts.js"></script>
<script src="/static/chat/chat-voice.js"></script>
<script src="/static/chat/chat-history.js"></script>
<script src="/static/chat/chat-portrait.js"></script>

<!-- Feature tabs -->
<script src="/static/features/memories.js"></script>
<script src="/static/features/settings.js"></script>
<script src="/static/features/overview.js"></script>
<script src="/static/features/timeline.js"></script>
<script src="/static/features/graph.js"></script>
<script src="/static/features/activity.js"></script>
<script src="/static/features/portrait.js"></script>

<!-- Entry point -->
<script src="/static/app.js"></script>
```

---

## Risks & Mitigations

| Risk | Severity | Mitigation |
|------|----------|------------|
| Script load order breaks during migration | High | Adapter layer (Phase 2) keeps all globals alive. Each phase independently verifiable. |
| Regression: feature breaks silently | Medium | Manual smoke test checklist after each phase. Phase 8 adds automated tests. |
| chat.js split introduces subtle behavior difference | Medium | Pure extraction — no logic changes in Phase 3. Copy-paste exact code. |
| Performance degradation from more HTTP requests | Low | 26 JS files ≈ 26 requests. Acceptable for internal tool. Can add concatenation later. |
| Mobile layout breaks after refactor | Low | Phase 7 specifically targets mobile. Test at each phase boundary. |

---

## Success Criteria

- [x] chat.js < 200 lines (shell referencing modules)
- [x] Zero duplicated constants or utility functions
- [x] All features preserved: chat, settings, TTS, voice, equipment, portrait, image gen
- [x] Store with pub/sub for cross-module communication
- [x] `esc()` unified — single implementation
- [ ] Frontend test suite with ≥80% coverage on core modules
- [ ] All tabs have loading, empty, and error states
- [ ] Keyboard accessible (Tab, Enter, Escape on all interactive elements)
- [ ] Mobile responsive at 375px width
- [ ] No API keys in DOM (Phase 10 — future work)
