/* =================================================================
   CHAT MEMORY PANEL — Memory panel CRUD, reflection, session UI
   Extracted from chat.js (Phase 3, Batch 2)
   ================================================================= */
;(function(N) {
var C = N.Core;
var api = C.api, esc = C.esc, toast = C.toast, safeSetHTML = C.safeSetHTML;
var showConfirm = C.showConfirm, showAlert = C.showAlert;
var truncate = C.truncate, relativeTime = C.relativeTime, fmtDate = C.fmtDate, fmtDateTime = C.fmtDateTime;
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
              '<div class="memory-item-card" data-panel-kind="memory" role="button" tabindex="0" title="' + esc(meta) + '" data-key="' +
              esc(key) +
              '" data-content="' +
              esc(_contentStr) +
              '" data-importance="' +
              (m.importance || 0.5) +
              '" data-tags="' +
              esc((m.tags || []).join(",")) +
              '">' +
              content +
              (extra
                ? '<div class="mem-score mem-score-extra">' +
                  extra +
                  "</div>"
                : "") +
              '<div class="mem-actions"><button type="button" class="mem-action-btn del" data-mem-action="delete" data-mem-key="' +
              esc(key) +
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
              '<div class="memory-item-card" data-panel-kind="memory" role="button" tabindex="0" data-key="' +
              esc(key) +
              '" data-content="' +
              esc(_contentStr) +
              '" data-importance="' +
              (m.importance || 0.5) +
              '" data-tags="' +
              esc((m.tags || []).join(",")) +
              '">' +
              content +
              (extra
                ? '<div class="mem-score mem-score-extra">' +
                  extra +
                  "</div>"
                : "") +
              '<div class="mem-actions"><button type="button" class="mem-action-btn del" data-mem-action="delete" data-mem-key="' +
              esc(key) +
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
              '<div class="memory-item-card" data-panel-kind="goal" role="button" tabindex="0" data-key="' +
              esc(key) +
              '" data-content="' +
              esc(g.content || "") +
              '" data-importance="' +
              (g.importance || 0.75) +
              '" data-tags="' +
              esc((g.tags || []).join(",")) +
              '">' +
              '<i data-lucide="target"></i> ' +
              actionBadge +
              esc((g.content || "").substring(0, 80)) +
              '<div class="mem-actions"><button type="button" class="mem-action-btn done" data-mem-action="complete" data-mem-key="' +
              esc(key) +
              '" data-mem-content="' +
              esc((g.content || "").substring(0, 50)) +
              '">完了</button><button type="button" class="mem-action-btn del" data-mem-action="delete" data-mem-key="' +
              esc(key) +
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
              '<div class="memory-item-card" data-panel-kind="promise" role="button" tabindex="0" data-key="' +
              esc(key) +
              '" data-content="' +
              esc(g.content || "") +
              '" data-importance="' +
              (g.importance || 0.8) +
              '" data-tags="' +
              esc((g.tags || []).join(",")) +
              '">' +
              '<i data-lucide="handshake"></i> ' +
              actionBadge +
              esc((g.content || "").substring(0, 80)) +
              '<div class="mem-actions"><button type="button" class="mem-action-btn del" data-mem-action="delete" data-mem-key="' +
              esc(key) +
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
  // Insights arrive as objects {content, key, created_at} (chat_management
  // _do_get_commitments); legacy string format still supported. Objects
  // must NOT hit esc() raw — String(obj) renders "[object Object]".
  safeSetHTML(list, insights
    .map((s) => {
      var o = (s && typeof s === "object")
        ? s : { content: String(s), key: "", created_at: null };
      return (
        '<div class="reflection-insight" data-panel-kind="reflection" role="button" tabindex="0"' +
        ' data-key="' + esc(o.key || "") + '"' +
        ' data-content="' + esc(o.content || "") + '"' +
        (o.created_at ? ' data-created="' + esc(o.created_at) + '"' : "") +
        ">" + esc(o.content || "") + "</div>"
      );
    })
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
// Row cards carry data-panel-kind="memory|goal|promise|reflection"
// and open the detail modals on click / Enter / Space.
// ------------------------------------------------------------------
if (typeof document !== "undefined" && !N.Chat.memoryPanel._delegated) {
  N.Chat.memoryPanel._delegated = true;
  document.addEventListener("click", function (e) {
    var btn = e.target && e.target.closest ? e.target.closest("[data-mem-action]") : null;
    if (btn) {
      e.stopPropagation();
      // Action fired inside the panel detail modal — close it first;
      // deleteCard/completeGoal refresh the panel via loadCommitments.
      if (btn.closest("#panel-detail-overlay")) closePanelDetail();
      var action = btn.getAttribute("data-mem-action");
      var key = btn.getAttribute("data-mem-key");
      if (action === "delete" && key) {
        if (typeof N.Chat.memoryPanel.deleteCard === "function") N.Chat.memoryPanel.deleteCard(key);
      } else if (action === "complete" && key) {
        var content = btn.getAttribute("data-mem-content") || "";
        if (typeof N.Chat.memoryPanel.completeGoal === "function") N.Chat.memoryPanel.completeGoal(key, content);
      }
      return;
    }
    var card = e.target && e.target.closest ? e.target.closest("[data-panel-kind]") : null;
    if (card) openPanelDetail(card);
  });
  document.addEventListener("keydown", function (e) {
    if (e.key !== "Enter" && e.key !== " ") return;
    var card = e.target && e.target.closest
      ? e.target.closest('[data-panel-kind][role="button"]') : null;
    if (!card || e.target.closest("[data-mem-action],[data-action]")) return;
    e.preventDefault();
    openPanelDetail(card);
  });
}

// ------------------------------------------------------------------
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
  monologue: "独り言",
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
    (mainKey
      ? // Row action: open the memory itself in the unified mem modal
        // (the edge detail modal stays on row click).
        '<button type="button" class="wiring-open-memory" data-action="wiring-open-memory"' +
        ' data-wiring-key="' + esc(mainKey) + '" title="記憶の詳細を開く"' +
        ' aria-label="記憶 ' + esc(mainKey) + ' の詳細を開く">&#9656;</button>'
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
  _wiringEvents = [];
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

// Wiring SSE rides the shared core stream manager (core/sse.js):
// single-flight, backoff 5000→60s cap and handler detach live there.
// url() re-evaluates the gate + persona on every (re)connect.
function connectWiring() {
  _clearWiringFlush();
  if (!_wiringShouldRun()) {
    N.Core.disconnectStream("wiring");
    _updateLiveDot();
    return;
  }
  var persona = _wiringPersona || _currentPersona();
  _wiringPersona = persona || null;
  ensureWiringFeed();
  N.Core.connectStream("wiring", {
    url: function () {
      return _wiringShouldRun() && _wiringPersona
        ? _wiringURL(_wiringPersona)
        : null;
    },
    handlers: {
      wiring: function (e) {
        handleWiringMessage(e.data);
      },
      // Server greets every connect with `connected`, then replays the
      // buffer. Hold paints for one window, then paint once.
      connected: function () {
        _beginWiringFlush();
      },
    },
    // Main-stream manners: a healthy open resets the backoff.
    onOpen: function () {
      _updateLiveDot();
    },
    onError: function () {
      _updateLiveDot();
      return _wiringShouldRun();
    },
  });
  _updateLiveDot();
}

function disconnectWiring() {
  N.Core.disconnectStream("wiring");
  _clearWiringFlush();
  _updateLiveDot();
}

// Persona switch: drop the old feed and rescope the stream. Wired into
// the main SSE connect (base.js persona-select init + change both funnel
// through N.Core.connectSSE), so no other hook point is needed.
function switchWiringPersona(persona) {
  if (!persona) persona = _currentPersona();
  if (persona && persona === _wiringPersona && N.Core.streamSocket("wiring")) return;
  _wiringPersona = persona || null;
  clearWiring();
  if (_wiringVisible) connectWiring();
  else disconnectWiring();
}

// Panel hidden ⇒ cut the stream; reshown ⇒ reconnect (single-flight).
function setWiringVisible(open) {
  _wiringVisible = !!open;
  if (_wiringVisible) connectWiring();
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
ensureWiringFeed();
ensureFireLimitSetting();
renderWiringFeed();

// ------------------------------------------------------------------
// Fire detail modal — reuses the .ov-modal system (sanitizer-safe:
// class-based markup + data-fill bars via memoryCard.applyDataStyles).
// Non-blocking viewer: focus + Escape + overlay click + focus restore.
// ------------------------------------------------------------------
var _wiringDetailOpener = null;

function _wiringFindEvent(key) {
  for (var i = 0; i < _wiringEvents.length; i++) {
    if (_wiringEvents[i].source === key || _wiringEvents[i].target === key) {
      return _wiringEvents[i];
    }
  }
  return null;
}

function _wiringDetailHTML(key, mem, ev, failed) {
  var h = '<div class="ov-modal wide">';
  h += '<div class="wiring-detail-head">';
  if (ev) {
    h += '<span class="wiring-kind-badge">' +
      esc(WIRING_KINDS[ev.kind] || String(ev.kind)) + "</span>";
    var w = Number(ev.weight);
    if (isFinite(w)) {
      h += '<span class="mem-bar-pct">weight ' + esc(w.toFixed(2)) + "</span>";
    }
  }
  h += '<button type="button" class="mem-modal-close" data-action="wiring-close" aria-label="閉じる"><i data-lucide="x"></i></button>';
  h += "</div>";
  h += '<div class="wiring-detail-content">';
  if (mem && mem.content) {
    h += '<div class="wiring-detail-text">' + esc(_wiringSummary(mem)) + "</div>";
  } else if (failed) {
    h += '<div class="memory-empty">記憶の詳細を取得できませんでした</div>';
  } else {
    h += '<div class="memory-empty">読み込み中…</div>';
  }
  h += "</div>";
  if (mem) {
    h += '<div class="mem-modal-row"><span class="mem-modal-key">種別</span><span class="badge badge-purple">' +
      esc(mem.kind || "memory") + "</span></div>";
    h += N.Components.memoryCard.renderImportanceBars(mem.importance);
    var tags = mem.tags || [];
    if (tags.length) {
      h += '<div class="mem-modal-row"><span class="mem-modal-key">Tags</span><span class="wiring-detail-tags">' +
        tags.map(function (t) {
          return N.Features.Memories.tagChipHtml(t);
        }).join("") + "</span></div>";
    }
    var rel = mem.related_keys || [];
    if (rel.length) {
      h += '<div class="mem-modal-row"><span class="mem-modal-key">関連</span><span class="wiring-detail-tags">' +
        rel.map(function (rk) {
          return '<span class="wiring-detail-chip" title="' + esc(rk) + '">' +
            esc(_wiringKeyShort(rk)) + "</span>";
        }).join("") + "</span></div>";
    }
    if (mem.created_at) {
      h += '<div class="mem-modal-row"><span class="mem-modal-key">Created</span><span>' +
        esc(fmtDateTime(mem.created_at)) + "</span></div>";
    }
    if (mem.updated_at && mem.updated_at !== mem.created_at) {
      h += '<div class="mem-modal-row"><span class="mem-modal-key">Updated</span><span>' +
        esc(fmtDateTime(mem.updated_at)) + "</span></div>";
    }
  }
  if (ev && (ev.source || ev.target)) {
    h += '<div class="mem-modal-row"><span class="mem-modal-key">Edge</span><span class="mem-key-mono wiring-edge-detail">' +
      esc(ev.source + " → " + ev.target) + "</span></div>";
  }
  h += "</div>";
  return h;
}

function _wiringPaintDetail(overlay, key, ev, mem, failed) {
  safeSetHTML(overlay, _wiringDetailHTML(key, mem, ev, failed));
  _wiringApplyFills(overlay);
  // Close button closes via delegation (data-action="wiring-close").
  if (typeof N.Core.refreshIcons === "function") N.Core.refreshIcons();
}

function openWiringDetail(key) {
  if (!key) return;
  var overlay = document.getElementById("wiring-detail-overlay");
  if (!overlay) {
    overlay = document.createElement("div");
    overlay.id = "wiring-detail-overlay";
    overlay.className = "ov-modal-overlay";
    overlay.setAttribute("role", "dialog");
    overlay.setAttribute("aria-modal", "true");
    overlay.setAttribute("aria-label", "発火した記憶の詳細");
    document.body.appendChild(overlay);
    overlay.addEventListener("click", function (e) {
      if (e.target === overlay) closeWiringDetail();
    });
  }
  var ev = _wiringFindEvent(key);
  _wiringDetailOpener = document.activeElement;
  _wiringPaintDetail(overlay, key, ev, _wiringMemCache[key] || null, false);
  overlay.style.display = "flex";
  var closeBtn = overlay.querySelector("[data-wiring-close]");
  if (closeBtn) closeBtn.focus();
  if (!_wiringMemCache[key] && !_wiringMemFailed[key]) {
    var repaint = function () {
      var ov = document.getElementById("wiring-detail-overlay");
      if (ov && ov.style.display !== "none") {
        _wiringPaintDetail(ov, key, _wiringFindEvent(key), _wiringMemCache[key] || null, true);
      }
    };
    if (_wiringMemPending[key]) _wiringMemPending[key].then(repaint);
    else _wiringEnsureMemories([{ source: key, target: "" }], repaint);
  }
}

function closeWiringDetail() {
  var overlay = document.getElementById("wiring-detail-overlay");
  if (overlay) overlay.style.display = "none";
  if (_wiringDetailOpener && typeof _wiringDetailOpener.focus === "function") {
    try { _wiringDetailOpener.focus(); } catch (_) {}
  }
  _wiringDetailOpener = null;
}

// CSP delegation moved to core/delegation.js:
//   click  [data-wiring-open]        → openWiringDetail (edge modal)
//   click  [data-action=wiring-open-memory] → N.Components.memModal.open
//   click  [data-action=wiring-close] → closeWiringDetail
//   keydown Escape (overlay open)    → closeWiringDetail
//   keydown Enter/Space on rows      → openWiringDetail

// ------------------------------------------------------------------
// Panel detail modal — goal / promise detail.
// Reuses the mem-modal vocabulary (.mem-modal-overlay / .mem-modal /
// mem-modal-row / ov-modal-actions) — zero new CSS. Goal/promise rows
// get 完了/削除 actions routed through the existing [data-mem-action]
// delegation (completeGoal → goal_manage achieve; deleteCard →
// DELETE /api/memories — promises are goals tagged goal/active/
// interpersonal, so both paths apply unchanged). Retrieved/saved/
// reflection rows go through the unified N.Components.memModal:
// complete key → open(key) (fresh fetch), partial data →
// openMemory(partial). Reflections carry full memory keys, so they
// open the rich memory modal, not this one.
// Non-blocking: focus + Escape + backdrop click + focus restore.
// ------------------------------------------------------------------
var _panelDetailOpener = null;
var PANEL_KIND_LABELS = { goal: "目標", promise: "約束" };

function _panelTagsHtml(tags) {
  return (tags || []).map(function (t) {
    var F = N.Features && N.Features.Memories;
    return F && typeof F.tagChipHtml === "function"
      ? F.tagChipHtml(t) : esc(t);
  }).join(" ");
}

function _panelAttrs(card) {
  return {
    key: card.getAttribute("data-key") || "",
    content: card.getAttribute("data-content") || "",
    importance: parseFloat(card.getAttribute("data-importance")),
    tags: (card.getAttribute("data-tags") || "").split(",").filter(Boolean),
    created_at: card.getAttribute("data-created") || null,
  };
}

function _panelDetailHTML(kind, item) {
  var h = '<div class="mem-modal">';
  h += '<div class="mem-modal-header"><div>';
  h += '<div class="mem-modal-kicker">' + esc(PANEL_KIND_LABELS[kind] || kind) + "</div>";
  if (item.key) {
    h += '<div class="mem-key-row"><span class="mem-key-mono">' + esc(item.key) + "</span></div>";
  }
  h += "</div>";
  h += '<button type="button" class="mem-modal-close" data-panel-detail-close aria-label="閉じる"><i data-lucide="x"></i></button>';
  h += "</div>";
  h += '<div class="mem-modal-body">' + esc(item.content || "") + "</div>";
  if (item.tags && item.tags.length) {
    h += '<div class="mem-modal-row"><span class="mem-modal-key">Tags</span><span>' +
      _panelTagsHtml(item.tags) + "</span></div>";
  }
  if (item.created_at) {
    h += '<div class="mem-modal-row"><span class="mem-modal-key">Created</span><span>' +
      esc(fmtDateTime(item.created_at)) + "</span></div>";
  }
  if (kind === "goal" || kind === "promise") {
    h += '<div class="ov-modal-actions">';
    h += '<button type="button" class="glass-btn glass-btn-success" data-mem-action="complete" data-mem-key="' +
      esc(item.key) + '" data-mem-content="' + esc((item.content || "").substring(0, 50)) + '">完了</button>';
    h += '<button type="button" class="glass-btn glass-btn-danger" data-mem-action="delete" data-mem-key="' +
      esc(item.key) + '">削除</button>';
    h += "</div>";
  }
  h += "</div>";
  return h;
}

function _panelDetailKeyHandler(e) {
  if (e.key === "Escape") closePanelDetail();
}

function openPanelDetail(card) {
  if (!card || !card.getAttribute) return;
  var kind = card.getAttribute("data-panel-kind");
  var item = _panelAttrs(card);
  // Reflections are memories (they carry a full memory key), so they go
  // through the unified memModal like memory rows — the sparse panel
  // modal is only for goal/promise, which are not memories.
  if (!kind || kind === "memory" || kind === "reflection") {
    if (item.key) N.Components.memModal.open(item.key);
    else N.Components.memModal.openMemory({
      content: item.content,
      importance: isNaN(item.importance) ? 0.5 : item.importance,
      tags: item.tags,
    });
    return;
  }
  var overlay = document.getElementById("panel-detail-overlay");
  if (!overlay) {
    overlay = document.createElement("div");
    overlay.id = "panel-detail-overlay";
    overlay.className = "mem-modal-overlay";
    overlay.setAttribute("role", "dialog");
    overlay.setAttribute("aria-modal", "true");
    document.body.appendChild(overlay);
    overlay.addEventListener("click", function (e) {
      if (e.target === overlay) closePanelDetail();
    });
  }
  overlay.setAttribute("aria-label", PANEL_KIND_LABELS[kind] || "詳細");
  _panelDetailOpener = document.activeElement;
  safeSetHTML(overlay, _panelDetailHTML(kind, item));
  overlay.classList.add("show");
  document.removeEventListener("keydown", _panelDetailKeyHandler);
  document.addEventListener("keydown", _panelDetailKeyHandler);
  var closeBtn = overlay.querySelector("[data-panel-detail-close]");
  if (closeBtn) {
    closeBtn.addEventListener("click", function () { closePanelDetail(); });
    closeBtn.focus();
  }
  if (typeof N.Core.refreshIcons === "function") N.Core.refreshIcons();
}

function closePanelDetail() {
  var overlay = document.getElementById("panel-detail-overlay");
  if (!overlay || !overlay.classList.contains("show")) return;
  overlay.classList.remove("show");
  document.removeEventListener("keydown", _panelDetailKeyHandler);
  if (_panelDetailOpener && typeof _panelDetailOpener.focus === "function") {
    try { _panelDetailOpener.focus(); } catch (_) {}
  }
  _panelDetailOpener = null;
}

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
  switchWiringPersona: switchWiringPersona,
  setWiringVisible: setWiringVisible,
  openWiringDetail: openWiringDetail,
  closeWiringDetail: closeWiringDetail,
  openPanelDetail: openPanelDetail,
  closePanelDetail: closePanelDetail,
});

})(window.Nous);
