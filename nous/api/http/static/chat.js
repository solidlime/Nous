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

/* appendToolEvent — extracted to chat/chat-tools.js */


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

/* handleFileToolCall + execCodeBlock — extracted to chat/chat-tools.js */


/* _imageGenSpinnerId + showImageGenSpinner + showImageGenResult — extracted to chat/chat-tools.js */


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

/* fetchMcpTools + renderMcpTools + toggleTool — extracted to chat/chat-tools.js */


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


