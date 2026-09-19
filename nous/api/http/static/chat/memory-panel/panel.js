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
      if (btn.closest("#panel-detail-overlay")) N.Chat.memoryPanel.closePanelDetail();
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
    if (card) N.Chat.memoryPanel.openPanelDetail(card);
  });
  document.addEventListener("keydown", function (e) {
    if (e.key !== "Enter" && e.key !== " ") return;
    var card = e.target && e.target.closest
      ? e.target.closest('[data-panel-kind][role="button"]') : null;
    if (!card || e.target.closest("[data-mem-action],[data-action]")) return;
    e.preventDefault();
    N.Chat.memoryPanel.openPanelDetail(card);
  });
}

// ------------------------------------------------------------------
// Expose on N.Chat.memoryPanel (chunk 1/5 — panel core)
// ------------------------------------------------------------------
Object.assign(N.Chat.memoryPanel, {
  update: updateMemoryPanel,
  updateReflection: updateReflectionPanel,
  sessionSummarized: showSessionSummarized,
  contextCompressed: showContextCompressed,
  deleteCard: deleteMemCard,
  completeGoal: completeGoal,
});
})(window.Nous);
