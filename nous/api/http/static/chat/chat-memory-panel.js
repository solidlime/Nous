/* =================================================================
   CHAT MEMORY PANEL — Memory panel CRUD, reflection, session UI
   Extracted from chat.js (Phase 3, Batch 2)
   ================================================================= */
;(function(N) {
var C = N.Core;
var api = C.api, esc = C.esc, toast = C.toast;
var showConfirm = C.showConfirm, showAlert = C.showAlert;
var truncate = C.truncate, relativeTime = C.relativeTime, fmtDate = C.fmtDate;
"use strict";
var S = window.S;

// ------------------------------------------------------------------
// Memory panel update (retrieved / saved / goals)
// ------------------------------------------------------------------
function updateMemoryPanel(retrieved, saved, goals) {
  const escAttr = (s) =>
    String(s)
      .replace(/&/g, "&amp;")
      .replace(/"/g, "&quot;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;");
  if (retrieved !== undefined) {
    const retrievedList = document.getElementById("memory-retrieved-list");
    if (retrievedList) {
      if (!retrieved || retrieved.length === 0) {
        retrievedList.innerHTML = '<div class="memory-empty">なし</div>';
      } else {
        retrievedList.innerHTML = retrieved
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
            const emotionBadges = renderEmotionBadges(
              m.emotion,
              m.emotion_intensity,
            );
            const bodyCompact = renderBodyStateCompact(m.body_state);
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
              '" onclick="openMemEdit(this)">' +
              (meta ? '<div class="mem-score">' + esc(meta) + "</div>" : "") +
              content +
              (extra
                ? '<div class="mem-score" style="font-size:0.7rem;margin-top:3px">' +
                  extra +
                  "</div>"
                : "") +
              '<div class="mem-actions"><button class="mem-action-btn del" onclick="event.stopPropagation();deleteMemCard(\'' +
              escAttr(key) +
              "')\">削除</button></div>" +
              "</div>"
            );
          })
          .join("");
      }
    }
  }
  if (saved !== undefined) {
    const savedList = document.getElementById("memory-saved-list");
    if (savedList) {
      if (!saved || saved.length === 0) {
        savedList.innerHTML = '<div class="memory-empty">なし</div>';
      } else {
        savedList.innerHTML = saved
          .map((m) => {
            var _raw = typeof m.content === "object" && m.content !== null ? JSON.stringify(m.content) : String(m.content || "");
            const content = esc(_raw.substring(0, 80));
            const tags = m.tags ? m.tags.join(", ") : "";
            const key = m.key || "";
            const emotionBadges = renderEmotionBadges(
              m.emotion,
              m.emotion_intensity,
            );
            const bodyCompact = renderBodyStateCompact(m.body_state);
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
              '" onclick="openMemEdit(this)">' +
              content +
              (tags ? '<div class="mem-score">' + esc(tags) + "</div>" : "") +
              (extra
                ? '<div class="mem-score" style="font-size:0.7rem;margin-top:3px">' +
                  extra +
                  "</div>"
                : "") +
              '<div class="mem-actions"><button class="mem-action-btn del" onclick="event.stopPropagation();deleteMemCard(\'' +
              escAttr(key) +
              "')\">削除</button></div>" +
              "</div>"
            );
          })
          .join("");
      }
    }
  }
  if (goals !== undefined) {
    const goalsList = document.getElementById("memory-goals-list");
    if (goalsList) {
      if (!goals || goals.length === 0) {
        goalsList.innerHTML = '<div class="memory-empty">なし</div>';
      } else {
        goalsList.innerHTML = goals
          .map((g) => {
            const key = g.key || "";
            return (
              '<div class="memory-item-card" data-key="' +
              escAttr(key) +
              '" data-content="' +
              escAttr(g.content || "") +
              '" data-importance="' +
              (g.importance || 0.75) +
              '" data-tags="' +
              escAttr((g.tags || []).join(",")) +
              '" onclick="openMemEdit(this)">' +
              '<i data-lucide="target"></i> ' +
              esc((g.content || "").substring(0, 80)) +
              '<div class="mem-actions"><button class="mem-action-btn done" onclick="event.stopPropagation();completeGoal(\'' +
              escAttr(key) +
              "','" +
              escAttr((g.content || "").substring(0, 50)) +
              '\')">完了</button><button class="mem-action-btn del" onclick="event.stopPropagation();deleteMemCard(\'' +
              escAttr(key) +
              "')\">削除</button></div>" +
              "</div>"
            );
          })
          .join("");
      }
    }
  }
}

