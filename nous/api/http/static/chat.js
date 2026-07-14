/* =================================================================
   CHAT TAB
   ================================================================= */
/* CHAT state + HELP_TEXTS → extracted to chat/chat-core.js */
const CHAT = window.Nous.Chat.state;

/* showHelpTooltip + hideHelpTooltip → extracted to chat/chat-core.js */

/* loadChat → extracted to chat/chat-core.js */

/* setupChatInputHandler + setupChatInputHandlerWithObserver + chatInputKeydownHandler + chatInputInputHandler → extracted to chat/chat-core.js */

/* toggleSettingsPanel + toggleMemoryPanel + renderDebugPanel → extracted to chat/chat-core.js */

// ESC key closes settings panel on mobile
document.addEventListener("keydown", function (e) {
  if (e.key === "Escape" && CHAT.sidebarOpen) {
    var isMobile = window.innerWidth <= 768;
    if (isMobile) {
      toggleSettingsPanel();
    }
  }
});

/* updateMemoryPanel — extracted to chat/chat-memory-panel.js */


/* showReflectionStart + updateReflectionPanel + showSessionSummarized + showContextCompressed — extracted to chat/chat-memory-panel.js */


/* resetToWelcome — extracted to chat/chat-history.js */


/* clearChatHistory — extracted to chat/chat-history.js */


/* getChatSessionId — extracted to chat/chat-history.js */


/* rollbackChat — extracted to chat/chat-history.js */


/* editChatMessage — extracted to chat/chat-history.js */


/* appendChatMessage — extracted to chat/chat-send.js */


/* safeMarkdown — extracted to chat/chat-markdown.js */


/* restoreChatHistory — extracted to chat/chat-history.js */


/* chatCancel — extracted to chat/chat-send.js */


/* exportChatHistory — extracted to chat/chat-history.js */


/* ── Voice input (Web Speech API) ── */
let _voiceRecognition = null;
function toggleVoiceInput() {
  const btn = document.getElementById("chat-voice-btn");
  if (!("webkitSpeechRecognition" in window || "SpeechRecognition" in window)) {
    toast("お使いのブラウザは音声入力に対応していません", "error");
    return;
  }
  const SpeechRecognition =
    window.SpeechRecognition || window.webkitSpeechRecognition;
  if (_voiceRecognition) {
    _voiceRecognition.stop();
    _voiceRecognition = null;
    if (btn) {
      btn.innerHTML = '<i data-lucide="mic"></i>';
      btn.style.color = "";
    }
    return;
  }
  _voiceRecognition = new SpeechRecognition();
  _voiceRecognition.lang = "ja-JP";
  _voiceRecognition.interimResults = false;
  _voiceRecognition.continuous = false;
  if (btn) {
    btn.innerHTML = '<i data-lucide="circle-dot"></i>';
    btn.style.color = "var(--accent-red)";
  }
  _voiceRecognition.onresult = (event) => {
    const transcript = event.results[0][0].transcript;
    const inputEl = document.getElementById("chat-input");
    if (inputEl) {
      inputEl.value = (inputEl.value ? inputEl.value + " " : "") + transcript;
      inputEl.dispatchEvent(new Event("input"));
    }
    _voiceRecognition = null;
    if (btn) {
      btn.innerHTML = '<i data-lucide="mic"></i>';
      btn.style.color = "";
    }
  };
  _voiceRecognition.onerror = () => {
    toast("音声認識エラー", "error");
    _voiceRecognition = null;
    if (btn) {
      btn.innerHTML = '<i data-lucide="mic"></i>';
      btn.style.color = "";
    }
  };
  _voiceRecognition.onend = () => {
    if (btn) {
      btn.innerHTML = '<i data-lucide="mic"></i>';
      btn.style.color = "";
    }
  };
  _voiceRecognition.start();
}

