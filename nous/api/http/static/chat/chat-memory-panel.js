/* =================================================================
   CHAT MEMORY PANEL — Memory panel CRUD, reflection, session UI
   Extracted from chat.js (Phase 3, Batch 2)
   ================================================================= */
;(function(N) {
var C = N.Core;
var api = C.api, esc = C.esc, toast = C.toast, safeSetHTML = C.safeSetHTML;
var showConfirm = C.showConfirm, showAlert = C.showAlert;
var truncate = C.truncate, relativeTime = C.relativeTime, fmtDate = C.fmtDate;
var renderEmotionBadges = N.Components.memoryCard.renderEmotionBadges;
var renderBodyStateCompact = N.Components.memoryCard.renderBodyStateCompact;
"use strict";
var S = window.S;

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
                ? '<div class="mem-score" style="font-size:0.7rem;margin-top:3px">' +
                  extra +
                  "</div>"
                : "") +
              '<div class="mem-actions"><button class="mem-action-btn del" onclick="event.stopPropagation();N.Chat.memoryPanel.deleteCard(\'' +
              escAttr(key) +
              "')\">削除</button></div>" +
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
                ? '<div class="mem-score" style="font-size:0.7rem;margin-top:3px">' +
                  extra +
                  "</div>"
                : "") +
              '<div class="mem-actions"><button class="mem-action-btn del" onclick="event.stopPropagation();N.Chat.memoryPanel.deleteCard(\'' +
              escAttr(key) +
              "')\">削除</button></div>" +
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
              '<div class="mem-actions"><button class="mem-action-btn done" onclick="event.stopPropagation();N.Chat.memoryPanel.completeGoal(\'' +
              escAttr(key) +
              "','" +
              escAttr((g.content || "").substring(0, 50)) +
              '\')">完了</button><button class="mem-action-btn del" onclick="event.stopPropagation();N.Chat.memoryPanel.deleteCard(\'' +
              escAttr(key) +
              "')\">削除</button></div>" +
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
              '<div class="mem-actions"><button class="mem-action-btn del" onclick="event.stopPropagation();N.Chat.memoryPanel.deleteCard(\'' +
              escAttr(key) +
              "')\">削除</button></div>" +
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
// Expose on N.Chat.memoryPanel
// ------------------------------------------------------------------
N.Chat.memoryPanel = {
  update: updateMemoryPanel,
  updateReflection: updateReflectionPanel,
  sessionSummarized: showSessionSummarized,
  contextCompressed: showContextCompressed,
  deleteCard: deleteMemCard,
  completeGoal: completeGoal,
};

})(window.Nous);
