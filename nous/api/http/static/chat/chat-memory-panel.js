/* =================================================================
   CHAT MEMORY PANEL — Memory panel CRUD, reflection, session UI
   Extracted from chat.js (Phase 3, Batch 2)
   ================================================================= */
;(function(N) {
var C = N.Core;
var api = C.api, esc = C.esc, toast = C.toast, safeSetHTML = C.safeSetHTML;
var showConfirm = C.showConfirm, showAlert = C.showAlert;
var truncate = C.truncate, relativeTime = C.relativeTime, fmtDate = C.fmtDate;
"use strict";
var S = window.S;
// Namespace first: the delegation block below reads N.Chat.memoryPanel,
// and the expose block uses Object.assign so a double-load keeps _delegated.
N.Chat.memoryPanel = N.Chat.memoryPanel || {};

// ------------------------------------------------------------------
// Memory panel update (retrieved / saved / goals)
// ------------------------------------------------------------------
function updateMemoryPanel(retrieved, saved, goals, promises) {
  const panel = document.getElementById("memory-panel");
  if (!panel || panel.style.display === "none") return;
  const escAttr = (s) =>
    String(s)
      .replace(/&/g, "&amp;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;");
  if (retrieved !== undefined) {
    const retrievedList = document.getElementById("memory-retrieved-list");
    if (retrievedList) {
      if (!retrieved || retrieved.length === 0) {
        safeSetHTML(retrievedList, '<div class="memory-empty">なし</div>');
      } else {
        safeSetHTML(retrievedList, retrieved
          .map((m) => {
            const score = m.score != null ? parseFloat(m.score).toFixed(3) : "";
            const imp =
              m.importance != null ? parseFloat(m.importance).toFixed(2) : "";
            var _raw = typeof m.content === "object" && m.content !== null ? JSON.stringify(m.content) : String(m.content || "");
            const content = esc(_raw.substring(0, 80));
            const meta = [
              score ? "score:" + score : "",
              imp ? "imp:" + imp : "",
            ]
              .filter(Boolean)
              .join(" ");
            const key = m.key || "";
            const emotionBadges = N.Components.memoryCard.renderEmotionBadges(
              m.emotion,
              m.emotion_intensity,
            );
            const bodyCompact = N.Components.memoryCard.renderBodyStateCompact(m.body_state);
            const extra = [emotionBadges, bodyCompact]
              .filter(Boolean)
              .join(" ");
            var _contentStr = typeof m.content === "object" && m.content !== null ? JSON.stringify(m.content) : String(m.content || "");
            return (
              '<div class="memory-item-card" title="' + escAttr(meta) + '" data-key="' +
              escAttr(key) +
              '" data-content="' +
              escAttr(_contentStr) +
              '" data-importance="' +
              (m.importance || 0.5) +
              '" data-tags="' +
              escAttr((m.tags || []).join(",")) +
              '">' +
              content +
              (extra
                ? '<div class="mem-score mem-score-extra">' +
                  extra +
                  "</div>"
                : "") +
              '<div class="mem-actions"><button type="button" class="mem-action-btn del" data-mem-action="delete" data-mem-key="' +
              escAttr(key) +
              '">削除</button></div>' +
              "</div>"
            );
          })
          .join(""));
      }
    }
  }
  if (saved !== undefined) {
    const savedList = document.getElementById("memory-saved-list");
    if (savedList) {
      if (!saved || saved.length === 0) {
        safeSetHTML(savedList, '<div class="memory-empty">なし</div>');
      } else {
        safeSetHTML(savedList, saved
          .map((m) => {
            var _raw = typeof m.content === "object" && m.content !== null ? JSON.stringify(m.content) : String(m.content || "");
            const content = esc(_raw.substring(0, 80));
            const key = m.key || "";
            const emotionBadges = N.Components.memoryCard.renderEmotionBadges(
              m.emotion,
              m.emotion_intensity,
            );
            const bodyCompact = N.Components.memoryCard.renderBodyStateCompact(m.body_state);
            const extra = [emotionBadges, bodyCompact]
              .filter(Boolean)
              .join(" ");
            var _contentStr = typeof m.content === "object" && m.content !== null ? JSON.stringify(m.content) : String(m.content || "");
            return (
              '<div class="memory-item-card" data-key="' +
              escAttr(key) +
              '" data-content="' +
              escAttr(_contentStr) +
              '" data-importance="' +
              (m.importance || 0.5) +
              '" data-tags="' +
              escAttr((m.tags || []).join(",")) +
              '">' +
              content +
              (extra
                ? '<div class="mem-score mem-score-extra">' +
                  extra +
                  "</div>"
                : "") +
              '<div class="mem-actions"><button type="button" class="mem-action-btn del" data-mem-action="delete" data-mem-key="' +
              escAttr(key) +
              '">削除</button></div>' +
              "</div>"
            );
          })
          .join(""));
      }
    }
  }
  if (goals !== undefined) {
    const goalsList = document.getElementById("memory-goals-list");
    if (goalsList) {
      if (!goals || goals.length === 0) {
        safeSetHTML(goalsList, '<div class="memory-empty">なし</div>');
      } else {
        safeSetHTML(goalsList, goals
          .map((g) => {
            const key = g.key || "";
            const actionBadge = (g.action && g.action !== "create")
              ? '<span class="mem-action-badge">更新</span> ' : "";
            return (
              '<div class="memory-item-card" data-key="' +
              escAttr(key) +
              '" data-content="' +
              escAttr(g.content || "") +
              '" data-importance="' +
              (g.importance || 0.75) +
              '" data-tags="' +
              escAttr((g.tags || []).join(",")) +
              '">' +
              '<i data-lucide="target"></i> ' +
              actionBadge +
              esc((g.content || "").substring(0, 80)) +
              '<div class="mem-actions"><button type="button" class="mem-action-btn done" data-mem-action="complete" data-mem-key="' +
              escAttr(key) +
              '" data-mem-content="' +
              escAttr((g.content || "").substring(0, 50)) +
              '">完了</button><button type="button" class="mem-action-btn del" data-mem-action="delete" data-mem-key="' +
              escAttr(key) +
              '">削除</button></div>' +
              "</div>"
            );
          })
          .join(""));
      }
    }
  }
  if (promises !== undefined) {
    const promisesList = document.getElementById("memory-promises-list");
    if (promisesList) {
      if (!promises || promises.length === 0) {
        safeSetHTML(promisesList, '<div class="memory-empty">なし</div>');
      } else {
        safeSetHTML(promisesList, promises
          .map((g) => {
            const key = g.key || "";
            const actionBadge = (g.action && g.action !== "create")
              ? '<span class="mem-action-badge">更新</span> ' : "";
            return (
              '<div class="memory-item-card" data-key="' +
              escAttr(key) +
              '" data-content="' +
              escAttr(g.content || "") +
              '" data-importance="' +
              (g.importance || 0.8) +
              '" data-tags="' +
              escAttr((g.tags || []).join(",")) +
              '">' +
              '<i data-lucide="handshake"></i> ' +
              actionBadge +
              esc((g.content || "").substring(0, 80)) +
              '<div class="mem-actions"><button type="button" class="mem-action-btn del" data-mem-action="delete" data-mem-key="' +
              escAttr(key) +
              '">削除</button></div>' +
              "</div>"
            );
          })
          .join(""));
      }
    }
  }
}

// ------------------------------------------------------------------
// Reflection panel (insights via commitments polling; no streaming SSE)
// ------------------------------------------------------------------
function updateReflectionPanel(insights) {
  const header = document.getElementById("reflection-header");
  if (header) {
    safeSetHTML(header, '<i data-lucide="sparkles"></i> リフレクション');
    if (typeof lucide !== "undefined") lucide.createIcons();
  }
  const list = document.getElementById("memory-reflection-list");
  if (!list) return;
  if (!insights || insights.length === 0) {
    safeSetHTML(list, '<div class="memory-empty">洞察なし</div>');
    return;
  }
  safeSetHTML(list, insights
    .map((s) => '<div class="reflection-insight">' + esc(s) + "</div>")
    .join(""));
}

function showSessionSummarized(summary) {
  const statusEl = document.getElementById("chat-status");
  if (statusEl) {
    safeSetHTML(statusEl,
      '<i data-lucide="edit-3"></i> セッションを要約しました');
    setTimeout(() => {
      if (statusEl) statusEl.textContent = "";
    }, 3000);
  }
}

function showContextCompressed(evt) {
  const beforePct = evt.budget ? Math.round((evt.before_tokens / evt.budget) * 100) : 0;
  const afterPct = evt.budget ? Math.round((evt.after_tokens / evt.budget) * 100) : 0;
  const savings = evt.before_tokens - evt.after_tokens;
  toast(
    "🧠 圧縮: " +
      evt.before_tokens +
      "→" +
      evt.after_tokens +
      " トークン (" +
      beforePct +
      "%→" +
      afterPct +
      "% 予算比) " +
      ((savings / evt.before_tokens) * 100).toFixed(0) +
      "%削減",
    "info",
  );
}

// ------------------------------------------------------------------
// Memory CRUD operations
// ------------------------------------------------------------------
async function deleteMemCard(key) {
  if (!key || !S.persona) return;
  showConfirm("このメモリを削除しますか？", async function () {
    try {
      await api(
        "/api/memories/" +
          encodeURIComponent(S.persona) +
          "/" +
          encodeURIComponent(key),
        {
          method: "DELETE",
        },
      );
      toast("メモリを削除しました", "success");
      N.Chat.core.loadCommitments(); // refresh panels
    } catch (e) {
      toast("削除失敗: " + e.message, "error");
    }
  });
}

async function completeGoal(key, content) {
  if (!S.persona) return;
  try {
    const resp = await api(
      "/api/chat/" + encodeURIComponent(S.persona) + "/tool",
      {
        method: "POST",
        body: JSON.stringify({
          tool: "goal_manage",
          input: { operation: "achieve", content, memory_key: key },
        }),
      },
    );
    if (resp.status === "ok") {
      toast("目標を達成しました: " + (resp.updated || content), "success");
      N.Chat.core.loadCommitments();
    } else {
      toast("完了失敗: " + (resp.message || ""), "error");
    }
  } catch (e) {
    toast("エラー: " + e.message, "error");
  }
}

// ------------------------------------------------------------------
// CSP-safe delegation: no inline onclick (script-src 'self').
// Buttons carry data-mem-action="delete|complete" + data-mem-key.
// ------------------------------------------------------------------
if (typeof document !== "undefined" && !N.Chat.memoryPanel._delegated) {
  N.Chat.memoryPanel._delegated = true;
  document.addEventListener("click", function (e) {
    var btn = e.target && e.target.closest ? e.target.closest("[data-mem-action]") : null;
    if (!btn) return;
    e.stopPropagation();
    var action = btn.getAttribute("data-mem-action");
    var key = btn.getAttribute("data-mem-key");
    if (action === "delete" && key) {
      if (typeof N.Chat.memoryPanel.deleteCard === "function") N.Chat.memoryPanel.deleteCard(key);
    } else if (action === "complete" && key) {
      var content = btn.getAttribute("data-mem-content") || "";
      if (typeof N.Chat.memoryPanel.completeGoal === "function") N.Chat.memoryPanel.completeGoal(key, content);
    }
  });
}

// ------------------------------------------------------------------
// Wiring fire feed — live synapse pulses (GET /api/memory/wiring/stream)
// Server flushes its ring buffer on connect, then pushes live events:
//   {seq, kind, source, target, weight, meta}
//   kind ∈ {link_fire, recall_boost, ppr_hit} — no server-side thinning.
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
};
var _wiringEvents = []; // newest-first
var _wiringMaxSeq = 0;
var _wiringVisible = true;

function _wiringEscAttr(s) {
  return String(s == null ? "" : s)
    .replace(/&/g, "&amp;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

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
  if (v <= 0) disconnectWiring();
  else if (_wiringVisible) connectWiring();
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
  var anchor = document.getElementById("chat-reflection-threshold");
  var host = anchor && anchor.closest
    ? anchor.closest(".details-body")
    : null;
  if (!host) {
    host = document.querySelector(
      'details[data-category="reflection"] .details-body',
    );
  }
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

function _updateLiveDot() {
  var dot = document.querySelector("#memory-wiring-section .wiring-live-dot");
  if (!dot) return;
  var on = _wiringShouldRun() && !!N.Core._wiringSSE;
  dot.classList.toggle("is-off", !on);
}

function _renderWiringItem(ev, fresh) {
  var label = WIRING_KINDS[ev.kind] || esc(String(ev.kind));
  var s = ev.source || "";
  var t = ev.target || "";
  var edge = s && t ? s + " → " + t : s || t || "—";
  var w = Number(ev.weight);
  var weight = isFinite(w) ? w.toFixed(2) : "";
  return (
    '<div class="wiring-fire-item wiring-kind-' + _wiringEscAttr(ev.kind) +
    (fresh ? " is-fresh" : "") + '" data-seq="' + _wiringEscAttr(ev.seq) + '">' +
    '<span class="wiring-kind-badge">' + label + "</span>" +
    '<span class="wiring-edge" title="' + _wiringEscAttr(edge) + '">' +
    esc(edge) + "</span>" +
    (weight
      ? '<span class="wiring-weight">' + _wiringEscAttr(weight) + "</span>"
      : "") +
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
  });
  if (_wiringEvents.length > WIRING_BUF_CAP) {
    _wiringEvents.length = WIRING_BUF_CAP;
  }
  renderWiringFeed();
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
  _wiringEvents = [];
  _wiringMaxSeq = 0;
  renderWiringFeed();
}

// Single-flight wiring SSE — same discipline as N.Core.connectSSE:
// exactly one live connection plus at most one pending retry timer.
function connectWiring() {
  if (N.Core._wiringTimer) {
    clearTimeout(N.Core._wiringTimer);
    N.Core._wiringTimer = null;
  }
  if (N.Core._wiringSSE) {
    try {
      var old = N.Core._wiringSSE;
      if (old._wiringHandler) {
        old.removeEventListener("wiring", old._wiringHandler);
      }
      old.onerror = null;
      old.close();
    } catch (e) {
      console.warn("[wiring] close failed:", e.message);
    }
    N.Core._wiringSSE = null;
  }
  if (!_wiringShouldRun()) {
    _updateLiveDot();
    return;
  }
  ensureWiringFeed();
  N.Core._wiringBackoff = N.Core._wiringBackoff || 5000;
  var es = new EventSource(WIRING_URL);
  es._wiringHandler = function (e) {
    handleWiringMessage(e.data);
  };
  es.addEventListener("wiring", es._wiringHandler);
  es.onerror = function () {
    try { es.close(); } catch (_) {}
    if (N.Core._wiringSSE === es) N.Core._wiringSSE = null;
    _updateLiveDot();
    if (!_wiringShouldRun()) return;
    var backoff = N.Core._wiringBackoff || 5000;
    N.Core._wiringBackoff = Math.min(backoff * 2, 60000);
    if (N.Core._wiringTimer) clearTimeout(N.Core._wiringTimer);
    N.Core._wiringTimer = setTimeout(function () {
      N.Core._wiringTimer = null;
      connectWiring();
    }, backoff);
  };
  N.Core._wiringSSE = es;
  _updateLiveDot();
}

function disconnectWiring() {
  if (N.Core._wiringTimer) {
    clearTimeout(N.Core._wiringTimer);
    N.Core._wiringTimer = null;
  }
  if (N.Core._wiringSSE) {
    try {
      var es = N.Core._wiringSSE;
      if (es._wiringHandler) {
        es.removeEventListener("wiring", es._wiringHandler);
      }
      es.close();
    } catch (_) {}
    N.Core._wiringSSE = null;
  }
  _updateLiveDot();
}

// Panel hidden ⇒ cut the stream; reshown ⇒ reconnect (single-flight).
function setWiringVisible(open) {
  _wiringVisible = !!open;
  if (_wiringVisible) connectWiring();
  else disconnectWiring();
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
ensureWiringFeed();
ensureFireLimitSetting();
renderWiringFeed();

// ------------------------------------------------------------------
// Expose on N.Chat.memoryPanel
// ------------------------------------------------------------------
Object.assign(N.Chat.memoryPanel, {
  update: updateMemoryPanel,
  updateReflection: updateReflectionPanel,
  sessionSummarized: showSessionSummarized,
  contextCompressed: showContextCompressed,
  deleteCard: deleteMemCard,
  completeGoal: completeGoal,
  getFireLimit: getFireLimit,
  setFireLimit: setFireLimit,
  pushWiringEvent: pushWiringEvent,
  clearWiring: clearWiring,
  renderWiringFeed: renderWiringFeed,
  connectWiring: connectWiring,
  disconnectWiring: disconnectWiring,
  setWiringVisible: setWiringVisible,
});

})(window.Nous);