function appendToolEvent(eventType, data, targetDiv) {
  const container = document.getElementById("chat-messages");

  if (eventType === "tool_call") {
    const div = document.createElement("div");
    div.className = "chat-tool-call";
    div.dataset.toolId = data.id || "";
    let inputStr;
    try {
      inputStr = JSON.stringify(data.input, null, 2);
    } catch (e) {
      inputStr = String(data.input);
    }
    div.innerHTML =
      '<details><summary><i data-lucide="wrench"></i> <strong>' +
      esc(data.name) +
      "</strong>" +
      '<span class="chat-tool-status">実行中...</span></summary>' +
      '<pre class="chat-tool-detail">' +
      esc(inputStr) +
      "</pre></details>";
    if (targetDiv) {
      // F3: inline insertion inside assistant div (before .chat-time)
      const timeDiv = targetDiv.querySelector(".chat-time");
      if (timeDiv) {
        targetDiv.insertBefore(div, timeDiv);
      } else {
        targetDiv.appendChild(div);
      }
    } else {
      // Legacy: insert tool_call after the last assistant message
      const lastAssistant = container.querySelector(".chat-msg.assistant:last-child");
      if (lastAssistant && lastAssistant.nextSibling) {
        container.insertBefore(div, lastAssistant.nextSibling);
      } else if (lastAssistant) {
        container.appendChild(div);
      } else {
        container.appendChild(div);
      }
    }
    container.scrollTop = container.scrollHeight;
    setTimeout(() => {
      if (typeof lucide !== "undefined") lucide.createIcons();
    }, 50);
    return div;
  } else if (eventType === "tool_result") {
    let resultStr;
    try {
      resultStr =
        typeof data.result === "object"
          ? JSON.stringify(data.result, null, 2)
          : String(data.result);
    } catch (e) {
      resultStr = String(data.result);
    }

    // ── Duplicate notification ──
    if (
      typeof data.result === "object" &&
      data.result &&
      data.result.status === "duplicate"
    ) {
      toast(
        "⚠️ " + (data.result.message || "類似の記憶が既に存在します"),
        "warning",
      );
    }

    // Find matching tool_call div by id and update it
    const callDiv = data.id
      ? container.querySelector('[data-tool-id="' + CSS.escape(data.id) + '"]')
      : null;
    if (callDiv) {
      const statusEl = callDiv.querySelector(".chat-tool-status");
      if (statusEl) statusEl.innerHTML = ' <i data-lucide="check"></i> 完了';
      const details = callDiv.querySelector("details");
      if (details) {
        const resultPre = document.createElement("pre");
        resultPre.className = "chat-tool-detail chat-tool-result-content";
        resultPre.textContent = resultStr;
        details.appendChild(resultPre);
      }
      callDiv.classList.add("done");
      container.scrollTop = container.scrollHeight;
    } else {
      const div = document.createElement("div");
      div.className = "chat-tool-result";
      div.innerHTML =
        '<details><summary><i data-lucide="check"></i> <strong>' +
        esc(data.name) +
        "</strong></summary>" +
        '<pre class="chat-tool-detail chat-tool-result-content">' +
        esc(resultStr) +
        "</pre></details>";
      container.appendChild(div);
      container.scrollTop = container.scrollHeight;
      setTimeout(() => {
        if (typeof lucide !== "undefined") lucide.createIcons();
      }, 50);
      return div;
    }
  }
}

/* showTypingIndicator + removeTypingIndicator — extracted to chat/chat-send.js */


async function uploadAttachment(file) {
  if (!S.persona) {
    toast("ペルソナを選択してください", "error");
    return;
  }
  const formData = new FormData();
  formData.append("file", file);
  try {
    const res = await fetch(
      "/api/chat/" + encodeURIComponent(S.persona) + "/attachment/upload",
      {
        method: "POST",
        body: formData,
      },
    );
    if (!res.ok) throw new Error("HTTP " + res.status);
    const data = await res.json();
    data.file = file; // 元のFileオブジェクトを保持（Base64エンコード用）
    CHAT.attachments.push(data);
    renderAttachmentBadge(data);
  } catch (e) {
    toast("ファイルのアップロードに失敗しました: " + e.message, "error");
  }
}

function renderAttachmentBadge(att) {
  const area = document.getElementById("chat-attachments");
  if (!area) return;
  const badge = document.createElement("div");
  badge.className = "chat-attachment-badge";
  badge.dataset.filename = att.filename;

  const isImage = att.mime_type && att.mime_type.startsWith("image/");
  const isVideo = att.mime_type && att.mime_type.startsWith("video/");
  const isAudio = att.mime_type && att.mime_type.startsWith("audio/");

  if (isImage) {
    const img = document.createElement("img");
    img.className = "thumb";
    img.src = att.url;
    img.alt = att.filename;
    img.onclick = () => openMediaViewer(att.url, "image");
    badge.appendChild(img);
  } else if (isVideo) {
    const vid = document.createElement("video");
    vid.className = "thumb";
    vid.src = att.url;
    vid.muted = true;
    vid.onclick = () => openMediaViewer(att.url, "video");
    badge.appendChild(vid);
  } else if (isAudio) {
    const icon = document.createElement("span");
    icon.innerHTML = '<i data-lucide="volume-2"></i>';
    badge.appendChild(icon);
    badge.style.cursor = "pointer";
    badge.onclick = () => openMediaViewer(att.url, "audio", att.mime_type);
  } else {
    const icon = document.createElement("span");
    const ext = att.filename.split(".").pop().toLowerCase();
    if (ext === "pdf") {
      icon.innerHTML = '<i data-lucide="book"></i>';
      badge.appendChild(icon);
      badge.style.cursor = "pointer";
      badge.onclick = () => openMediaViewer(att.url, "pdf");
    } else {
      icon.innerHTML =
        ext === "zip" || ext === "tar" || ext === "gz"
          ? '<i data-lucide="package"></i>'
          : '<i data-lucide="file-text"></i>';
      badge.appendChild(icon);
    }
  }

  const nameSpan = document.createElement("span");
  nameSpan.className = "attach-name";
  nameSpan.textContent = att.filename;
  badge.appendChild(nameSpan);

  const removeBtn = document.createElement("button");
  removeBtn.className = "attach-remove";
  removeBtn.innerHTML = '<i data-lucide="x"></i>';
  removeBtn.onclick = () => {
    CHAT.attachments = CHAT.attachments.filter(
      (a) => a.filename !== att.filename,
    );
    badge.remove();
  };
  badge.appendChild(removeBtn);
  area.appendChild(badge);
}

