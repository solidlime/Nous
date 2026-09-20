/* =================================================================
   CHAT MEMORY PANEL WIRING — synapse fire feed: constants, fire-limit,
   feed rendering, push/dedupe/flush, memory resolution
   Chunk 2/5 of chat-memory-panel.js. Namespace: N.Chat.memoryPanel.*
   + N.Chat.memoryPanel._wiring (internal cross-chunk table used by
   memory-panel/wiring-stream.js and wiring-detail.js).
   ================================================================= */
;(function(N) {
var C = N.Core;
var api = C.api, esc = C.esc, toast = C.toast, safeSetHTML = C.safeSetHTML;
var showConfirm = C.showConfirm, showAlert = C.showAlert;
var truncate = C.truncate, relativeTime = C.relativeTime, fmtDate = C.fmtDate, fmtDateTime = C.fmtDateTime;
"use strict";
var S = window.S;

// Wiring fire feed — live synapse pulses (GET /api/memory/wiring/stream)
// Server flushes its ring buffer on connect, then pushes live events:
//   {seq, kind, source, target, weight, meta}
//   kind ∈ {link_fire, recall_boost, ppr_hit, replay_fire, novelty_gate} — no server-side thinning.
// Client keeps a top-N view (default 8, 0 hides). Panel hidden ⇒ SSE off.
// ------------------------------------------------------------------
var WIRING_URL = "/api/memory/wiring/stream";
var WIRING_LIMIT_KEY = "nous_wiring_limit";
var WIRING_DEFAULT_LIMIT = 8;
var WIRING_MAX_LIMIT = 50;
var WIRING_BUF_CAP = 200;
var WIRING_KINDS = {
  link_fire: "発火",
  recall_boost: "想起",
  ppr_hit: "PPR",
  replay_fire: "リプレイ",
  novelty_gate: "新規性",
  // monologue は意図的にフィードから除外 — 独り言はチャット側の
  // 💭バブル（chat-send.js）で受ける表示専用イベントなので、
  // pushWiringEvent の未知 kind 落としに乗る。
};
var WIRING_BAR_COLORS = {
  link_fire: "linear-gradient(90deg,var(--accent-purple),var(--accent-pink))",
  recall_boost: "linear-gradient(90deg,var(--accent-green),var(--accent-teal))",
  ppr_hit: "linear-gradient(90deg,var(--accent-blue),var(--accent-teal))",
  replay_fire: "linear-gradient(90deg,var(--accent-blue),var(--accent-purple))",
  novelty_gate: "linear-gradient(90deg,var(--accent-yellow),var(--accent-orange))",
};
var _wiringEvents = []; // newest-first
var _wiringMaxSeq = 0;
var _wiringVisible = true;
var _wiringPersona = null; // persona the live socket is scoped to
// Connect flush (up to 200 buffered fires) lands as a burst — hold
// rendering until the window closes, then paint once.
var WIRING_FLUSH_WINDOW_MS = 500;
var _wiringSuspendRender = false;
var _wiringFlushTimer = null;

// Attribute escaping for generated markup goes through N.Core.esc
// (escapes & " ' < >) — no bespoke escAttr helper anymore.

function getFireLimit() {
  try {
    var raw = window.localStorage
      ? window.localStorage.getItem(WIRING_LIMIT_KEY)
      : null;
    if (raw === null || raw === undefined || raw === "") {
      return WIRING_DEFAULT_LIMIT;
    }
    var n = parseInt(raw, 10);
    if (isNaN(n) || n < 0) return WIRING_DEFAULT_LIMIT;
    return Math.min(n, WIRING_MAX_LIMIT);
  } catch (_) {
    return WIRING_DEFAULT_LIMIT;
  }
}

function setFireLimit(n) {
  var v = parseInt(n, 10);
  if (isNaN(v)) v = WIRING_DEFAULT_LIMIT;
  v = Math.max(0, Math.min(WIRING_MAX_LIMIT, v));
  try {
    if (window.localStorage) {
      window.localStorage.setItem(WIRING_LIMIT_KEY, String(v));
    }
  } catch (_) {}
  syncFireLimitInput();
  renderWiringFeed();
  // 0 hides the feed: drop the connection; raising it reconnects.
  if (v <= 0) N.Chat.memoryPanel.disconnectWiring();
  else if (_wiringVisible) N.Chat.memoryPanel.connectWiring();
}

// Feed DOM lives next to reflection (server HTML has no wiring section yet,
// so the client injects it — keeps this feature inside static/ only).
function ensureWiringFeed() {
  if (document.getElementById("memory-wiring-list")) return;
  var panel = document.getElementById("memory-panel");
  if (!panel) return;
  var anchor = document.getElementById("memory-reflection-list");
  var anchorSection = anchor && anchor.closest
    ? anchor.closest(".memory-panel-section")
    : null;
  var section = document.createElement("div");
  section.className = "memory-panel-section";
  section.id = "memory-wiring-section";
  var header = document.createElement("div");
  header.className = "memory-section-header wiring-feed-header";
  safeSetHTML(header,
    '<i data-lucide="zap"></i> 発火' +
    '<span class="wiring-live-dot is-off" aria-hidden="true"></span>');
  var list = document.createElement("div");
  list.id = "memory-wiring-list";
  list.setAttribute("role", "log");
  list.setAttribute("aria-live", "polite");
  list.setAttribute("aria-label", "シナプス発火フィード");
  section.appendChild(header);
  section.appendChild(list);
  if (anchorSection && anchorSection.parentNode === panel) {
    panel.insertBefore(section, anchorSection.nextSibling);
  } else {
    panel.appendChild(section);
  }
  if (typeof N.Core.refreshIcons === "function") N.Core.refreshIcons();
}

// "発火表示数" — numeric setting injected into the reflection settings
// block (same number-input pattern as its neighbours, CSP-safe: the
// listener is bound with addEventListener, never an inline handler).
function ensureFireLimitSetting() {
  if (document.getElementById("chat-wiring-fire-limit")) return;
  // Host: the reflection settings block (its threshold input was removed in
  // v4.0, so resolve the block directly instead of via a control anchor).
  var host = document.querySelector(
    'details[data-category="reflection"] .details-body',
  );
  if (!host) return;
  var row = document.createElement("div");
  var label = document.createElement("div");
  label.className = "chat-field-label";
  label.textContent = "発火表示数（0で非表示）";
  var input = document.createElement("input");
  input.type = "number";
  input.id = "chat-wiring-fire-limit";
  input.className = "chat-field-input";
  input.min = "0";
  input.max = String(WIRING_MAX_LIMIT);
  input.step = "1";
  input.value = String(getFireLimit());
  input.setAttribute("aria-label", "発火フィードの表示数（0で非表示）");
  input.addEventListener("input", function () {
    setFireLimit(input.value);
  });
  input.addEventListener("change", function () {
    setFireLimit(input.value);
  });
  row.appendChild(label);
  row.appendChild(input);
  host.appendChild(row);
}

function syncFireLimitInput() {
  var el = document.getElementById("chat-wiring-fire-limit");
  if (el && document.activeElement !== el) {
    el.value = String(getFireLimit());
  }
}

function _wiringShouldRun() {
  return _wiringVisible && getFireLimit() > 0;
}

function _currentPersona() {
  try {
    if (typeof S !== "undefined" && S && S.persona) return S.persona;
  } catch (_) {}
  return null;
}

function _wiringURL(persona) {
  return WIRING_URL +
    (persona ? "?persona=" + encodeURIComponent(persona) : "");
}

function _updateLiveDot() {
  var dot = document.querySelector("#memory-wiring-section .wiring-live-dot");
  if (!dot) return;
  var on = _wiringShouldRun() && !!N.Core.streamSocket("wiring");
  dot.classList.toggle("is-off", !on);
}

// ── Memory content resolution ──
// Feed rows lead with the memory's content, not its raw ID. Keys resolve
// through /api/memories/{persona}/{key} into a small LRU-ish cache;
// failures are remembered so a deleted memory never retries forever.
var _wiringMemCache = {};    // key -> memory object
var _wiringMemPending = {};  // key -> in-flight promise
var _wiringMemFailed = {};   // key -> true (fetch failed)
var WIRING_MEM_CACHE_CAP = 300;

function _wiringRemember(key, mem) {
  _wiringMemCache[key] = mem || null;
  var keys = Object.keys(_wiringMemCache);
  if (keys.length > WIRING_MEM_CACHE_CAP) {
    keys.slice(0, keys.length - WIRING_MEM_CACHE_CAP).forEach(function (k) {
      delete _wiringMemCache[k];
    });
  }
}

function _wiringSummary(mem) {
  if (!mem || !mem.content) return "";
  var raw = typeof mem.content === "object" && mem.content !== null
    ? JSON.stringify(mem.content) : String(mem.content);
  return raw.replace(/\s+/g, " ").trim();
}

function _wiringKeyShort(key) {
  var s = String(key == null ? "" : key);
  return s.length > 22 ? s.substring(0, 22) + "…" : s;
}

// Resolve unknown source/target keys for the visible rows; one batched
// re-render when the whole batch settles (no per-fetch flicker).
function _wiringEnsureMemories(events, onDone) {
  var persona = _currentPersona();
  if (!persona) return;
  var missing = [];
  events.forEach(function (ev) {
    [ev.source, ev.target].forEach(function (k) {
      if (k && !_wiringMemCache[k] && !_wiringMemPending[k] &&
          !_wiringMemFailed[k] && missing.indexOf(k) === -1) {
        missing.push(k);
      }
    });
  });
  if (!missing.length) return;
  Promise.allSettled(missing.map(function (k) {
    var p = api(
      "/api/memories/" + encodeURIComponent(persona) + "/" + encodeURIComponent(k),
      // Background resolution: a missing key is expected (deleted/consolidated
      // memory) and cached in _wiringMemFailed — never a user-facing toast.
      { suppressErrorToast: true },
    )
      .then(function (d) { _wiringRemember(k, d && d.memory); })
      .catch(function () { _wiringMemFailed[k] = true; })
      .then(function () { delete _wiringMemPending[k]; });
    _wiringMemPending[k] = p;
    return p;
  })).then(onDone).catch(function () {});
}

function _wiringApplyFills(scope) {
  if (N.Components.memoryCard && typeof N.Components.memoryCard.applyDataStyles === "function") {
    N.Components.memoryCard.applyDataStyles(scope);
  }
}

// recall_boost weight sits at ≈1.00 post-boost (monotone) — show the
// recall_count / stability from meta instead; weight stays the fallback
// when meta is absent (legacy events).
function _wiringMetaBadge(ev) {
  if (ev.kind !== "recall_boost") return "";
  var meta = ev.meta && typeof ev.meta === "object" ? ev.meta : {};
  var parts = [];
  var rc = Number(meta.recall_count);
  if (isFinite(rc)) parts.push("×" + rc + "回");
  var st = Number(meta.stability);
  if (isFinite(st)) parts.push("安定 " + st.toFixed(2));
  if (!parts.length) return "";
  var text = parts.join(" · ");
  return '<span class="wiring-meta" title="' + esc(text) + '">' +
    esc(text) + "</span>";
}

function _wiringWeightBar(ev) {
  var w = Number(ev.weight);
  if (!isFinite(w)) return "";
  var pct = Math.max(0, Math.min(100, Math.round(w * 100)));
  var color = WIRING_BAR_COLORS[ev.kind] || WIRING_BAR_COLORS.ppr_hit;
  return '<span class="wiring-weight-bar">' +
    '<span class="wiring-track"><span class="mem-bar-fill" data-fill="' + pct +
    '" data-color="' + esc(color) + '"></span></span>' +
    '<span class="wiring-weight">' + esc(w.toFixed(2)) + "</span></span>";
}

function _renderWiringItem(ev, fresh) {
  var label = WIRING_KINDS[ev.kind] || esc(String(ev.kind));
  var s = ev.source || "";
  var t = ev.target || "";
  var mainKey = t || s;
  var edge = s && t ? s + " → " + t : s || t || "—";
  var mem = _wiringMemCache[mainKey];
  var summary = _wiringSummary(mem);
  var metaBadge = _wiringMetaBadge(ev);
  var tail = metaBadge || _wiringWeightBar(ev);
  var line;
  if (summary) {
    var cut = summary.length > 64 ? summary.substring(0, 64) + "…" : summary;
    line = '<span class="wiring-edge wiring-edge-main" title="' +
      esc(summary) + '">' + esc(cut) + "</span>";
  } else if (mem && mem.kind) {
    // content empty / unrenderable — type-level name fallback
    line = '<span class="wiring-edge wiring-edge-main" title="' +
      esc(edge) + '">' + esc(mem.kind) + "</span>";
  } else {
    // not resolved yet or fetch failed — raw key fallback
    line = '<span class="wiring-edge wiring-edge-main" title="' +
      esc(edge) + '">' + esc(mainKey || "—") + "</span>";
  }
  return (
    '<div class="wiring-fire-item wiring-kind-' + esc(ev.kind) +
    (fresh ? " is-fresh" : "") + '" data-seq="' + esc(ev.seq) + '"' +
    (mainKey
      ? ' data-wiring-open="' + esc(mainKey) + '" role="button" tabindex="0"' +
        ' aria-label="' + esc(label + ": " + (summary || mainKey)) + '"'
      : "") +
    ">" +
    '<span class="wiring-kind-badge">' + label + "</span>" +
    line +
    tail +
    "</div>"
  );
}

function renderWiringFeed() {
  ensureWiringFeed();
  ensureFireLimitSetting();
  var section = document.getElementById("memory-wiring-section");
  var list = document.getElementById("memory-wiring-list");
  if (!section || !list) return;
  var limit = getFireLimit();
  section.classList.toggle("is-hidden", limit <= 0);
  syncFireLimitInput();
  if (limit <= 0) {
    safeSetHTML(list, "");
    return;
  }
  if (_wiringEvents.length === 0) {
    safeSetHTML(list,
      '<div class="memory-empty">発火なし — まだシナプスは静か</div>');
    return;
  }
  var view = _wiringEvents.slice(0, limit);
  safeSetHTML(list, view
    .map(function (ev, i) {
      return _renderWiringItem(ev, i === 0);
    })
    .join(""));
  _wiringApplyFills(list);
  // Content-first rows: resolve unknown memory keys, repaint once settled.
  _wiringEnsureMemories(view, renderWiringFeed);
}

// Reconnect replays the ring buffer, so dedupe by seq (monotonic).
function pushWiringEvent(ev) {
  if (!ev || typeof ev !== "object") return false;
  if (!WIRING_KINDS[ev.kind]) return false;
  var seq = Number(ev.seq);
  if (!isFinite(seq)) seq = 0;
  if (seq > 0) {
    if (seq <= _wiringMaxSeq) return false;
    _wiringMaxSeq = seq;
  }
  _wiringEvents.unshift({
    seq: seq,
    kind: ev.kind,
    source: ev.source || "",
    target: ev.target || "",
    weight: ev.weight,
    meta: ev.meta && typeof ev.meta === "object"
      ? Object.assign({}, ev.meta)
      : {},
  });
  if (_wiringEvents.length > WIRING_BUF_CAP) {
    _wiringEvents.length = WIRING_BUF_CAP;
  }
  // Suppressed while the connect flush lands — one batch paint later.
  if (!_wiringSuspendRender) renderWiringFeed();
  return true;
}

function handleWiringMessage(data) {
  try {
    pushWiringEvent(JSON.parse(data));
  } catch (err) {
    console.warn("[wiring parse]:", err.message);
  }
}

// Persona switch / tests: drop buffered fires and start clean.
function clearWiring() {
  // in-place clear: _wiring.events (wiring-detail) keeps the same
  // array reference — a reassignment would strand it on the old array.
  _wiringEvents.length = 0;
  _wiringMaxSeq = 0;
  renderWiringFeed();
}

// Flush batching: the server greets every connect with `connected`,
// then replays the buffer. Hold paints for one window, then paint once.
function _beginWiringFlush() {
  _wiringSuspendRender = true;
  if (_wiringFlushTimer) clearTimeout(_wiringFlushTimer);
  _wiringFlushTimer = setTimeout(function () {
    _wiringFlushTimer = null;
    _wiringSuspendRender = false;
    renderWiringFeed();
  }, WIRING_FLUSH_WINDOW_MS);
}

function _clearWiringFlush() {
  if (_wiringFlushTimer) {
    clearTimeout(_wiringFlushTimer);
    _wiringFlushTimer = null;
  }
  _wiringSuspendRender = false;
}
// ------------------------------------------------------------------
// Internal cross-chunk table (chunk 2/5) — consumed by the wiring
// stream manager and the fire-detail modal chunks.
// ------------------------------------------------------------------
N.Chat.memoryPanel._wiring = {
  events: _wiringEvents,
  memCache: _wiringMemCache,
  memFailed: _wiringMemFailed,
  memPending: _wiringMemPending,
  kinds: WIRING_KINDS,
  summary: _wiringSummary,
  keyShort: _wiringKeyShort,
  applyFills: _wiringApplyFills,
  ensureMemories: _wiringEnsureMemories,
  shouldRun: _wiringShouldRun,
  currentPersona: _currentPersona,
  wiringURL: _wiringURL,
  ensureFeed: ensureWiringFeed,
  ensureLimit: ensureFireLimitSetting,
  beginFlush: _beginWiringFlush,
  clearFlush: _clearWiringFlush,
  handleMessage: handleWiringMessage,
  updateLiveDot: _updateLiveDot,
  getVisible: function () { return _wiringVisible; },
  setVisible: function (v) { _wiringVisible = !!v; },
  getPersona: function () { return _wiringPersona; },
  setPersona: function (p) { _wiringPersona = p; },
};

// ------------------------------------------------------------------
// Expose on N.Chat.memoryPanel (chunk 2/5 — feed API)
// ------------------------------------------------------------------
Object.assign(N.Chat.memoryPanel, {
  getFireLimit: getFireLimit,
  setFireLimit: setFireLimit,
  pushWiringEvent: pushWiringEvent,
  clearWiring: clearWiring,
  renderWiringFeed: renderWiringFeed,
});
})(window.Nous);