// ------------------------------------------------------------------
// Reflection panel
// ------------------------------------------------------------------
function showReflectionStart() {
  const header = document.getElementById("reflection-header");
  if (header) {
    header.innerHTML =
      '<i data-lucide="sparkles"></i> リフレクション (実行中...)';
    if (typeof lucide !== "undefined") lucide.createIcons();
  }
  const list = document.getElementById("memory-reflection-list");
  if (list)
    list.innerHTML =
      '<div class="memory-empty" style="color:var(--accent-purple);">分析中...</div>';
}

function updateReflectionPanel(insights) {
  const header = document.getElementById("reflection-header");
  if (header) {
    header.innerHTML = '<i data-lucide="sparkles"></i> リフレクション';
    if (typeof lucide !== "undefined") lucide.createIcons();
  }
  const list = document.getElementById("memory-reflection-list");
  if (!list) return;
  if (!insights || insights.length === 0) {
    list.innerHTML = '<div class="memory-empty">洞察なし</div>';
    return;
  }
  list.innerHTML = insights
    .map((s) => '<div class="reflection-insight">' + esc(s) + "</div>")
    .join("");
}

function showSessionSummarized(summary) {
  const statusEl = document.getElementById("chat-status");
  if (statusEl) {
    statusEl.innerHTML =
      '<i data-lucide="edit-3"></i> セッションを要約しました';
    setTimeout(() => {
      if (statusEl) statusEl.textContent = "";
    }, 3000);
  }
}

function showContextCompressed(evt) {
  const beforePct = Math.round((evt.before_tokens / evt.budget) * 100);
  const afterPct = Math.round((evt.after_tokens / evt.budget) * 100);
  const savings = evt.before_tokens - evt.after_tokens;
  toast(
    "🧠 圧縮: " +
      evt.before_tokens +
      "→" +
      evt.after_tokens +
      " tokens (" +
      beforePct +
      "%→" +
      afterPct +
      "% 予算比) " +
      ((-savings / evt.before_tokens) * 100).toFixed(0) +
      "%削減",
    "info",
  );
}

// ------------------------------------------------------------------
// Memory CRUD operations
// ------------------------------------------------------------------
let _memEditKey = null;

function openMemEdit(card) {
  _memEditKey = card.dataset.key;
  document.getElementById("mem-edit-content").value =
    card.dataset.content || "";
  document.getElementById("mem-edit-importance").value =
    card.dataset.importance || "0.5";
  document.getElementById("mem-edit-tags").value = card.dataset.tags || "";
  document.getElementById("mem-edit-overlay").classList.add("show");
}

function closeMemEdit() {
  document.getElementById("mem-edit-overlay").classList.remove("show");
  _memEditKey = null;
}

async function saveMemEdit() {
  if (!_memEditKey || !S.persona) return;
  const content = document.getElementById("mem-edit-content").value.trim();
  const importance =
    parseFloat(document.getElementById("mem-edit-importance").value) || 0.5;
  const tagsStr = document.getElementById("mem-edit-tags").value.trim();
  const tags = tagsStr
    ? tagsStr
        .split(",")
        .map((t) => t.trim())
        .filter(Boolean)
    : [];
  if (!content) {
    toast("内容を入力してください", "error");
    return;
  }
  try {
    await api(
      "/api/memories/" +
        encodeURIComponent(S.persona) +
        "/" +
        encodeURIComponent(_memEditKey),
      {
        method: "PUT",
        body: JSON.stringify({ content, importance, tags }),
      },
    );
    closeMemEdit();
    toast("メモリを更新しました", "success");
    loadChatCommitments(); // refresh panels
  } catch (e) {
    toast("更新失敗: " + e.message, "error");
  }
}

async function deleteMemCard(key) {
  const k = key || _memEditKey;
  if (!k || !S.persona) return;
  showConfirm("このメモリを削除しますか？", async function () {
    try {
      await api(
        "/api/memories/" +
          encodeURIComponent(S.persona) +
          "/" +
          encodeURIComponent(k),
        {
          method: "DELETE",
        },
      );
      closeMemEdit();
      toast("メモリを削除しました", "success");
      loadChatCommitments(); // refresh panels
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
      loadChatCommitments();
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
  showReflection: showReflectionStart,
  updateReflection: updateReflectionPanel,
};

// Expose globals:
window.updateMemoryPanel = updateMemoryPanel;
window.showReflectionStart = showReflectionStart;
window.updateReflectionPanel = updateReflectionPanel;
window.showSessionSummarized = showSessionSummarized;
window.showContextCompressed = showContextCompressed;
window.openMemEdit = openMemEdit;
window.closeMemEdit = closeMemEdit;
window.saveMemEdit = saveMemEdit;
window.deleteMemCard = deleteMemCard;
window.completeGoal = completeGoal;

})(window.Nous);