function openMediaViewer(url, type, mimeType) {
  const overlay = document.getElementById("media-viewer-overlay");
  const inner = document.getElementById("media-viewer-inner");
  if (!overlay || !inner) return;
  inner.innerHTML = "";
  if (type === "image") {
    const img = document.createElement("img");
    img.src = url;
    inner.appendChild(img);
  } else if (type === "video") {
    const vid = document.createElement("video");
    vid.src = url;
    vid.controls = true;
    vid.autoplay = true;
    inner.appendChild(vid);
  } else if (type === "pdf") {
    inner.innerHTML =
      '<iframe src="' +
      url +
      '" width="100%" height="80vh" style="border:none;border-radius:8px;"></iframe>';
  } else if (type === "audio") {
    inner.innerHTML =
      '<audio controls autoplay style="max-width:90vw;"><source src="' +
      url +
      '" type="' +
      (mimeType || "audio/mpeg") +
      '"></audio>';
  } else {
    const vid = document.createElement("video");
    vid.src = url;
    vid.controls = true;
    vid.autoplay = true;
    inner.appendChild(vid);
  }
  overlay.classList.add("visible");
  // ESC to close
  const escHandler = (e) => {
    if (e.key === "Escape") {
      closeMediaViewer();
      document.removeEventListener("keydown", escHandler);
    }
  };
  document.addEventListener("keydown", escHandler);
}

function closeMediaViewer() {
  const overlay = document.getElementById("media-viewer-overlay");
  const inner = document.getElementById("media-viewer-inner");
  if (overlay) overlay.classList.remove("visible");
  if (inner) {
    const vid = inner.querySelector("video");
    if (vid) vid.pause();
    inner.innerHTML = "";
  }
}

/* _memEditKey + openMemEdit + closeMemEdit + saveMemEdit + deleteMemCard + completeGoal — extracted to chat/chat-memory-panel.js */


/* ── Slash command handler ── */
const SLASH_COMMANDS = [
  { name: "/memory", desc: "記憶を作成", example: "/memory 今日は楽しかった" },
  {
    name: "/goal",
    desc: "目標を作成",
    example: "/goal プロジェクトを完成させる",
  },
  { name: "/help", desc: "コマンド一覧を表示", example: "/help" },
  { name: "/search", desc: "記憶を検索", example: "/search 昨日の会話" },
  { name: "/image", desc: "画像を生成", example: "/image 猫の写真" },
  {
    name: "/invoke_skill",
    desc: "スキルを呼び出す",
    example: "/invoke_skill skill_name",
  },
];

function showHelpCommand() {
  const timeStr = new Date().toLocaleTimeString("ja-JP", {
    hour: "2-digit",
    minute: "2-digit",
  });
  let msg = "**利用可能なコマンド**\n\n";
  SLASH_COMMANDS.forEach(function (cmd) {
    msg += "`" + cmd.name + "` — " + cmd.desc + "\n";
    msg += "  例: `" + cmd.example + "`\n\n";
  });
  msg += "**キーボードショートカット**\n\n";
  msg += "`Alt+1` ~ `Alt+0` — タブ切り替え\n";
  msg += "`Ctrl+F` — 検索\n";
  msg += "`Enter` — 送信 / `Shift+Enter` — 改行\n";
  appendChatMessage("assistant", msg, timeStr, true);
}

