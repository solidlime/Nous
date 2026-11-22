/* =================================================================
   CHAT HISTORY SESSION — welcome/reset, clear, session id, rollback,
   inline edit, delete + rebuild
   Chunk 2/3 of chat-history.js. Namespace: N.Chat.history.*
   Depends on: history/render.js (N.Chat._history.appendSegments),
   send/render.js (N.Chat.ui.append), chat-tts.js (N.Chat.tts.endSession),
   chat-tts-stream.js (N.Chat.ttsStream.stop), chat-attachments.js.
   ================================================================= */
;(function(N) {
"use strict";
var C = N.Core;
var api = C.api, toast = C.toast, safeSetHTML = C.safeSetHTML;
var showConfirm = C.showConfirm;
var safeMarkdown = N.Chat.markdown && N.Chat.markdown.render;
var S = window.S;

var CHAT = N.Chat.state;

// Stop every TTS source the chat owns — single-shot (tts) and streaming (ttsStream).
// Both modules are optional at call time (load order / test stubs), and a broken
// TTS stub must never abort the history operation that is already committed server-side.
function _stopTts(reason) {
  try { if (N.Chat.tts && N.Chat.tts.endSession) N.Chat.tts.endSession(reason); } catch (e) {}
  try { if (N.Chat.ttsStream && N.Chat.ttsStream.stop) N.Chat.ttsStream.stop(); } catch (e) {}
}

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
                <span class="chat-welcome-cmd">/help</span>
                <span class="chat-welcome-cmd">/search</span>
                <span class="chat-welcome-cmd">/image</span>
                <span class="chat-welcome-cmd">/invoke_skill</span>
            </div>
        </div>`);
  N.Core.refreshIcons();
}

/* #107: attachment clear runs at both exits — the empty-history early
   return (badge-only state) and after a confirmed reset — never before
   confirm, so cancelling keeps staged files (and their File refs) intact. */

// F4 placeholder: CHAT.abortController has no writer yet — this is a
// no-op guard until streaming cancel is wired (#121). Called AFTER the
// confirm so a cancelled reset never kills a live stream.
function _abortActiveStream() {
  if (CHAT.abortController) {
    CHAT.abortController.abort();
    CHAT.abortController = null;
  }
}

async function clearChatHistory() {
  if (CHAT.messages.length === 0) {
    _abortActiveStream();
    _stopTts("clear"); // empty-history path: no confirm dialog, reset is immediate
    if (N.Chat.attachments && N.Chat.attachments.clear) N.Chat.attachments.clear();
    resetToWelcome();
    return;
  }
  const ok = await showConfirm("会話をリセットしますか？現在の会話履歴がすべて削除されます。");
  if (!ok) return; // cancel = no-op: staged files AND audio must survive
  _abortActiveStream();
  _stopTts("clear"); // confirmed path: stop TTS only after the user commits
  if (N.Chat.attachments && N.Chat.attachments.clear) N.Chat.attachments.clear();
  CHAT.messages = [];
  resetToWelcome();
  // Delete server-side session (F3) - AWAITED, not fire-and-forget
  const oldSid = getChatSessionId();
  if (S.persona && oldSid) {
    try {
      const res = await N.Core.api.rawFetch(
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

// Numeric msg-index (DOM position) → UUID resolution, shared by
// rollback/edit/delete. Three outcomes:
//   { ok: true, id }            — resolved to the element's data-msg-id
//   { ok: false, reason: "missing" } — element not in DOM (e.g. after re-render)
//   { ok: false, reason: "pending" } — element exists but data-msg-id is empty
//                                 (response still streaming, id not yet assigned)
function resolveMsgIndex(num) {
  var c = document.getElementById("chat-messages");
  var el = c ? c.querySelector('.chat-msg[data-msg-index="' + num + '"]') : null;
  if (el && el.dataset.msgId) return { ok: true, id: el.dataset.msgId };
  return { ok: false, reason: el ? "pending" : "missing" };
}

// Resolve a numeric index to its UUID, or explain via toast why we cannot
// and return null (caller must return). Keeps the three guard messages in
// one place — "missing" vs "pending" used to collapse into a single
// misleading "応答処理中" toast (#105).
function requireMsgId(num) {
  var r = resolveMsgIndex(num);
  if (r.ok) return r.id;
  if (r.reason === "missing") {
    toast("対象メッセージが見つかりません。一覧を再読み込みしてから操作してください。", "warning");
  } else {
    toast("応答処理中のため操作できません。しばらくお待ちください。", "warning");
  }
  return null;
}

async function rollbackChat(fromId, shouldResend) {
  if (!S.persona) return;
  // Resolve numeric index to UUID, or bail with the precise reason (#105)
  if (typeof fromId === "number") {
    var rid = requireMsgId(fromId);
    if (rid === null) return;
    fromId = rid;
  }
  const sid = getChatSessionId();

  try {
    // TTSキャッシュクリーンアップ: 削除対象のキャッシュURLを収集
    var ttsCacheUrls = [];
    var cc = document.getElementById("chat-messages");
    var allMsgs = cc.querySelectorAll(".chat-msg.assistant");
    // fromId is always a UUID string here — requireMsgId already converted
    // any numeric index before we got here.
    var found = false;
    for (var j = 0; j < allMsgs.length; j++) {
      if (found && allMsgs[j].dataset.ttsCacheUrl) {
        ttsCacheUrls.push(allMsgs[j].dataset.ttsCacheUrl);
      }
      if (allMsgs[j].dataset.msgId === String(fromId)) found = true;
    }

    const body = { from_id: String(fromId), exclusive: !!shouldResend };

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
    _stopTts("rollback");
    // TTSキャッシュ削除
    ttsCacheUrls.forEach(function(url) {
      var filename = url.split("/").pop();
      N.Core.api.rawFetch("/api/tts/" + encodeURIComponent(S.persona) + "/cache/" + encodeURIComponent(filename), { method: "DELETE" }).catch(function() {});
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
  // Resolve numeric index to UUID, or bail with the precise reason (#105)
  if (typeof msgId === "number") {
    var eid = requireMsgId(msgId);
    if (eid === null) return;
    msgId = eid;
  }
  // msgId is always a UUID string here — requireMsgId already converted
  // any numeric index before we got here.
  let msgDiv = document.querySelector('.chat-msg.user[data-msg-id="' + msgId + '"]');
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
        const currentMsgEl = container.querySelector('.chat-msg.user[data-msg-id="' + msgId + '"]');
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
  // Resolve numeric index to UUID, or bail with the precise reason (#105)
  if (typeof msgId === "number") {
    var did = requireMsgId(msgId);
    if (did === null) return;
    msgId = did;
  }

  const container = document.getElementById("chat-messages");
  const allMsgs = container.querySelectorAll(".chat-msg");

  // 後続メッセージ数を計算
  let subsequentCount = 0;
  let found = false;
  for (const msg of allMsgs) {
    if (found) { subsequentCount++; continue; }
    // msgId is always a UUID string here (requireMsgId converted it)
    if (msg.dataset.msgId === msgId) found = true;
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
    // msgId is always a UUID string here (requireMsgId converted it)
    var found2 = false;
    for (var m = 0; m < allMsgs2.length; m++) {
      if (found2 && allMsgs2[m].dataset.ttsCacheUrl) {
        ttsCacheUrls.push(allMsgs2[m].dataset.ttsCacheUrl);
      }
      if (allMsgs2[m].dataset.msgId === String(msgId)) found2 = true;
    }

    const body = { from_id: String(msgId), exclusive: true };

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
    _stopTts("delete");
    // TTSキャッシュ削除
    ttsCacheUrls.forEach(function(url) {
      var filename = url.split("/").pop();
      N.Core.api.rawFetch("/api/tts/" + encodeURIComponent(S.persona) + "/cache/" + encodeURIComponent(filename), { method: "DELETE" }).catch(function() {});
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

    toast("🗑️ メッセージを削除しました", "success");
  } catch (e) {
    toast("削除失敗: " + e.message, "error");
  }
}

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
