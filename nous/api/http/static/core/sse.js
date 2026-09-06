/* =================================================================
   SSE REAL-TIME EVENTS — named multi-stream manager
   ================================================================= */
;(function(N) {
"use strict";

/* SSE status indicator helpers */
function _setSseStatus(state) {
  var el = document.getElementById("sse-status");
  if (!el) return;
  el.className = "sse-indicator sse-" + state;
  var labels = { connected: "接続済み", connecting: "接続中...", reconnecting: "再接続中...", error: "接続エラー" };
  el.title = labels[state] || state;
}

/* ── Stream engine ──
   Each named stream owns its socket plus reconnect state: single-flight
   timer, exponential backoff (5s → 60s cap), handler set (detached on
   teardown). The URL is re-evaluated on every (re)connect — url() for
   the initial connect, reconnectUrl() (falling back to url()) for
   scheduled reconnects — so persona switches and gates are picked up
   without re-registering handlers. url() returning null opens nothing
   (gated streams). */
function _streams() {
  return (N.Core._sseStreams = N.Core._sseStreams || {});
}

function _detachHandlers(rec, es) {
  if (!rec.handlers || !es || typeof es.removeEventListener !== "function") return;
  Object.keys(rec.handlers).forEach(function (ev) {
    es.removeEventListener(ev, rec.handlers[ev]);
  });
}

function _closeSocket(rec) {
  var es = rec.socket;
  if (!es) return;
  try {
    _detachHandlers(rec, es);
    es.onerror = null;
    es.onopen = null;
    es.close();
  } catch (e) {
    console.warn("[SSE] close failed:", e.message);
  }
  rec.socket = null;
}

function _open(name, reconnect) {
  var rec = _streams()[name], opts = rec.opts;
  var url = reconnect && opts.reconnectUrl ? opts.reconnectUrl() : opts.url();
  if (!url) return;
  var es = new EventSource(url);
  rec.socket = es;
  rec.handlers = {};
  Object.keys(opts.handlers).forEach(function (ev) {
    rec.handlers[ev] = opts.handlers[ev];
    es.addEventListener(ev, opts.handlers[ev]);
  });
  if (opts.onConnecting) opts.onConnecting(es);
  es.onopen = function () {
    rec.backoff = opts.initialBackoff || 5000;
    if (opts.onOpen) opts.onOpen(es);
  };
  es.onerror = function () {
    try { es.close(); } catch (_) {}
    if (rec.socket === es) rec.socket = null;
    if (opts.onError && opts.onError(es) === false) return;
    var backoff = rec.backoff || opts.initialBackoff || 5000;
    rec.backoff = Math.min(backoff * 2, opts.maxBackoff || 60000);
    /* Single-flight reconnect: exactly one pending timer */
    if (rec.timer) clearTimeout(rec.timer);
    rec.timer = setTimeout(function () {
      rec.timer = null;
      _open(name, true);
    }, backoff);
  };
}

N.Core.connectStream = function connectStream(name, opts) {
  var rec = _streams()[name] || (_streams()[name] = { socket: null });
  if (rec.timer) {
    clearTimeout(rec.timer);
    rec.timer = null;
  }
  rec.opts = opts;
  rec.backoff = opts.initialBackoff || 5000;
  _closeSocket(rec);
  _open(name, false);
};

N.Core.streamSocket = function streamSocket(name) {
  var rec = _streams()[name];
  return rec ? rec.socket : null;
};

N.Core.disconnectStream = function disconnectStream(name) {
  var rec = _streams()[name];
  if (!rec) return;
  if (rec.timer) {
    clearTimeout(rec.timer);
    rec.timer = null;
  }
  _closeSocket(rec);
};

/* ── Main event stream (all tabs) ── */
var MAIN_EVENTS_URL = function MAIN_EVENTS_URL(persona) {
  return "/api/events/" + encodeURIComponent(persona) +
    "?topics=memory,context,emotion,body,session";
};

var MAIN_HANDLERS = {
  "memory.created": function handleMemoryCreated(e) {
    try {
      var d = JSON.parse(e.data);
      N.Core.toast("\ud83d\udcdd \u65b0\u3057\u3044\u8a18\u61b6: " +
        (d.content_preview || "...").substring(0, 50), "info");
      _scheduleMemoriesRefresh();
    } catch (err) { console.warn("[SSE parse] memory.created:", err.message); }
  },
  "memory.updated": function handleMemoryUpdated(e) {
    try {
      var d = JSON.parse(e.data);
      N.Core.toast("\ud83d\udd04 \u8a18\u61b6\u66f4\u65b0: " +
        (d.content_preview || "...").substring(0, 50), "info");
      _scheduleMemoriesRefresh();
    } catch (err) { console.warn("[SSE parse] memory.updated:", err.message); }
  },
  "memory.deleted": function handleMemoryDeleted(e) {
    try {
      var d = JSON.parse(e.data);
      N.Core.toast("\ud83d\uddd1 \u8a18\u61b6\u524a\u9664: " +
        (d.content_preview || "...").substring(0, 50), "info");
      _scheduleMemoriesRefresh();
    } catch (err) { console.warn("[SSE parse] memory.deleted:", err.message); }
  },
  "context.updated": function handleContextUpdated(e) {
    N.Core.toast("\ud83d\udc64 \u30b3\u30f3\u30c6\u30ad\u30b9\u30c8\u66f4\u65b0\u3055\u308c\u307e\u3057\u305f", "info");
  },
  "context.emotion_changed": function handleEmotionChanged(e) {
    try {
      var d = JSON.parse(e.data);
      if (d.emotion) {
        N.Core.toast("\ud83d\ude0c \u611f\u60c5\u5909\u66f4: " + d.emotion +
          " (" + Math.round((d.emotion_intensity || 0) * 100) + "%)", "info");
        window.dispatchEvent(new CustomEvent("emotion-changed", { detail: d }));
      }
    } catch (err) { console.warn("[SSE parse] context.emotion_changed:", err.message); }
  },
  "context.body_state_changed": function handleBodyStateChanged(e) {
    try {
      var d = JSON.parse(e.data);
      if (d.states) {
        var labels = { fatigue: "\ud83d\udd25", warmth: "\ud83c\udf3c", arousal: "\u26a1", heart_rate: "\ud83d\udc93", pain: "\ud83d\udcaa" };
        var parts = Object.entries(d.states)
          .filter(function(kv) { return kv[1] != null; })
          .map(function(kv) {
            var val = Number(kv[1]);
            if (isNaN(val)) {
              return (labels[kv[0]] || kv[0]) + " " + kv[1];
            }
            return (labels[kv[0]] || kv[0]) + " " + Math.round(val * 100) + "%";
          });
        if (parts.length) {
          N.Core.toast("\ud83e\udda0 \u4f53\u8abf\u5909\u66f4: " + parts.join(" "), "info");
        }
        window.dispatchEvent(new CustomEvent("body-state-changed", { detail: d }));
      }
    } catch (err) { console.warn("[SSE parse] context.body_state_changed:", err.message); }
  },
  "session.rollback": function handleSessionRollback(e) {
    try {
      var d = JSON.parse(e.data);
      // Only sync if the rollback is for the current chat session (cross-tab sync)
      var currentPersona = (typeof S !== "undefined" && S.persona) ? S.persona : null;
      var currentSessionId = (typeof getChatSessionId === "function") ? getChatSessionId() : null;
      var matchesSession = currentPersona && d.persona === currentPersona &&
                           currentSessionId && d.session_id === currentSessionId;
      if (matchesSession && typeof restoreChatHistory === "function") {
        restoreChatHistory(false);
      }
    } catch (err) { console.warn("[SSE parse] session.rollback:", err.message); }
  },
};

N.Core.connectSSE = function connectSSE(persona) {
  N.Core.connectStream("main", {
    url: function () { return MAIN_EVENTS_URL(persona); },
    // Scheduled reconnects follow the live persona from the store.
    reconnectUrl: function () {
      var p = N.Core.store ? N.Core.store.get("persona") : null;
      return p ? MAIN_EVENTS_URL(p) : null;
    },
    handlers: MAIN_HANDLERS,
    onConnecting: function () { _setSseStatus("connecting"); },
    onOpen: function () { _setSseStatus("connected"); },
    onError: function () { _setSseStatus("reconnecting"); },
  });
};

/* Tear down the main stream + cancel any pending reconnect (page hide / unload) */
N.Core.disconnectSSE = function disconnectSSE() {
  N.Core.disconnectStream("main");
};

/* Memories tab debounced refresh — called from memory SSE handlers */
var _memoriesRefreshTimer = null;
function _scheduleMemoriesRefresh() {
    if (_memoriesRefreshTimer) clearTimeout(_memoriesRefreshTimer);
    _memoriesRefreshTimer = setTimeout(function() {
        if (typeof S !== "undefined" && S.tab === "memories" && typeof N.Features.Memories.loadMemories === "function") {
            N.Features.Memories.loadMemories();
        }
        _memoriesRefreshTimer = null;
    }, 500);
}
})(window.Nous);