function showCommandPopup(inputEl) {
  hideCommandPopup();
  const val = inputEl.value.trim();
  if (!val.startsWith("/")) return;

  const query = val.toLowerCase();
  const matches = SLASH_COMMANDS.filter(function (cmd) {
    return cmd.name.startsWith(query);
  });
  if (matches.length === 0) return;

  S.slashCommandIndex = 0;

  const popup = document.createElement("div");
  popup.className = "chat-command-popup";
  popup.id = "chat-command-popup";

  matches.forEach(function (cmd, idx) {
    const item = document.createElement("div");
    item.className = "chat-command-item" + (idx === 0 ? " active" : "");
    item.setAttribute("role", "option");
    item.setAttribute("aria-selected", idx === 0 ? "true" : "false");
    item.innerHTML =
      '<span class="cmd-name">' +
      cmd.name +
      '</span><span class="cmd-desc">' +
      cmd.desc +
      "</span>";
    item.onclick = function () {
      inputEl.value = cmd.name + " ";
      inputEl.focus();
      hideCommandPopup();
      inputEl.dispatchEvent(new Event("input"));
    };
    popup.appendChild(item);
  });

  const inputArea = inputEl.closest("#chat-input-area") || inputEl.parentNode;
  inputArea.style.position = "relative";
  inputArea.appendChild(popup);
}

function hideCommandPopup() {
  const existing = document.getElementById("chat-command-popup");
  if (existing) existing.remove();
  S.slashCommandIndex = -1;
}

function updateSlashSelection(items) {
  items.forEach(function (el, i) {
    var selected = i === S.slashCommandIndex;
    el.classList.toggle("active", selected);
    el.setAttribute("aria-selected", selected ? "true" : "false");
  });
}

async function handleSlashCommand(toolName, toolInput) {
  const inputEl = document.getElementById("chat-input");
  const rawInput = inputEl.value.trim();
  inputEl.value = "";
  inputEl.style.height = "auto";
  const timeStr = new Date().toLocaleTimeString("ja-JP", {
    hour: "2-digit",
    minute: "2-digit",
  });
  appendChatMessage("user", rawInput, timeStr);
  showTypingIndicator();
  try {
    const resp = await api(
      "/api/chat/" + encodeURIComponent(S.persona) + "/tool",
      {
        method: "POST",
        body: JSON.stringify({ tool: toolName, input: toolInput }),
      },
    );
    removeTypingIndicator();
    const resultMsg =
      resp.status === "ok"
        ? '<i data-lucide="check"></i> ' +
          (resp.key
            ? "作成: " + resp.key
            : resp.updated
              ? "更新: " + resp.updated
              : "実行完了")
        : '<i data-lucide="x"></i> ' + (resp.message || resp.error || "エラー");
    appendChatMessage(
      "assistant",
      resultMsg,
      new Date().toLocaleTimeString("ja-JP", {
        hour: "2-digit",
        minute: "2-digit",
      }),
    );
    if (resp.status === "ok") toast(resultMsg, "success");
  } catch (ex) {
    removeTypingIndicator();
    appendChatMessage(
      "assistant",
      '<i data-lucide="x"></i> コマンド実行失敗: ' + ex.message,
      new Date().toLocaleTimeString("ja-JP", {
        hour: "2-digit",
        minute: "2-digit",
      }),
    );
    toast("コマンド失敗: " + ex.message, "error");
  }
}

/* _createAssistantDiv + _createTextBubble — extracted to chat/chat-send.js */


/* chatSend — extracted to chat/chat-send.js */


// Chat auto-resize and keyboard handler — now registered via loadChat() -> setupChatInputHandler()
// DOMContentLoaded に依存しない: MutationObserver で #chat-input を待つ

// Reload chat config when persona changes
let __chatPersonaTries = 0;
const __CHAT_PERSONA_MAX_TRIES = 20;
window.__chatPersonaWatcher = setInterval(() => {
  const sel = document.getElementById("persona-select");
  if (!sel) {
    __chatPersonaTries++;
    if (__chatPersonaTries >= __CHAT_PERSONA_MAX_TRIES) {
      console.warn("[chat] #persona-select not found after 20 tries, giving up");
      clearInterval(window.__chatPersonaWatcher);
    }
    return;
  }
  if (!sel._chatBound) {
    sel._chatBound = true;
    sel.addEventListener("change", () => {
      // DOM reset + history restore is handled by base.py's loadTab() → loadChat() → restoreChatHistory()
      // Do NOT call clearChatHistory() here — it would destroy the session ID and break history
      if (S.tab === "chat") {
        loadChatConfig();
        loadChatCommitments();
      }
    });
    clearInterval(window.__chatPersonaWatcher);
  }
}, 500);

const FILE_OP_TOOLS = new Set([
  "edit",
  "create",
  "view",
  "bash",
  "powershell",
  "str_replace_editor",
  "write_file",
  "read_file",
  "delete_file",
  "list_files",
  "glob",
  "grep",
]);

