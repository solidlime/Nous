/* =================================================================
   CHAT HISTORY SESSION — welcome/reset, clear, session id, rollback,
   inline edit, delete + rebuild
   Chunk 2/3 of chat-history.js. Namespace: N.Chat.history.*
   Depends on: history/render.js (N.Chat._history.appendSegments),
   send/render.js (N.Chat.ui.append), chat-tts.js (_endSession noop
   guard), chat-attachments.js.
   ================================================================= */
;(function(N) {
var C = N.Core;
var api = C.api, esc = C.esc, toast = C.toast, safeSetHTML = C.safeSetHTML;
var showConfirm = C.showConfirm, showAlert = C.showAlert;
var truncate = C.truncate, relativeTime = C.relativeTime, fmtDate = C.fmtDate;
var fmtStamp = C.fmtStamp;
var safeMarkdown = N.Chat.markdown && N.Chat.markdown.render;
var appendChatMessage = N.Chat.ui && N.Chat.ui.append;
"use strict";
var S = window.S;

var CHAT = N.Chat.state;

function resetToWelcome() {
  const container = document.getElementById("chat-messages");
  if (!container) return;
  safeSetHTML(container, `
        <div class="chat-welcome" id="chat-welcome">
            <div class="chat-welcome-icon"><i data-lucide="message-circle"></i></div>
            <p>チャットを開始するには下のテキストボックスにメッセージを入力してください。</p>
            <p class="chat-welcome-hint">APIキーとBase URLを設定してください。<br><a href="#" data-chat-welcome-settings="1" class="chat-welcome-link"><i data-lucide="settings"></i> 設定パネルを開く</a></p>
            <div class="chat-welcome-commands">
                <span class="chat-welcome-cmd">/memory</span>
                <span class="chat-welcome-cmd">/goal</span>
                <span class="chat-welcome-cmd">/help</span>
                <span class="chat-welcome-cmd">/search</span>
                <span class="chat-welcome-cmd">/image</span>
                <span class="chat-welcome-cmd">/invoke_skill</span>
            </div>
        </div>`);
  N.Core.refreshIcons();
}

async function clearChatHistory() {
  // Abort any active stream before clearing
  if (CHAT.abortController) {
    CHAT.abortController.abort();
    CHAT.abortController = null;
  }
  if (typeof _endSession === "function") _endSession("rollback");
  if (CHAT.messages.length === 0) {
    resetToWelcome();
    return;
  }
  const ok = await showConfirm("会話をリセットしますか？現在の会話履歴がすべて削除されます。");
  if (!ok) return;
  CHAT.messages = [];
  CHAT.attachments = [];
  const badge = document.getElementById('chat-attach-badge');
  if (badge) badge.style.display = 'none';
  resetToWelcome();
  // Delete server-side session (F3) - AWAITED, not fire-and-forget
  const oldSid = getChatSessionId();
  if (S.persona && oldSid) {
    try {
      const res = await fetch(
        "/api/chat/" +
          encodeURIComponent(S.persona) +
          "/sessions/" +
          encodeURIComponent(oldSid),
        { method: "DELETE" },
      );
      if (!res.ok) throw new Error(res.statusText);
      CHAT._justReset = true; // prevent restoreChatHistory from re-fetching
    } catch (e) {
      console.warn("[session delete] failed:", e);
      toast("セッション削除失敗: " + e.message, "error");
    }
  }
  document.getElementById("chat-status").textContent = "会話をリセットしました";
  setTimeout(() => {
    document.getElementById("chat-status").textContent = "";
  }, 2000);
}

function getChatSessionId() {
  // Fixed session ID per persona — enables cross-device sync
  return "main";
}

async function rollbackChat(fromId, shouldResend) {
  if (!S.persona) return;
  // Resolve numeric index to UUID (streaming messages may not have msgId yet)
  if (typeof fromId === "number") {
    var c = document.getElementById("chat-messages");
    if (c) {
      var el = c.querySelector('.chat-msg[data-msg-index="' + fromId + '"]');
      if (el && el.dataset.msgId) fromId = el.dataset.msgId;
    }
  }
  // 応答処理中でmsgIdが空文字列のままの場合 → 操作不能
  if (typeof fromId === "number") {
    toast("応答処理中のため操作できません。しばらくお待ちください。", "warning");
    return;
  }
  const sid = getChatSessionId();

  try {
    // TTSキャッシュクリーンアップ: 削除対象のキャッシュURLを収集
    var ttsCacheUrls = [];
    var cc = document.getElementById("chat-messages");
    var allMsgs = cc.querySelectorAll(".chat-msg.assistant");
    if (typeof fromId === "number") {
      for (var i = 0; i < allMsgs.length; i++) {
        var idx = parseInt(allMsgs[i].dataset.msgIndex);
        var exclusive = !!shouldResend;
        if ((exclusive && idx >= fromId) || (!exclusive && idx > fromId)) {
          if (allMsgs[i].dataset.ttsCacheUrl) {
            ttsCacheUrls.push(allMsgs[i].dataset.ttsCacheUrl);
          }
        }
      }
    } else {
      var found = false;
      for (var j = 0; j < allMsgs.length; j++) {
        if (found && allMsgs[j].dataset.ttsCacheUrl) {
          ttsCacheUrls.push(allMsgs[j].dataset.ttsCacheUrl);
        }
        if (allMsgs[j].dataset.msgId === String(fromId)) found = true;
      }
    }

    const body = typeof fromId === "number"
      ? { keep_until: fromId, exclusive: !!shouldResend }
      : { from_id: String(fromId), exclusive: !!shouldResend };

    const result = await api(
      "/api/chat/" +
        encodeURIComponent(S.persona) +
        "/sessions/" +
        encodeURIComponent(sid) +
        "/rollback",
      {
        method: "POST",
        body: JSON.stringify(body),
      },
    );

    // TTS session cleanup before DOM rebuild
    if (typeof _endSession === "function") _endSession("rollback");
    // TTSキャッシュ削除
    ttsCacheUrls.forEach(function(url) {
      var filename = url.split("/").pop();
      fetch("/api/tts/" + encodeURIComponent(S.persona) + "/cache/" + encodeURIComponent(filename), { method: "DELETE" }).catch(function() {});
    });
    // DOM完全再構築: server response の remaining_messages から再描画
    const container = document.getElementById("chat-messages");
    container.textContent = "";
    const remaining = result.remaining_messages || [];
    for (const msg of remaining) {
    if (msg.segments) {
      N.Chat.ui.append(msg.role, "", msg.time, false, msg.id, msg.ts);
      N.Chat._history.appendSegments(msg, container.querySelector(".chat-msg:last-child"));
    } else {
      N.Chat.ui.append(msg.role, msg.content, msg.time, msg.role === "assistant", msg.id, msg.ts);
    }
    }

    // Restore welcome if no messages left
    if (remaining.length === 0) {
      resetToWelcome();
    }

    // 入力欄に最後のユーザーメッセージを設定
    const lastUserText = result.removed_user_text ||
      (function() {
        for (let i = remaining.length - 1; i >= 0; i--) {
          if (remaining[i].role === "user") return remaining[i].content;
        }
        return null;
      })();

    if (lastUserText) {
      const inputEl = document.getElementById("chat-input");
      if (inputEl) {
        inputEl.value = lastUserText;
        inputEl.focus();
        inputEl.dispatchEvent(new Event("input"));
      }

      if (shouldResend) {
        setTimeout(() => {
          N.Chat.send(false);
        }, 100);
      }
    }

    toast("🔄 ロールバックしました", "info");
  } catch (e) {
    toast("ロールバック失敗: " + e.message, "error");
  }
}

// ------------------------------------------------------------------
async function editChatMessage(msgId) {
  if (!S.persona) return;
  // Resolve numeric index to UUID (streaming messages may not have msgId yet)
  if (typeof msgId === "number") {
    var c = document.getElementById("chat-messages");
    if (c) {
      var el = c.querySelector('.chat-msg[data-msg-index="' + msgId + '"]');
      if (el && el.dataset.msgId) msgId = el.dataset.msgId;
    }
  }
  // 応答処理中でmsgIdが空文字列のままの場合 → 操作不能
  if (typeof msgId === "number") {
    toast("応答処理中のため操作できません。しばらくお待ちください。", "warning");
    return;
  }
  let msgDiv;
  if (typeof msgId === "number") {
    msgDiv = document.querySelector('.chat-msg.user[data-msg-index="' + msgId + '"]');
  } else {
    msgDiv = document.querySelector('.chat-msg.user[data-msg-id="' + msgId + '"]');
  }
  if (!msgDiv) return;
  const bubble = msgDiv.querySelector(".chat-bubble");
  if (!bubble) return;

  const originalText = bubble.textContent;

  // Replace bubble with editable textarea
  const textarea = document.createElement("textarea");
  textarea.className = "chat-edit-textarea";
  textarea.value = originalText;
  textarea.style.width = "100%";
  textarea.style.minHeight = "60px";
  textarea.style.boxSizing = "border-box";
  bubble.style.display = "none";
  bubble.parentNode.insertBefore(textarea, bubble.nextSibling);

  // Focus and select all
  textarea.focus();
  textarea.select();

  // Create save/cancel buttons
  const btnBar = document.createElement("div");
  btnBar.className = "chat-edit-btn-bar";
  btnBar.style.cssText =
    "display:flex;gap:8px;margin-top:6px;justify-content:flex-end;";

  const saveBtn = document.createElement("button");
  saveBtn.className = "chat-msg-action-btn";
  safeSetHTML(saveBtn, '<i data-lucide="check"></i> 保存');
  saveBtn.onclick = async () => {
    const newText = textarea.value.trim();
    if (!newText || newText === originalText) {
      cancelEdit();
      return;
    }
    try {
      const sid = getChatSessionId();
      const url =
        "/api/chat/" +
        encodeURIComponent(S.persona) +
        "/sessions/" +
        encodeURIComponent(sid) +
        "/messages/" +
        msgId;
      const result = await api(url, {
        method: "PUT",
        body: JSON.stringify({ content: newText }),
      });
      if (result.status === "ok") {
        safeSetHTML(bubble, typeof safeMarkdown === "function" ? safeMarkdown(newText) : newText);

        // 編集後に後続メッセージがあれば自動再生成
        const container = document.getElementById("chat-messages");
        const currentMsgEl = typeof msgId === "number"
          ? container.querySelector('.chat-msg.user[data-msg-index="' + msgId + '"]')
          : container.querySelector('.chat-msg.user[data-msg-id="' + msgId + '"]');
        const allMsgEls = container.querySelectorAll(".chat-msg");
        const allMsgs = Array.from(allMsgEls);
        const currentIdx = allMsgs.indexOf(currentMsgEl);
        if (currentIdx >= 0 && currentIdx < allMsgs.length - 1) {
          cleanup();
          await rollbackChat(msgId, true);
          return;
        }
        toast("メッセージを更新しました", "success");
      } else {
        toast("更新失敗: " + (result.error || "unknown"), "error");
      }
    } catch (e) {
      toast("更新失敗: " + e.message, "error");
    } finally {
      cleanup();
    }
  };

  const cancelBtn = document.createElement("button");
  cancelBtn.className = "chat-msg-action-btn";
  safeSetHTML(cancelBtn, '<i data-lucide="x"></i> キャンセル');
  cancelBtn.onclick = cancelEdit;

  btnBar.appendChild(saveBtn);
  btnBar.appendChild(cancelBtn);
  textarea.parentNode.insertBefore(btnBar, textarea.nextSibling);

  // Keyboard shortcuts: Enter to save, Escape to cancel
  textarea.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      saveBtn.click();
    } else if (e.key === "Escape") {
      e.preventDefault();
      cancelBtn.click();
    }
  });

  N.Core.refreshIcons();

  function cancelEdit() {
    cleanup();
    toast("編集をキャンセルしました", "info");
  }

  function cleanup() {
    textarea.remove();
    btnBar.remove();
    bubble.style.display = "";
  }
}

