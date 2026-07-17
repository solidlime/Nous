/* =================================================================
   SSE REAL-TIME EVENTS
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

N.Core.connectSSE = function connectSSE(persona) {
  _setSseStatus("connecting");
  // Clean up old SSE
  if (N.Core._sse) {
    try {
      if (N.Core._sse._sseHandlers) {
        var handlers = N.Core._sse._sseHandlers;
        Object.keys(handlers).forEach(function(ev) {
          N.Core._sse.removeEventListener(ev, handlers[ev]);
        });
      }
      N.Core._sse.onerror = null;
      N.Core._sse.close();
    } catch (e) {
      console.warn("[SSE] close failed:", e.message);
    }
  }
  N.Core._sseBackoff = 5000;
  var es = new EventSource(
    "/api/events/" + encodeURIComponent(persona) +
    "?topics=memory,context,emotion,body"
  );
  es._sseHandlers = {};

  es._sseHandlers["memory.created"] = function handleMemoryCreated(e) {
    try {
      var d = JSON.parse(e.data);
      N.Core.toast("\ud83d\udcdd \u65b0\u3057\u3044\u8a18\u61b6: " +
        (d.content_preview || "...").substring(0, 50), "info");
    } catch (err) { console.warn("[SSE parse] memory.created:", err.message); }
  };
  es.addEventListener("memory.created", es._sseHandlers["memory.created"]);

  es._sseHandlers["memory.updated"] = function handleMemoryUpdated(e) {
    try {
      var d = JSON.parse(e.data);
      N.Core.toast("\ud83d\udd04 \u8a18\u61b6\u66f4\u65b0: " +
        (d.content_preview || "...").substring(0, 50), "info");
    } catch (err) { console.warn("[SSE parse] memory.updated:", err.message); }
  };
  es.addEventListener("memory.updated", es._sseHandlers["memory.updated"]);

  es._sseHandlers["memory.deleted"] = function handleMemoryDeleted(e) {
    try {
      var d = JSON.parse(e.data);
      N.Core.toast("\ud83d\uddd1 \u8a18\u61b6\u524a\u9664: " +
        (d.content_preview || "...").substring(0, 50), "info");
    } catch (err) { console.warn("[SSE parse] memory.deleted:", err.message); }
  };
  es.addEventListener("memory.deleted", es._sseHandlers["memory.deleted"]);

  es.addEventListener("context.updated", function(e) {
    N.Core.toast("\ud83d\udc64 \u30b3\u30f3\u30c6\u30ad\u30b9\u30c8\u66f4\u65b0\u3055\u308c\u307e\u3057\u305f", "info");
  });

  es.addEventListener("context.emotion_changed", function(e) {
    try {
      var d = JSON.parse(e.data);
      if (d.emotion) {
        N.Core.toast("\ud83d\ude0c \u611f\u60c5\u5909\u66f4: " + d.emotion +
          " (" + Math.round((d.emotion_intensity || 0) * 100) + "%)", "info");
        window.dispatchEvent(new CustomEvent("emotion-changed", { detail: d }));
      }
    } catch (err) { console.warn("[SSE parse] context.emotion_changed:", err.message); }
  });

  es.addEventListener("context.body_state_changed", function(e) {
    try {
      var d = JSON.parse(e.data);
      if (d.states) {
        var labels = { fatigue: "\ud83d\udd25", warmth: "\ud83c\udf3c", arousal: "\u26a1", heart_rate: "\ud83d\udc93", pain: "\ud83d\udcaa" };
        var parts = Object.entries(d.states)
          .filter(function(kv) { return kv[1] != null; })
          .map(function(kv) { return (labels[kv[0]] || kv[0]) + " " + Math.round(Number(kv[1]) * 100) + "%"; });
        if (parts.length) {
          N.Core.toast("\ud83e\udda0 \u4f53\u8abf\u5909\u66f4: " + parts.join(" "), "info");
        }
        window.dispatchEvent(new CustomEvent("body-state-changed", { detail: d }));
      }
    } catch (err) { console.warn("[SSE parse] context.body_state_changed:", err.message); }
  });
  es.onopen = function handleSSEOpen() {
    _setSseStatus("connected");
    N.Core._sseBackoff = 5000;
  };

  es.onerror = function handleSSEError() {
    N.Core._sse = null;
    _setSseStatus("reconnecting");
    var backoff = N.Core._sseBackoff || 5000;
    N.Core._sseBackoff = Math.min(backoff * 2, 60000);
    setTimeout(function() {
      var p = N.Core.store ? N.Core.store.get("persona") : null;
      if (p) N.Core.connectSSE(p);
    }, backoff);
  };
  N.Core._sse = es;
};

window.connectSSE = N.Core.connectSSE;
})(window.Nous);
