/* =================================================================
   CHAT HISTORY — History restore, clear, rollback, edit, export
   Extracted from chat.js (Phase 3, Batch 2)
   ================================================================= */
;(function(N) {
var C = N.Core;
var api = C.api, esc = C.esc, toast = C.toast, safeSetHTML = C.safeSetHTML;
var showConfirm = C.showConfirm, showAlert = C.showAlert;
var truncate = C.truncate, relativeTime = C.relativeTime, fmtDate = C.fmtDate;
var safeMarkdown = N.Chat.markdown && N.Chat.markdown.render;
var appendChatMessage = N.Chat.ui && N.Chat.ui.append;
"use strict";
var S = window.S;

var CHAT = N.Chat.state;
var _historyGen = 0;
var _restoreLock = false;

// ------------------------------------------------------------------
// Reset to welcome screen
// ------------------------------------------------------------------
function resetToWelcome() {
  const container = document.getElementById("chat-messages");
  safeSetHTML(container, `
        <div class="chat-welcome" id="chat-welcome">
            <div class="chat-welcome-icon"><i data-lucide="message-circle"></i></div>
            <p>チャットを開始するには下のテキストボックスにメッセージを入力してください。</p>
            <p class="chat-welcome-hint">APIキーとプロバイダーを設定してください。<br><a href="#" onclick="N.Chat.core.toggleSettings();return false;" class="chat-welcome-link"><i data-lucide="settings"></i> 設定パネルを開く</a></p>
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

// ------------------------------------------------------------------
// Clear chat history
// ------------------------------------------------------------------
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

// ------------------------------------------------------------------
// Get chat session ID
// ------------------------------------------------------------------
function getChatSessionId() {
  // Fixed session ID per persona — enables cross-device sync
  return "main";
}

// ------------------------------------------------------------------
// Shared: append tool_call / tool_result / text bubble elements from segments
// into the given message div. Uses restoreChatHistory's rendering logic.
// ------------------------------------------------------------------
function _appendSegmentsToBubble(msg, msgDiv) {
  if (!msg.segments || !msg.segments.length) return;
  var toolCallDivs = {};
  for (var si = 0; si < msg.segments.length; si++) {
    var seg = msg.segments[si];
    if (seg.type === "text") {
      var bubble = document.createElement("div");
      bubble.className = "chat-bubble";
      safeSetHTML(bubble, safeMarkdown(seg.content));
      bubble.querySelectorAll("img").forEach(function(img) {
        img.style.cssText = "max-width:100%;border-radius:8px;cursor:pointer;margin:8px 0;";
        img.addEventListener("click", function() { N.Chat.attachments.openViewer(img.src, "image"); });
      });
      var timeDiv = msgDiv.querySelector(".chat-time");
      if (timeDiv) msgDiv.insertBefore(bubble, timeDiv);
      else msgDiv.appendChild(bubble);
    } else if (seg.type === "thinking") {
      // CoT restore (R7): same .chat-thinking-bubble <details> as streaming.
      // NOT .chat-bubble — excluded from TTS manual / copy collectors.
      if (!seg.content) continue;
      var thinkDiv = document.createElement("details");
      thinkDiv.className = "chat-thinking-bubble";
      thinkDiv.open = true;
      safeSetHTML(thinkDiv,
        '<summary><i data-lucide="brain"></i> 思考過程</summary>' +
        '<div class="chat-thinking-body"></div>');
      thinkDiv.querySelector(".chat-thinking-body").textContent = seg.content;
      var timeDiv3 = msgDiv.querySelector(".chat-time");
      if (timeDiv3) msgDiv.insertBefore(thinkDiv, timeDiv3);
      else msgDiv.appendChild(thinkDiv);
    } else if (seg.type === "tool_call") {
      var inputStr;
      try { inputStr = JSON.stringify(seg.input, null, 2); } catch (e) { inputStr = String(seg.input); }
      var div = document.createElement("div");
      div.className = "chat-tool-call done";
      if (seg.id) div.dataset.toolId = seg.id;
      safeSetHTML(div, '<details><summary>' +
        '<span class="chat-tool-summary-left">' +
        '<i data-lucide="wrench"></i> <strong>' +
        esc(seg.name) + '</strong></span>' +
        '<span class="chat-tool-chevron"><i data-lucide="chevron-right"></i></span>' +
        '<span class="chat-tool-status"><i data-lucide="check"></i> 完了</span></summary>' +
        '<pre class="chat-tool-detail">' + esc(inputStr) + '</pre></details>');
      if (seg.id) toolCallDivs[seg.id] = div;
      var timeDiv2 = msgDiv.querySelector(".chat-time");
      if (timeDiv2) msgDiv.insertBefore(div, timeDiv2);
      else msgDiv.appendChild(div);
    } else if (seg.type === "tool_result") {
      var toolDiv = seg.id ? toolCallDivs[seg.id] : null;
      if (toolDiv) {
        var resultStr;
        try { resultStr = typeof seg.result === "object" ? JSON.stringify(seg.result, null, 2) : String(seg.result); }
        catch (e) { resultStr = String(seg.result); }
        var details = toolDiv.querySelector("details");
        if (details) {
          var resultPre = document.createElement("pre");
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
              if (img.url) {
                imgEl.src = img.url;
              } else if (img.base64) {
                try {
                  var binary = atob(img.base64);
                  var bytes = new Uint8Array(binary.length);
                  for (var b = 0; b < binary.length; b++) bytes[b] = binary.charCodeAt(b);
                  var blob = new Blob([bytes], { type: "image/png" });
                  imgEl.src = URL.createObjectURL(blob);
                } catch (e) {
                  imgEl.src = "data:image/png;base64," + img.base64;
                }
              }
              imgEl.alt = img.revised_prompt || "生成画像";
              imgEl.title = img.revised_prompt || "";
              imgEl.dataset.revisedPrompt = img.revised_prompt || "";
              imgEl.dataset.negativePrompt = img.negative_prompt || "";
              imgEl.onerror = function() {
                imgEl.style.display = "none";
                var errDiv = document.createElement("div");
                errDiv.className = "image-gen-error";
                errDiv.textContent = "⚠️ 画像のデコードに失敗しました";
                card.insertBefore(errDiv, card.firstChild);
              };
              imgEl.onclick = function() {
                if (typeof N.Chat.attachments.openViewer === "function") {
                  N.Chat.attachments.openViewer(imgEl.src, "image", null, {
                    revised_prompt: imgEl.dataset.revisedPrompt,
                    negative_prompt: imgEl.dataset.negativePrompt,
                  });
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
              toolDiv.parentNode.insertBefore(card, toolDiv.nextSibling);
            });
          }
        }
      }
    }
  }
  // Remove empty bubble if appendChatMessage created one with no content
  var emptyBubble = msgDiv.querySelector(".chat-bubble");
  if (emptyBubble && !emptyBubble.innerHTML.trim()) emptyBubble.remove();
  // Set time
  var timeEl = msgDiv.querySelector(".chat-time");
  if (timeEl && msg.time) timeEl.textContent = msg.time;
}

// ------------------------------------------------------------------
// Rollback: undo messages from keep_until onwards, optionally auto-resend
// ------------------------------------------------------------------
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
        appendChatMessage(msg.role, "", msg.time, false, msg.id);
        _appendSegmentsToBubble(msg, container.querySelector(".chat-msg:last-child"));
      } else {
        appendChatMessage(msg.role, msg.content, msg.time, msg.role === "assistant", msg.id);
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
// Inline edit: 編集ボタン用 — textarea.value 代入なし、undo スタック非破壊
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
// Restore chat history from server on page load / persona switch
// ------------------------------------------------------------------
async function restoreChatHistory(showSkeleton) {
  if (showSkeleton === undefined) showSkeleton = true;
  if (!S.persona) return;
  if (CHAT._justReset) {
    CHAT._justReset = false;
    return; // リセット直後は履歴を再取得しない
  }
  // Generation counter — prevent stale response from overwriting newer data
  var myGen = ++_historyGen;
  // Exclusive lock — prevent concurrent restore calls
  if (_restoreLock) return;
  _restoreLock = true;
  try {
  const sid = getChatSessionId();
  const container = document.getElementById("chat-messages");
  // Show loading skeleton while fetching history (Bug B3 fix: don't reset DOM before fetch)
  if (showSkeleton) {
    const skeletonHtml =
      '<div class="chat-msg assistant"><div class="chat-bubble" style="opacity:0.5"><div class="skeleton skeleton-text" style="width:80%;height:14px;margin-bottom:8px"></div><div class="skeleton skeleton-text" style="width:60%;height:14px;margin-bottom:8px"></div><div class="skeleton skeleton-text" style="width:40%;height:14px"></div></div></div>' +
      '<div class="chat-msg user" style="align-self:flex-end"><div class="chat-bubble" style="opacity:0.5"><div class="skeleton skeleton-text" style="width:70%;height:14px;margin-bottom:8px"></div><div class="skeleton skeleton-text" style="width:50%;height:14px"></div></div></div>';
    const skeletonDiv = document.createElement("div");
    skeletonDiv.id = "chat-history-skeleton";
    safeSetHTML(skeletonDiv, skeletonHtml);
    container.appendChild(skeletonDiv);
  }
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
    if (myGen !== _historyGen) return; // 新しい呼び出しに敗退
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
    container.textContent = "";
    for (const msg of msgs) {
      const msgContainer = document.getElementById("chat-messages");

      // ── Segments-based rendering (F2: correct interleaving) ──
      if (msg.segments) {
        appendChatMessage(msg.role, "", msg.time, false, msg.id);
        _appendSegmentsToBubble(msg, msgContainer.querySelector(".chat-msg:last-child"));
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
          safeSetHTML(div,
            '<details><summary>' +
            '<span class="chat-tool-summary-left">' +
            '<i data-lucide="wrench"></i> <strong>' +
            esc(tc.name) +
            '</strong></span>' +
            '<span class="chat-tool-chevron"><i data-lucide="chevron-right"></i></span>' +
            '<span class="chat-tool-status"><i data-lucide="check"></i> 完了</span></summary>' +
            '<pre class="chat-tool-detail">' +
            esc(inputStr) +
            "</pre>" +
            '<pre class="chat-tool-detail chat-tool-result-content">' +
            esc(resultStr) +
            "</pre></details>");
          msgContainer.appendChild(div);
        }
      }
      appendChatMessage(
        msg.role,
        msg.content,
        msg.time,
        msg.role === "assistant",
        msg.id,
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
          safeSetHTML(div,
            '<details><summary>' +
            '<span class="chat-tool-summary-left">' +
            '<i data-lucide="wrench"></i> <strong>' +
            esc(tc.name) +
            '</strong></span>' +
            '<span class="chat-tool-chevron"><i data-lucide="chevron-right"></i></span>' +
            '<span class="chat-tool-status"><i data-lucide="check"></i> 完了</span></summary>' +
            '<pre class="chat-tool-detail">' +
            esc(inputStr) +
            "</pre>" +
            '<pre class="chat-tool-detail chat-tool-result-content">' +
            esc(resultStr) +
            "</pre></details>");
          msgContainer.appendChild(div);
        }
      }
    }
    N.Core.refreshIcons();
  } catch (e) {
    console.error("[restoreChatHistory] failed:", e);
    toast("チャット履歴復元失敗: " + e.message, "error");
    // Session not found or API unavailable — start fresh
    const skel = document.getElementById("chat-history-skeleton");
    if (skel) skel.remove();
  }
  // 最下部にスクロール
  const c = document.getElementById("chat-messages");
  if (c) {
    requestAnimationFrame(function() {
      c.scrollTop = c.scrollHeight;
    });
  }
  } finally {
    _restoreLock = false;
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
        appendChatMessage(msg.role, "", msg.time, false, msg.id);
        _appendSegmentsToBubble(msg, container.querySelector(".chat-msg:last-child"));
      } else {
        appendChatMessage(msg.role, msg.content, msg.time, msg.role === "assistant", msg.id);
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

})(window.Nous);