function updateEquipmentPanel(update) {
  const list = document.getElementById("memory-equipment-list");
  if (!list) return;
  if (!update) return;

  // Build equipment display from update data
  const equipped = update.equip || {};
  const unequipped = update.unequip || [];
  const added = update.add_items || [];

  let html = "";
  const entries = Object.entries(equipped).filter(function (e) {
    return e[1] != null && e[1] !== "";
  });
  if (entries.length > 0) {
    html +=
      '<div style="font-size:0.75rem;font-weight:600;color:var(--text-muted);margin-bottom:4px;"><i data-lucide="shield" style="width:12px;height:12px;vertical-align:middle;margin-right:4px;"></i>装備中</div>';
    for (const [slot, item] of entries) {
      const slotIcon =
        {
          top: "shirt",
          bottom: "footprints",
          shoes: "footprints",
          outer: "jacket",
          accessories: "gem",
          head: "crown",
        }[slot] || "circle";
      const slotLabel =
        {
          top: "上",
          bottom: "下",
          shoes: "靴",
          outer: "アウター",
          accessories: "アクセ",
          head: "頭",
        }[slot] || slot;
      html +=
        '<div style="font-size:0.73rem;padding:2px 0;display:flex;justify-content:space-between;align-items:center;">' +
        '<span style="display:inline-flex;align-items:center;gap:4px;"><i data-lucide="' +
        slotIcon +
        '" style="width:11px;height:11px;opacity:0.7;"></i>' +
        slotLabel +
        "</span><span>" +
        esc(String(item)) +
        "</span></div>";
    }
  }
  if (unequipped.length > 0) {
    html +=
      '<div style="font-size:0.7rem;opacity:0.6;margin-top:4px;">外した: ' +
      unequipped
        .map(function (i) {
          return esc(String(i));
        })
        .join(", ") +
      "</div>";
  }
  if (added.length > 0) {
    html +=
      '<div style="font-size:0.7rem;opacity:0.6;margin-top:2px;">追加: ' +
      added
        .map(function (i) {
          return esc(String(i));
        })
        .join(", ") +
      "</div>";
  }

  if (html) {
    list.innerHTML = html;
    // Re-render Lucide icons in the equipment panel
    setTimeout(() => {
      if (typeof lucide !== "undefined") lucide.createIcons();
    }, 10);
  }
}

function handleFileToolCall(evt) {
  const icons = {
    edit: '<i data-lucide="pencil"></i>',
    create: '<i data-lucide="edit-3"></i>',
    view: '<i data-lucide="eye"></i>',
    bash: '<i data-lucide="settings"></i>',
    powershell: '<i data-lucide="settings"></i>',
    str_replace_editor: '<i data-lucide="pencil"></i>',
    delete_file: '<i data-lucide="trash-2"></i>',
    list_files: '<i data-lucide="folder-open"></i>',
    write_file: '<i data-lucide="edit-3"></i>',
    read_file: '<i data-lucide="eye"></i>',
    glob: '<i data-lucide="search"></i>',
    grep: '<i data-lucide="search"></i>',
  };
  const icon = icons[evt.name] || '<i data-lucide="wrench"></i>';
  const detail =
    evt.input?.path ||
    evt.input?.file_path ||
    evt.input?.command ||
    evt.input?.pattern ||
    evt.input?.glob ||
    "";
  // チャットにもツールバブルを表示（CodingAgent閉時でも見えるように）
  appendToolEvent("tool_call", evt);
}

/* ── Code block Run button ── */
async function execCodeBlock(code, language, resultEl, runBtn) {
  if (!S.persona) return;
  if (typeof openCodingAgent === "function") {
    openCodingAgent({ code, language });
    if (resultEl) {
      resultEl.className = "hljs-run-result stdout";
      resultEl.textContent = "▶ Coding Agent で開きました";
      resultEl.style.display = "block";
    }
    if (runBtn) runBtn.textContent = "▶ Run";
    return;
  }
  if (resultEl) {
    resultEl.className = "hljs-run-result stderr";
    resultEl.textContent = "サンドボックス実行は利用できません";
    resultEl.style.display = "block";
  }
}

/* ── Image Generation ── */
let _imageGenSpinnerId = null;

function showImageGenSpinner(evt) {
  const container = findChatLogContainer();
  if (!container) return;

  const spinner = document.createElement("div");
  spinner.className = "chat-image-gen-spinner";
  spinner.innerHTML = '<div class="spinner"></div> ';
  spinner.innerHTML +=
    "画像を生成中... (" + esc(evt.provider) + ", " + evt.n + "枚)";

  _imageGenSpinnerId = "image-gen-spinner-" + Date.now();
  spinner.id = _imageGenSpinnerId;
  container.appendChild(spinner);

  scrollToBottom(container);
}

