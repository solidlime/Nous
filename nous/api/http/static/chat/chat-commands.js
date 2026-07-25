;/* =================================================================
   CHAT COMMANDS — Slash command definitions + popup UI
   Extracted from chat.js (Phase 3c)
   ================================================================= */
(function(N) {
"use strict";
var C = N.Core;
var api = C.api, esc = C.esc, toast = C.toast, safeSetHTML = C.safeSetHTML;
var appendChatMessage = N.Chat.ui && N.Chat.ui.append;
var showTypingIndicator = N.Chat.ui && N.Chat.ui.showTyping;
var removeTypingIndicator = N.Chat.ui && N.Chat.ui.removeTyping;
var S = window.S;

/* ---- Slash command definitions ---- */
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
  msg += "`Enter` — 改行 / `Shift+Enter` — 送信\n";
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
    safeSetHTML(item,
      '<span class="cmd-name">' +
      cmd.name +
      '</span><span class="cmd-desc">' +
      cmd.desc +
      "</span>");
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

N.Chat.commands = {
  SLASH_COMMANDS: SLASH_COMMANDS,
  show: showHelpCommand,
  popup: showCommandPopup,
  hide: hideCommandPopup,
  handle: handleSlashCommand,
  updateSlashSelection: updateSlashSelection,
};

})(window.Nous);
