/* =================================================================
   CHAT SEND MONOLOGUE — REM monologue display-only whispers
   Chunk 5/5 of chat-send.js. Namespace: N.Chat.monologue.*
   Depends on: send/render.js (N.Chat.ui.findLog), chat-core.js,
   components/mem-modal.js. The connectSSE persona funnel (which calls
   N.Chat.monologue.connect) lives in send/turn.js.
   ================================================================= */
;(function(N) {
var C = N.Core;
var api = C.api, esc = C.esc, toast = C.toast, safeSetHTML = C.safeSetHTML;
var showConfirm = C.showConfirm, showAlert = C.showAlert;
var truncate = C.truncate, relativeTime = C.relativeTime, fmtDate = C.fmtDate;
var fmtStamp = C.fmtStamp;
"use strict";
var S = window.S;

// ------------------------------------------------------------------
var MONOLOGUE_URL = "/api/memory/wiring/stream";
var _monologuePersona = null;
var _monologueMaxSeq = 0;

function _tsEpoch(ts) {
  if (typeof ts !== "string" || !ts) return NaN;
  var n = Date.parse(ts);
  return isFinite(n) ? n : NaN;
}

// First message node strictly newer than the whisper's timestamp —
// epoch-ms comparison (ISO strings with mixed offsets sort wrong).
function findMonologueAnchor(container, ts) {
  var epoch = _tsEpoch(ts);
  if (isNaN(epoch)) return null;
  var nodes = container.children;
  for (var i = 0; i < nodes.length; i++) {
    var t = _tsEpoch(nodes[i].dataset && nodes[i].dataset.ts);
    if (!isNaN(t) && t > epoch) return nodes[i];
  }
  return null;
}

// Re-slot every existing whisper after history prepends new older
// messages (loadOlderMessages): remove-free reorder in place.
function reslotMonologueBubbles() {
  var container = N.Chat.ui.findLog();
  if (!container) return;
  var movable = [];
  container.querySelectorAll(".chat-monologue-bubble").forEach(function (b) {
    if (!isNaN(_tsEpoch(b.dataset && b.dataset.ts))) movable.push(b);
  });
  movable.sort(function (a, b) { return _tsEpoch(a.dataset.ts) - _tsEpoch(b.dataset.ts); });
  movable.forEach(function (b) {
    container.insertBefore(b, findMonologueAnchor(container, b.dataset.ts));
  });
}

function appendMonologueBubble(text, ts, kind) {
  if (!text || typeof text !== "string") return;
  var container = N.Chat.ui.findLog();
  if (!container) return;
  var isExploration = kind === "exploration";
  var bubble = document.createElement("details");
  bubble.className = "chat-monologue-bubble";
  bubble.dataset.ts = ts || "";
  if (isExploration) bubble.dataset.kind = "exploration";
  var summary = document.createElement("summary");
  summary.textContent = isExploration ? "🔍 調べたこと" : "💭 独り言";
  // The canonical reader is the memory modal (keyless preview — no
  // Edit/Delete); suppress the native details toggle so the click does
  // exactly one legible thing. CSP-safe: listener, no inline handler.
  summary.addEventListener("click", function (e) {
    e.preventDefault();
    if (N.Components && N.Components.memModal &&
        typeof N.Components.memModal.openMemory === "function") {
      N.Components.memModal.openMemory({
        content: text,
        tags: isExploration ? ["monologue", "exploration"] : ["monologue"],
      });
    }
  });
  // Timestamp rides in the summary, not the details body: the bubble
  // renders collapsed (the modal is the canonical reader), so a label
  // inside the body would stay display:none and never be seen.
  if (!isNaN(_tsEpoch(ts))) {
    var timeSpan = document.createElement("span");
    timeSpan.className = "chat-time chat-monologue-time";
    timeSpan.textContent = fmtStamp(ts);
    summary.appendChild(timeSpan);
  }
  var body = document.createElement("div");
  body.className = "chat-monologue-text";
  body.textContent = text; // CSP-safe: textContent, never parsed as HTML
  bubble.appendChild(summary);
  bubble.appendChild(body);
  // Restored whispers carry their ISO timestamp — slot them between
  // messages in conversation order instead of the tail. Live whispers
  // (no parseable timestamp) keep append-at-end, which IS their order.
  var anchor = findMonologueAnchor(container, ts);
  if (anchor) container.insertBefore(bubble, anchor);
  else container.appendChild(bubble);
  // Follow the stream only while the user is already at the bottom
  if (container.scrollHeight - container.scrollTop - container.clientHeight < 80) {
    container.scrollTop = container.scrollHeight;
  }
}

function handleMonologueWiring(data) {
  try {
    var evt = JSON.parse(data);
    if (!evt || evt.kind !== "monologue") return;
    // The endpoint flushes its whole ring buffer (last_seq=0) on every
    // connect, so a reconnect re-delivers old monologues as if fresh.
    // Same seq dedupe as the panel's pushWiringEvent.
    var seq = Number(evt.seq);
    if (isFinite(seq) && seq > 0) {
      if (seq <= _monologueMaxSeq) return;
      _monologueMaxSeq = seq;
    }
    var meta = evt.meta || {};
    // Stale socket from a previous persona: drop quietly.
    if (meta.persona && window.S && meta.persona !== window.S.persona) return;
    // kind="exploration" は reload (restoreMonologueBubbles) と同じ 🔍 ラベルにする
    appendMonologueBubble(meta.text, meta.timestamp, meta.kind);
  } catch (err) {
    console.warn("[monologue wiring parse]:", err.message);
  }
}

function connectMonologueStream(persona) {
  _monologuePersona = persona || (window.S && window.S.persona) || null;
  // Persona switch: replayed buffer entries for the new persona must
  // render once — start the seq guard from zero (clearWiring's twin).
  _monologueMaxSeq = 0;
  N.Core.connectStream("wiring-chat", {
    url: function () {
      return _monologuePersona
        ? MONOLOGUE_URL + "?persona=" + encodeURIComponent(_monologuePersona)
        : null;
    },
    handlers: {
      wiring: function (e) { handleMonologueWiring(e.data); },
    },
  });
}
// ------------------------------------------------------------------
// Expose on N.Chat (chunk 5/5 — monologue API)
// ------------------------------------------------------------------
N.Chat.monologue = {
  append: appendMonologueBubble,
  reslot: reslotMonologueBubbles,
  handle: handleMonologueWiring,
  connect: connectMonologueStream,
};
})(window.Nous);