function showImageGenResult(evt) {
  const container = findChatLogContainer();
  if (!container) return;

  // スピナーを削除
  if (_imageGenSpinnerId) {
    const spinner = document.getElementById(_imageGenSpinnerId);
    if (spinner) spinner.remove();
    _imageGenSpinnerId = null;
  }

  if (!evt.images || !evt.images.length) return;

  evt.images.forEach(function (img) {
    const card = document.createElement("div");
    card.className = "chat-image-gen-card";

    const imgEl = document.createElement("img");
    imgEl.src = "data:image/png;base64," + img.base64;
    imgEl.alt = img.revised_prompt || "生成画像";
    imgEl.title = img.revised_prompt || "";
    imgEl.onclick = function () {
      if (typeof openMediaViewer === "function") {
        openMediaViewer(imgEl.src, "image");
      } else {
        window.open(imgEl.src, "_blank");
      }
    };

    const meta = document.createElement("div");
    meta.className = "image-gen-meta";

    // 改訂プロンプトがあれば表示（先頭80文字）
    const rp = img.revised_prompt || "";
    if (rp) {
      const promptSpan = document.createElement("span");
      promptSpan.textContent =
        rp.length > 80 ? rp.substring(0, 80) + "..." : rp;
      promptSpan.style.fontStyle = "italic";
      meta.appendChild(promptSpan);
    }

    const sizeSpan = document.createElement("span");
    sizeSpan.textContent = evt.provider + " · " + (img.size || "");
    meta.appendChild(sizeSpan);

    card.appendChild(imgEl);
    card.appendChild(meta);
    container.appendChild(card);
  });

  scrollToBottom(container);
}

/* findChatLogContainer + scrollToBottom — extracted to chat/chat-send.js */


/* renderCodeBlock — extracted to chat/chat-markdown.js */


/* =================================================================
   TB07: PERSONA PORTRAIT
   ================================================================= */
// EMOTION_COLORS_PORTRAIT — removed; use global EMOTION_COLORS from core/constants.js

async function loadPortrait() {
  if (!S.persona) return;
  const container = document.getElementById("portrait-container");
  const img = document.getElementById("portrait-img");
  const placeholder = document.getElementById("portrait-placeholder");
  const status = document.getElementById("portrait-status");
  if (!container || !img || !placeholder || !status) return;

  status.textContent = "";
  status.className = "";

  try {
    const data = await api("/api/portrait/" + encodeURIComponent(S.persona));
    if (data.image_base64) {
      setPortraitImage(data.image_base64, data.emotion);
    } else if (data.fallback_emoji) {
      placeholder.textContent = data.fallback_emoji;
      placeholder.style.fontSize = "2.5rem";
    }
  } catch (e) {
    console.error("[loadPortrait] failed:", e);
    if (e.message !== "Portrait generation is disabled for this persona") {
      toast("ポートレート読込失敗: " + e.message, "error");
    }
  }
}

function setPortraitImage(base64, emotion) {
  const container = document.getElementById("portrait-container");
  const img = document.getElementById("portrait-img");
  const placeholder = document.getElementById("portrait-placeholder");
  const status = document.getElementById("portrait-status");
  if (!container || !img) return;

  img.src = "data:image/png;base64," + base64;
  img.style.display = "block";
  if (placeholder) placeholder.style.display = "none";
  img.classList.remove("fade-in");
  void img.offsetWidth; // trigger reflow
  img.classList.add("fade-in");
  if (status) {
    status.textContent = "";
    status.className = "";
  }

  // Set emotion border color
  if (emotion && EMOTION_COLORS[emotion]) {
    container.classList.add("has-emotion");
    container.style.setProperty(
      "--portrait-emotion-color",
      EMOTION_COLORS[emotion],
    );
  } else {
    container.classList.remove("has-emotion");
    container.style.removeProperty("--portrait-emotion-color");
  }
}

function onPortraitClick() {
  const img = document.getElementById("portrait-img");
  if (img && img.style.display !== "none" && img.src) {
    openMediaViewer(img.src, "image");
  }
}


/* =================================================================
   TE04: TTS AUDIO PLAYBACK
   ================================================================= */
let _ttsAbortController = null;

