/* =================================================================
   CHAT MEMORY PANEL WIRING-STREAM — wiring SSE connect/disconnect,
   persona switch, panel-visibility gating, connectSSE funnels
   Chunk 3/5 of chat-memory-panel.js. Namespace: N.Chat.memoryPanel.*
   Depends on: memory-panel/wiring.js (N.Chat.memoryPanel._wiring +
   renderWiringFeed), core/sse.js.
   ================================================================= */
;(function(N) {
var C = N.Core;
var api = C.api, esc = C.esc, toast = C.toast, safeSetHTML = C.safeSetHTML;
var showConfirm = C.showConfirm, showAlert = C.showAlert;
var truncate = C.truncate, relativeTime = C.relativeTime, fmtDate = C.fmtDate, fmtDateTime = C.fmtDateTime;
"use strict";
var S = window.S;


// Wiring SSE rides the shared core stream manager (core/sse.js):
// single-flight, backoff 5000→60s cap and handler detach live there.
// url() re-evaluates the gate + persona on every (re)connect.
function connectWiring() {
  N.Chat.memoryPanel._wiring.clearFlush();
  if (!N.Chat.memoryPanel._wiring.shouldRun()) {
    N.Core.disconnectStream("wiring");
    N.Chat.memoryPanel._wiring.updateLiveDot();
    return;
  }
  var persona = N.Chat.memoryPanel._wiring.getPersona() || N.Chat.memoryPanel._wiring.currentPersona();
  N.Chat.memoryPanel._wiring.setPersona(persona || null);
  N.Chat.memoryPanel._wiring.ensureFeed();
  N.Core.connectStream("wiring", {
    url: function () {
      return N.Chat.memoryPanel._wiring.shouldRun() && N.Chat.memoryPanel._wiring.getPersona()
        ? N.Chat.memoryPanel._wiring.wiringURL(N.Chat.memoryPanel._wiring.getPersona())
        : null;
    },
    handlers: {
      wiring: function (e) {
        N.Chat.memoryPanel._wiring.handleMessage(e.data);
      },
      // Server greets every connect with `connected`, then replays the
      // buffer. Hold paints for one window, then paint once.
      connected: function () {
        N.Chat.memoryPanel._wiring.beginFlush();
      },
    },
    // Main-stream manners: a healthy open resets the backoff.
    onOpen: function () {
      N.Chat.memoryPanel._wiring.updateLiveDot();
    },
    onError: function () {
      N.Chat.memoryPanel._wiring.updateLiveDot();
      return N.Chat.memoryPanel._wiring.shouldRun();
    },
  });
  N.Chat.memoryPanel._wiring.updateLiveDot();
}

function disconnectWiring() {
  N.Core.disconnectStream("wiring");
  N.Chat.memoryPanel._wiring.clearFlush();
  N.Chat.memoryPanel._wiring.updateLiveDot();
}

// Persona switch: drop the old feed and rescope the stream. Wired into
// the main SSE connect (base.js persona-select init + change both funnel
// through N.Core.connectSSE), so no other hook point is needed.
function switchWiringPersona(persona) {
  if (!persona) persona = N.Chat.memoryPanel._wiring.currentPersona();
  if (persona && persona === N.Chat.memoryPanel._wiring.getPersona() && N.Core.streamSocket("wiring")) return;
  N.Chat.memoryPanel._wiring.setPersona(persona || null);
  N.Chat.memoryPanel.clearWiring();
  if (N.Chat.memoryPanel._wiring.getVisible()) connectWiring();
  else disconnectWiring();
}

// Panel hidden ⇒ cut the stream; reshown ⇒ reconnect (single-flight).
function setWiringVisible(open) {
  N.Chat.memoryPanel._wiring.setVisible(!!open);
  if (N.Chat.memoryPanel._wiring.getVisible()) connectWiring();
  else disconnectWiring();
}

// Persona select (init + change) funnels through the main SSE connect —
// mirror it so the wiring stream always follows the active persona
// (wraps once, even under script double-load).
if (typeof N.Core.connectSSE === "function" &&
    !N.Core._wiringConnectWrapped) {
  N.Core._wiringConnectWrapped = true;
  (function () {
    var _origConnect = N.Core.connectSSE;
    N.Core.connectSSE = function (persona) {
      var r = _origConnect.apply(this, arguments);
      try { switchWiringPersona(persona); } catch (_) {}
      return r;
    };
  })();
}

// beforeunload tears down the main SSE via disconnectSSE — take the
// wiring stream down with it (wraps once, even under script double-load).
if (typeof N.Core.disconnectSSE === "function" &&
    !N.Core._wiringDisconnectWrapped) {
  N.Core._wiringDisconnectWrapped = true;
  (function () {
    var _origDisconnect = N.Core.disconnectSSE;
    N.Core.disconnectSSE = function () {
      try { disconnectWiring(); } catch (_) {}
      return _origDisconnect.apply(this, arguments);
    };
  })();
}

// Feed + setting exist from first paint; the stream itself starts when
// the chat core restores panel visibility (loadChat / toggleMemory).
N.Chat.memoryPanel._wiring.ensureFeed();
N.Chat.memoryPanel._wiring.ensureLimit();
N.Chat.memoryPanel.renderWiringFeed();
// ------------------------------------------------------------------
// Expose on N.Chat.memoryPanel (chunk 3/5 — stream API)
// ------------------------------------------------------------------
Object.assign(N.Chat.memoryPanel, {
  connectWiring: connectWiring,
  disconnectWiring: disconnectWiring,
  switchWiringPersona: switchWiringPersona,
  setWiringVisible: setWiringVisible,
});
})(window.Nous);
