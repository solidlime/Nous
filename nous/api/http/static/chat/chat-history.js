/* =================================================================
   CHAT HISTORY — History restore, clear, rollback, edit, export
   Extracted from chat.js (Phase 3, Batch 2)
   ================================================================= */
;(function(N) {
var C = N.Core;
var api = C.api, esc = C.esc, toast = C.toast;
var showConfirm = C.showConfirm, showAlert = C.showAlert;
var truncate = C.truncate, relativeTime = C.relativeTime, fmtDate = C.fmtDate;
"use strict";
var S = window.S;

var CHAT = N.Chat.state;

// ------------------------------------------------------------------
// Reset to welcome screen
// ------------------------------------------------------------------
function resetToWelcome() {
  const container = document.getElementById("chat-messages");
  container.innerHTML = `
        <div class="chat-welcome" id="chat-welcome">
            <div class="chat-welcome-icon"><i data-lucide="message-circle"></i></div>
            <p>チャットを開始するには下のテキストボックスにメッセージを入力してください。</p>
            <p class="chat-welcome-hint">APIキーとプロバイダーを設定してください。<br><a href="#" onclick="toggleSettingsPanel();return false;" class="chat-welcome-link"><i data-lucide="settings"></i> 設定パネルを開く</a></p>
            <div class="chat-welcome-commands">
                <span class="chat-welcome-cmd">/memory</span>
                <span class="chat-welcome-cmd">/goal</span>
                <span class="chat-welcome-cmd">/help</span>
                <span class="chat-welcome-cmd">/search</span>
                <span class="chat-welcome-cmd">/image</span>
                <span class="chat-welcome-cmd">/invoke_skill</span>
            </div>
        </div>`;
  setTimeout(() => {
    if (typeof lucide !== "undefined") lucide.createIcons();
  }, 50);
}

// ------------------------------------------------------------------
// Clear chat history
// ------------------------------------------------------------------
async function clearChatHistory() {
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

// ------------------------------------------------------------------
// Get chat session ID
// ------------------------------------------------------------------
function getChatSessionId() {
  // Fixed session ID per persona — enables cross-device sync
  return "main";
}

// ------------------------------------------------------------------
// Rollback: undo messages from keep_until onwards, optionally auto-resend
// ------------------------------------------------------------------
async function rollbackChat(keepUntil, shouldResend) {
  if (!S.persona) return;
  const sid = getChatSessionId();

  try {
    const result = await api(
      "/api/chat/" +
        encodeURIComponent(S.persona) +
        "/sessions/" +
        encodeURIComponent(sid) +
        "/rollback",
      {
        method: "POST",
        body: JSON.stringify({ keep_until: keepUntil }),
      },
    );

    // Remove DOM messages from keep_until onwards
    const container = document.getElementById("chat-messages");
    const allMsgs = container.querySelectorAll(".chat-msg");
    for (const msg of allMsgs) {
      if (parseInt(msg.dataset.msgIndex) >= keepUntil) {
        msg.remove();
      }
    }

    // Restore welcome if no messages left
    if (container.querySelectorAll(".chat-msg").length === 0) {
      resetToWelcome();
    }

    if (result.removed_user_text) {
      const inputEl = document.getElementById("chat-input");
      if (inputEl) {
        inputEl.value = result.removed_user_text;
        inputEl.focus();
        inputEl.dispatchEvent(new Event("input"));
      }

      if (shouldResend) {
        // Small delay to let the DOM settle, then auto-send
        setTimeout(() => {
          chatSend(false);
        }, 100);
      }
    }

    if (result.removed_count > 0) {
      toast(
        "🔄 " + result.removed_count + "件のメッセージを元に戻しました",
        "info",
      );
    }
  } catch (e) {
    toast("ロールバック失敗: " + e.message, "error");
  }
}

// ------------------------------------------------------------------
// Inline edit: 編集ボタン用 — textarea.value 代入なし、undo スタック非破壊
// ------------------------------------------------------------------
async function editChatMessage(msgIndex) {
  if (!S.persona) return;
  const msgDiv = document.querySelector(
    '.chat-msg.user[data-msg-index="' + msgIndex + '"]',
  );
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
  saveBtn.innerHTML = '<i data-lucide="check"></i> 保存';
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
        msgIndex;
      const result = await api(url, {
        method: "PUT",
        body: JSON.stringify({ content: newText }),
      });
      if (result.status === "ok") {
        bubble.textContent = newText;

        // Check for subsequent messages → auto-regenerate
        const container = document.getElementById("chat-messages");
        const allMsgs = container.querySelectorAll(".chat-msg");
        if (allMsgs.length > msgIndex + 1) {
          cleanup();
          await rollbackChat(msgIndex, true);
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
  cancelBtn.innerHTML = '<i data-lucide="x"></i> キャンセル';
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

  setTimeout(() => {
    if (typeof lucide !== "undefined") lucide.createIcons();
  }, 50);

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
// Restore chat history from server on page load / persona switch
// ------------------------------------------------------------------
async function restoreChatHistory() {
  if (!S.persona) return;
  if (CHAT._justReset) {
    CHAT._justReset = false;
    return; // リセット直後は履歴を再取得しない
  }
  const sid = getChatSessionId();
  const container = document.getElementById("chat-messages");
  // Show loading skeleton while fetching history (Bug B3 fix: don't reset DOM before fetch)
  const skeletonHtml =
    '<div class="chat-msg assistant"><div class="chat-bubble" style="opacity:0.5"><div class="skeleton skeleton-text" style="width:80%;height:14px;margin-bottom:8px"></div><div class="skeleton skeleton-text" style="width:60%;height:14px;margin-bottom:8px"></div><div class="skeleton skeleton-text" style="width:40%;height:14px"></div></div></div>' +
    '<div class="chat-msg user" style="align-self:flex-end"><div class="chat-bubble" style="opacity:0.5"><div class="skeleton skeleton-text" style="width:70%;height:14px;margin-bottom:8px"></div><div class="skeleton skeleton-text" style="width:50%;height:14px"></div></div></div>';
  const skeletonDiv = document.createElement("div");
  skeletonDiv.id = "chat-history-skeleton";
  skeletonDiv.innerHTML = skeletonHtml;
  container.appendChild(skeletonDiv);
  try {
    const data = await api(
      "/api/chat/" +
        encodeURIComponent(S.persona) +
        "/sessions/" +
        encodeURIComponent(sid),
    );
    // Remove skeleton
    const skel = document.getElementById("chat-history-skeleton");
    if (skel) skel.remove();
    if (!data || !data.messages) {
      console.warn("[restoreChatHistory] unexpected response — data or messages missing:", data);
      S.historyLoadFailed = true;
      return;
    }
    if (data.messages.length === 0) {
      // No history, show welcome
      console.info("[restoreChatHistory] no messages, fresh start");
      CHAT.messages = [];
      resetToWelcome();
      return;
    }
    // display_history_turns 件数分（最新N turns = N*2 messages）に制限
    const displayTurns = parseInt(
      document.getElementById("chat-display-history-turns")?.value || "10",
    );
    const maxMsgs = displayTurns * 2;
    const msgs = data.messages.slice(-maxMsgs);
    // Successful fetch — now safe to reset DOM (Bug B3 fix: only reset after fetch succeeds)
    CHAT.messages = [];
    container.innerHTML = "";
    for (const msg of msgs) {
      const msgContainer = document.getElementById("chat-messages");

      // ── Segments-based rendering (F2: correct interleaving) ──
      if (msg.segments) {
        // F3: inline content_parts rendering for correct interleaving
        appendChatMessage(msg.role, "", msg.time, false);  // creates empty .chat-msg div
        const msgDiv = msgContainer.querySelector(".chat-msg:last-child");
        const toolCallDivs = {}; // id -> div

        for (const seg of msg.segments) {
          if (seg.type === "text") {
            const bubble = document.createElement("div");
            bubble.className = "chat-bubble";
            bubble.innerHTML = safeMarkdown(seg.content);
            bubble.querySelectorAll("img").forEach((img) => {
              img.style.cssText =
                "max-width:100%;border-radius:8px;cursor:pointer;margin:8px 0;";
              img.addEventListener("click", () =>
                openMediaViewer(img.src, "image"),
              );
            });
            const timeDiv = msgDiv.querySelector(".chat-time");
            if (timeDiv) {
              msgDiv.insertBefore(bubble, timeDiv);
            } else {
              msgDiv.appendChild(bubble);
            }
          } else if (seg.type === "tool_call") {
            let inputStr;
            try { inputStr = JSON.stringify(seg.input, null, 2); } catch (e) { inputStr = String(seg.input); }
            const div = document.createElement("div");
            div.className = "chat-tool-call done";
            if (seg.id) div.dataset.toolId = seg.id;
            div.innerHTML =
              '<details><summary><i data-lucide="wrench"></i> <strong>' +
              esc(seg.name) +
              "</strong>" +
              '<span class="chat-tool-status"> <i data-lucide="check"></i> 完了</span></summary>' +
              '<pre class="chat-tool-detail">' +
              esc(inputStr) +
              "</pre></details>";
            if (seg.id) toolCallDivs[seg.id] = div;
            const timeDiv = msgDiv.querySelector(".chat-time");
            if (timeDiv) {
              msgDiv.insertBefore(div, timeDiv);
            } else {
              msgDiv.appendChild(div);
            }
          } else if (seg.type === "tool_result") {
            const toolDiv = seg.id ? toolCallDivs[seg.id] : null;
            if (toolDiv) {
              let resultStr;
              try {
                resultStr = typeof seg.result === "object"
                  ? JSON.stringify(seg.result, null, 2)
                  : String(seg.result);
              } catch (e) { resultStr = String(seg.result); }
              const details = toolDiv.querySelector("details");
              if (details) {
                const resultPre = document.createElement("pre");
                resultPre.className = "chat-tool-detail chat-tool-result-content";
                resultPre.textContent = resultStr;
                details.appendChild(resultPre);
              }
              // 画像生成結果があればレンダリング（履歴復元時）
              if (seg.id && msg.tool_calls) {
                var tc = msg.tool_calls.find(function(t) { return t.id === seg.id; });
                if (tc && tc.result_raw && tc.result_raw.images && tc.result_raw.images.length) {
                  tc.result_raw.images.forEach(function(img) {
                    var card = document.createElement("div");
                    card.className = "chat-image-gen-card";
                    var imgEl = document.createElement("img");
                    try {
                      var binary = atob(img.base64);
                      var bytes = new Uint8Array(binary.length);
                      for (var b = 0; b < binary.length; b++) bytes[b] = binary.charCodeAt(b);
                      var blob = new Blob([bytes], { type: "image/png" });
                      imgEl.src = URL.createObjectURL(blob);
                    } catch (e) {
                      imgEl.src = "data:image/png;base64," + img.base64;
                    }
                    imgEl.alt = img.revised_prompt || "生成画像";
                    imgEl.title = img.revised_prompt || "";
                    imgEl.onerror = function() {
                      imgEl.style.display = "none";
                      var errDiv = document.createElement("div");
                      errDiv.className = "image-gen-error";
                      errDiv.textContent = "⚠️ 画像のデコードに失敗しました";
                      card.insertBefore(errDiv, card.firstChild);
                    };
                    imgEl.onclick = function() {
                      if (typeof openMediaViewer === "function") {
                        openMediaViewer(imgEl.src, "image");
                      } else {
                        window.open(imgEl.src, "_blank");
                      }
                    };
                    var meta = document.createElement("div");
                    meta.className = "image-gen-meta";
                    var rp = img.revised_prompt || "";
                    if (rp) {
                      var promptSpan = document.createElement("span");
                      promptSpan.textContent = rp.length > 80 ? rp.substring(0, 80) + "..." : rp;
                      promptSpan.style.fontStyle = "italic";
                      meta.appendChild(promptSpan);
                    }
                    var sizeSpan = document.createElement("span");
                    sizeSpan.textContent = (tc.result_raw.provider || "") + " · " + (img.size || "");
                    meta.appendChild(sizeSpan);
                    card.appendChild(imgEl);
                    card.appendChild(meta);
                    // tool_call div の後ろに挿入
                    toolDiv.parentNode.insertBefore(card, toolDiv.nextSibling);
                  });
                }
              }
            }
          }
        }
        // Remove empty bubble if appendChatMessage created one with no content
        const emptyBubble = msgDiv.querySelector(".chat-bubble");
        if (emptyBubble && !emptyBubble.innerHTML.trim()) {
          emptyBubble.remove();
        }
        // Set time
        const timeEl = msgDiv.querySelector(".chat-time");
        if (timeEl && msg.time) timeEl.textContent = msg.time;
        continue;
      }

      // ── Legacy: no segments (backward compat) ──
      if (msg.role === "assistant" && msg.tool_calls?.length) {
        for (const tc of msg.tool_calls) {
          const div = document.createElement("div");
          div.className = "chat-tool-call done";
          let inputStr;
          try {
            inputStr = JSON.stringify(tc.input, null, 2);
          } catch (e) {
            inputStr = String(tc.input);
          }
          let resultStr;
          try {
            resultStr =
              typeof tc.result === "object"
                ? JSON.stringify(tc.result, null, 2)
                : String(tc.result);
          } catch (e) {
            resultStr = String(tc.result);
          }
          div.innerHTML =
            '<details><summary><i data-lucide="wrench"></i> <strong>' +
            esc(tc.name) +
            "</strong>" +
            '<span class="chat-tool-status"> <i data-lucide="check"></i> 完了</span></summary>' +
            '<pre class="chat-tool-detail">' +
            esc(inputStr) +
            "</pre>" +
            '<pre class="chat-tool-detail chat-tool-result-content">' +
            esc(resultStr) +
            "</pre></details>";
          msgContainer.appendChild(div);
        }
      }
      appendChatMessage(
        msg.role,
        msg.content,
        msg.time,
        msg.role === "assistant",
      );
      if (msg.role !== "assistant" && msg.tool_calls?.length) {
        for (const tc of msg.tool_calls) {
          const div = document.createElement("div");
          div.className = "chat-tool-call done";
          let inputStr;
          try {
            inputStr = JSON.stringify(tc.input, null, 2);
          } catch (e) {
            inputStr = String(tc.input);
          }
          let resultStr;
          try {
            resultStr =
              typeof tc.result === "object"
                ? JSON.stringify(tc.result, null, 2)
                : String(tc.result);
          } catch (e) {
            resultStr = String(tc.result);
          }
          div.innerHTML =
            '<details><summary><i data-lucide="wrench"></i> <strong>' +
            esc(tc.name) +
            "</strong>" +
            '<span class="chat-tool-status"> <i data-lucide="check"></i> 完了</span></summary>' +
            '<pre class="chat-tool-detail">' +
            esc(inputStr) +
            "</pre>" +
            '<pre class="chat-tool-detail chat-tool-result-content">' +
            esc(resultStr) +
            "</pre></details>";
          msgContainer.appendChild(div);
        }
      }
    }
    setTimeout(() => {
      if (typeof lucide !== "undefined") lucide.createIcons();
    }, 50);
  } catch (e) {
    console.error("[restoreChatHistory] failed:", e);
    toast("チャット履歴復元失敗: " + e.message, "error");
    // Session not found or API unavailable — start fresh
    const skel = document.getElementById("chat-history-skeleton");
    if (skel) skel.remove();
  }
}

// ------------------------------------------------------------------
// Export chat history
// ------------------------------------------------------------------
function exportChatHistory() {
  const container = document.getElementById("chat-messages");
  if (!container) return;
  const bubbles = container.querySelectorAll(".chat-msg");
  if (bubbles.length === 0) {
    toast("エクスポートする会話がありません", "error");
    return;
  }
  const lines = [];
  const persona = S.persona;
  lines.push("# 会話ログ - " + persona);
  lines.push("> エクスポート日時: " + new Date().toISOString());
  lines.push("");
  bubbles.forEach((msg) => {
    const role = msg.classList.contains("user")
      ? '**ユーザー**'
      : '**アシスタント**';
    const bubble = msg.querySelector(".chat-bubble");
    const time = msg.querySelector(".chat-time")?.textContent || "";
    const content = bubble ? bubble.textContent : "";
    lines.push("### " + role + " _" + time + "_");
    lines.push("");
    lines.push(content);
    lines.push("");
  });
  const blob = new Blob([lines.join("\n")], {
    type: "text/markdown;charset=utf-8",
  });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download =
    "chat-" + persona + "-" + new Date().toISOString().slice(0, 10) + ".md";
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
  toast("会話をエクスポートしました", "success");
}

// ------------------------------------------------------------------
// Delete a chat message and all subsequent messages
// ------------------------------------------------------------------
async function deleteChatMessage(msgIndex) {
  if (!S.persona) return;

  const container = document.getElementById("chat-messages");
  const allMsgs = container.querySelectorAll(".chat-msg");
  const subsequentCount = allMsgs.length - msgIndex;

  const confirmed = await showConfirm(
    "このメッセージを削除しますか？以降の " + subsequentCount + " 件のメッセージも削除されます。"
  );
  if (!confirmed) return;

  const sid = getChatSessionId();
  try {
    const result = await api(
      "/api/chat/" +
        encodeURIComponent(S.persona) +
        "/sessions/" +
        encodeURIComponent(sid) +
        "/rollback",
      { method: "POST", body: JSON.stringify({ keep_until: msgIndex }) }
    );

    // Remove DOM messages from msgIndex onwards
    const currentMsgs = container.querySelectorAll(".chat-msg");
    for (const msg of currentMsgs) {
      if (parseInt(msg.dataset.msgIndex) >= msgIndex) msg.remove();
    }

    // Restore welcome if no messages left
    if (container.querySelectorAll(".chat-msg").length === 0) {
      resetToWelcome();
    }

    // Find last remaining user message for auto-regeneration
    const remaining = result.remaining_messages || [];
    let lastUserText = null;
    for (let i = remaining.length - 1; i >= 0; i--) {
      if (remaining[i].role === "user") {
        lastUserText = remaining[i].content;
        break;
      }
    }

    if (lastUserText) {
      const inputEl = document.getElementById("chat-input");
      if (inputEl) {
        inputEl.value = lastUserText;
        inputEl.focus();
        inputEl.dispatchEvent(new Event("input"));
      }
      setTimeout(() => chatSend(false), 100);
    }

    toast("🗑️ メッセージを削除しました", "success");
  } catch (e) {
    toast("削除失敗: " + e.message, "error");
  }
}

// ------------------------------------------------------------------
// Expose on N.Chat.history
// ------------------------------------------------------------------
N.Chat.history = {
  restore: restoreChatHistory,
  clear: clearChatHistory,
  rollback: rollbackChat,
  edit: editChatMessage,
  delete: deleteChatMessage,
  export: exportChatHistory,
  reset: resetToWelcome,
  getSessionId: getChatSessionId,
};

// Expose globals:
window.restoreChatHistory = restoreChatHistory;
window.clearChatHistory = clearChatHistory;
window.rollbackChat = rollbackChat;
window.editChatMessage = editChatMessage;
window.deleteChatMessage = deleteChatMessage;
window.exportChatHistory = exportChatHistory;
window.resetToWelcome = resetToWelcome;
window.getChatSessionId = getChatSessionId;

})(window.Nous);