/* ── TE04: Voice model loading & test playback ── */
async function loadVoiceModels(selectedId) {
  if (!S.persona) return;
  const select = document.getElementById("chat-voice-model");
  if (!select) return;
  try {
    const resp = await api("/api/tts/" + encodeURIComponent(S.persona) + "/voices");
    if (resp.voices && resp.voices.length > 0) {
      select.innerHTML = "";
      resp.voices.forEach(function (v) {
        var opt = document.createElement("option");
        opt.value = v.id;
        opt.textContent = v.name || v.id;
        select.appendChild(opt);
      });
      // Restore saved selection
      if (selectedId && select.querySelector('option[value="' + selectedId.replace(/"/g, '&quot;') + '"]')) {
        select.value = selectedId;
      }
    } else {
      select.innerHTML = '<option value="">音声モデルが見つかりません</option>';
    }
  } catch (e) {
    console.warn("[Voice] Failed to load models:", e.message);
    select.innerHTML = '<option value="">取得エラー</option>';
  }
}

async function testVoicePlayback() {
  if (!S.persona) return;
  var statusEl = document.getElementById("chat-voice-test-status");
  if (statusEl) statusEl.textContent = "合成中...";
  try {
    var resp = await api("/api/tts/" + encodeURIComponent(S.persona), {
      method: "POST",
      body: JSON.stringify({ text: "こんにちは、テストです。" }),
    });
    if (resp.audio_base64) {
      if (statusEl) statusEl.textContent = "再生中...";
      var audioUrl = "data:audio/" + (resp.format || "wav") + ";base64," + resp.audio_base64;
      var audio = new Audio(audioUrl);
      audio.onended = function () {
        if (statusEl) statusEl.textContent = "完了";
        setTimeout(function () { if (statusEl) statusEl.textContent = ""; }, 2000);
      };
      audio.onerror = function () {
        if (statusEl) statusEl.textContent = "再生エラー";
      };
      audio.play().catch(function (err) {
        console.error("[Voice test] Play failed:", err);
        if (statusEl) statusEl.textContent = "再生エラー: " + err.message;
      });
    } else {
      if (statusEl) statusEl.textContent = "エラー: " + (resp.error || "不明");
    }
  } catch (e) {
    console.error("[Voice test] Error:", e);
    if (statusEl) statusEl.textContent = "エラー: " + e.message;
  }
}

/* ── MCP Tools management ── */
async function fetchMcpTools() {
  if (!S.persona) return;
  const list = document.getElementById("chat-mcp-tools-list");
  if (!list) return;
  list.innerHTML = '<span style="font-size:0.7rem;color:var(--text-muted);">読み込み中...</span>';
  try {
    const data = await api("/api/chat/" + encodeURIComponent(S.persona) + "/mcp-tools");
    CHAT.mcpTools = data.tools || [];
    CHAT.mcpErrors = data.errors || [];
    renderMcpTools();
  } catch (e) {
    list.innerHTML = '<span style="font-size:0.7rem;color:var(--accent-red);">取得失敗: ' + e.message + '</span>';
  }
}

function renderMcpTools() {
  const list = document.getElementById("chat-mcp-tools-list");
  if (!list) return;
  // Clear previous content
  while (list.firstChild) list.removeChild(list.firstChild);
  const tools = CHAT.mcpTools || [];
  if (!tools.length) {
    const span = document.createElement("span");
    span.style.cssText = "font-size:0.7rem;color:var(--text-muted);";
    span.textContent = "ツールがありません";
    list.appendChild(span);
    return;
  }
  if (CHAT.mcpErrors && CHAT.mcpErrors.length > 0) {
    const errDiv = document.createElement("div");
    errDiv.style.cssText = "font-size:0.65rem;color:var(--accent-red);margin-bottom:4px;";
    errDiv.textContent = "⚠ " + CHAT.mcpErrors.join("; ");
    list.appendChild(errDiv);
  }
  for (const tool of tools) {
    const enabled = !CHAT.disabledTools.has(tool.name);
    const shortDesc = (tool.description || "").slice(0, 60) + ((tool.description || "").length > 60 ? "..." : "");

    const row = document.createElement("div");
    row.style.cssText = "display:flex;align-items:center;gap:6px;padding:2px 0;font-size:0.7rem;";

    // Toggle switch
    const label = document.createElement("label");
    label.className = "mcp-tool-toggle";
    label.title = tool.name;
    const input = document.createElement("input");
    input.type = "checkbox";
    input.checked = enabled;
    input.dataset.toolName = tool.name;
    input.addEventListener("change", function() {
      toggleTool(this.dataset.toolName);
    });
    const slider = document.createElement("span");
    slider.className = "mcp-tool-toggle-slider";
    label.appendChild(input);
    label.appendChild(slider);
    row.appendChild(label);

    // Tool name
    const nameSpan = document.createElement("span");
    nameSpan.style.cssText = "font-weight:500;flex-shrink:0;";
    nameSpan.textContent = tool.name;
    row.appendChild(nameSpan);

    // Server badge
    if (tool.server) {
      const badge = document.createElement("span");
      badge.className = "chat-badge";
      badge.style.cssText = "font-size:0.6rem;flex-shrink:0;";
      badge.textContent = tool.server;
      row.appendChild(badge);
    }

    // Description
    const descSpan = document.createElement("span");
    descSpan.style.cssText = "color:var(--text-muted);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;";
    descSpan.textContent = shortDesc;
    row.appendChild(descSpan);

    list.appendChild(row);
  }
}

function toggleTool(toolName) {
  if (!CHAT.disabledTools) CHAT.disabledTools = new Set();
  if (CHAT.disabledTools.has(toolName)) {
    CHAT.disabledTools.delete(toolName);
  } else {
    CHAT.disabledTools.add(toolName);
  }
}

/* loosenJson + formatMcpJson → extracted to chat/chat-settings.js */

// esc() — now provided by core/adapter.js (global alias for Nous.Core.esc)

function autoPlayTts(text) {
  if (!S.persona || !text) return;
  // Strip markdown for TTS
  var plainText = text
    .replace(/```[\s\S]*?```/g, "コードブロック")
    .replace(/`([^`]+)`/g, "$1")
    .replace(/[*_~>#-]/g, "")
    .replace(/\[([^\]]+)\]\([^)]+\)/g, "$1")
    .trim();
  if (!plainText) return;

  api("/api/tts/" + encodeURIComponent(S.persona), {
    method: "POST",
    body: JSON.stringify({ text: plainText }),
  })
    .then(function (resp) {
    if (resp.audio_base64) {
        var audioUrl = "data:audio/" + (resp.format || "wav") + ";base64," + resp.audio_base64;
        var audio = new Audio(audioUrl);
        audio.play().catch(function (err) {
          console.warn("[AutoTTS] Play failed:", err.message);
        });
      }
    })
    .catch(function (e) {
      console.warn("[AutoTTS] Request failed:", e.message);
    });
}

async function playTts(btn, text) {
  if (!S.persona || !text) return;
  // If already playing, stop
  if (btn.classList.contains("playing")) {
    btn.classList.remove("playing");
    btn.innerHTML = '<i data-lucide="volume-2"></i>';
    if (typeof lucide !== "undefined") lucide.createIcons();
    if (_ttsAbortController) {
      _ttsAbortController.abort();
      _ttsAbortController = null;
    }
    return;
  }

  // Strip markdown-like formatting for TTS
  const plainText = text
    .replace(/```[\s\S]*?```/g, "コードブロック")
    .replace(/`([^`]+)`/g, "$1")
    .replace(/[*_~>#-]/g, "")
    .replace(/\[([^\]]+)\]\([^)]+\)/g, "$1")
    .trim();
  if (!plainText) return;

  btn.innerHTML = '<span class="tts-spinner"></span>';
  btn.disabled = true;

  try {
    const resp = await api("/api/tts/" + encodeURIComponent(S.persona), {
      method: "POST",
      body: JSON.stringify({ text: plainText }),
    });
    const audioBase64 = resp.audio_base64;
    if (audioBase64) {
      btn.classList.add("playing");
      btn.innerHTML = '<i data-lucide="volume-2"></i>';
      btn.disabled = false;
      if (typeof lucide !== "undefined") lucide.createIcons();

      const audioUrl =
        "data:audio/" + (resp.format || "wav") + ";base64," + audioBase64;
      const audio = new Audio(audioUrl);
      audio.onended = function () {
        btn.classList.remove("playing");
        btn.innerHTML = '<i data-lucide="volume-2"></i>';
        if (typeof lucide !== "undefined") lucide.createIcons();
      };
      audio.onerror = function () {
        btn.classList.remove("playing");
        btn.innerHTML = '<i data-lucide="volume-2"></i>';
        if (typeof lucide !== "undefined") lucide.createIcons();
        console.error("[TTS] Audio playback error");
      };
      audio.play().catch(function (err) {
        console.error("[TTS] Play failed:", err);
        btn.classList.remove("playing");
        btn.innerHTML = '<i data-lucide="volume-2"></i>';
        if (typeof lucide !== "undefined") lucide.createIcons();
      });
    } else {
      console.warn("[TTS] Synthesis failed:", resp.error || "unknown");
      btn.innerHTML = '<i data-lucide="volume-2"></i>';
      btn.disabled = false;
      if (typeof lucide !== "undefined") lucide.createIcons();
    }
  } catch (e) {
    console.error("[TTS] Request error:", e.message);
    btn.innerHTML = '<i data-lucide="volume-2"></i>';
    btn.disabled = false;
    if (typeof lucide !== "undefined") lucide.createIcons();
  }
}