// ------------------------------------------------------------------
// Shared renderer for history messages (initial load / load-older)
// prepend=false: DOM リセット後に末尾へ append（初期ロード）
async function deleteChatMessage(msgId) {
  if (!S.persona) return;
  // Resolve numeric index to UUID (streaming messages may not have msgId yet)
  if (typeof msgId === "number") {
    var c = document.getElementById("chat-messages");
    if (c) {
      var el = c.querySelector('.chat-msg[data-msg-index="' + msgId + '"]');
      if (el && el.dataset.msgId) msgId = el.dataset.msgId;
    }
  }
  // 応答処理中でmsgIdが空文字列のままの場合 → 操作不能
  if (typeof msgId === "number") {
    toast("応答処理中のため操作できません。しばらくお待ちください。", "warning");
    return;
  }

  const container = document.getElementById("chat-messages");
  const allMsgs = container.querySelectorAll(".chat-msg");

  // 後続メッセージ数を計算
  let subsequentCount = 0;
  let found = false;
  for (const msg of allMsgs) {
    if (found) { subsequentCount++; continue; }
    if (typeof msgId === "number") {
      if (parseInt(msg.dataset.msgIndex) === msgId) found = true;
    } else {
      if (msg.dataset.msgId === msgId) found = true;
    }
  }

  const confirmed = await showConfirm(
    "このメッセージを削除しますか？以降の " + subsequentCount + " 件のメッセージも削除されます。"
  );
  if (!confirmed) return;

  try {
    // TTSキャッシュクリーンアップ: 削除対象のキャッシュURLを収集
    var ttsCacheUrls = [];
    var container2 = document.getElementById("chat-messages");
    var allMsgs2 = container2.querySelectorAll(".chat-msg.assistant");
    if (typeof msgId === "number") {
      for (var k = 0; k < allMsgs2.length; k++) {
        var idx2 = parseInt(allMsgs2[k].dataset.msgIndex);
        if (idx2 >= msgId) {
          if (allMsgs2[k].dataset.ttsCacheUrl) {
            ttsCacheUrls.push(allMsgs2[k].dataset.ttsCacheUrl);
          }
        }
      }
    } else {
      var found2 = false;
      for (var m = 0; m < allMsgs2.length; m++) {
        if (found2 && allMsgs2[m].dataset.ttsCacheUrl) {
          ttsCacheUrls.push(allMsgs2[m].dataset.ttsCacheUrl);
        }
        if (allMsgs2[m].dataset.msgId === String(msgId)) found2 = true;
      }
    }

    const body = typeof msgId === "number"
      ? { keep_until: msgId, exclusive: true }
      : { from_id: String(msgId), exclusive: true };

    CHAT._justReset = true;
    const result = await api(
      "/api/chat/" +
        encodeURIComponent(S.persona) +
        "/sessions/" +
        encodeURIComponent(getChatSessionId()) +
        "/rollback",
      { method: "POST", body: JSON.stringify(body) }
    );

    // TTS session cleanup before DOM rebuild
    if (typeof _endSession === "function") _endSession("rollback");
    // TTSキャッシュ削除
    ttsCacheUrls.forEach(function(url) {
      var filename = url.split("/").pop();
      fetch("/api/tts/" + encodeURIComponent(S.persona) + "/cache/" + encodeURIComponent(filename), { method: "DELETE" }).catch(function() {});
    });
    // DOM完全再構築
    container.textContent = "";
    const remaining = result.remaining_messages || [];
    for (const msg of remaining) {
    if (msg.segments) {
      N.Chat.ui.append(msg.role, "", msg.time, false, msg.id, msg.ts);
      N.Chat._history.appendSegments(msg, container.querySelector(".chat-msg:last-child"));
    } else {
      N.Chat.ui.append(msg.role, msg.content, msg.time, msg.role === "assistant", msg.id, msg.ts);
    }
    }

    if (remaining.length === 0) {
      resetToWelcome();
    }

    toast("�️ メッセージを削除しました", "success");
  } catch (e) {
    toast("削除失敗: " + e.message, "error");
  }
}

// ------------------------------------------------------------------
// REM monologue bubbles — display-only restore from session events.
// Fetched after each history render; persona switches re-fetch because
// restoreChatHistory wipes the container first. Never touches
// ------------------------------------------------------------------
// Expose on N.Chat (chunk 2/3 — session ops)
// ------------------------------------------------------------------
N.Chat.history = N.Chat.history || {};
N.Chat.history.clear = clearChatHistory;
N.Chat.history.rollback = rollbackChat;
N.Chat.history.edit = editChatMessage;
N.Chat.history.delete = deleteChatMessage;
N.Chat.history.reset = resetToWelcome;
N.Chat.history.getSessionId = getChatSessionId;
})(window.Nous);
