;/* =================================================================
   CHAT ATTACHMENTS — File upload, badge rendering, media viewer
   Extracted from chat.js (Phase 3c)
   ================================================================= */
(function(N) {
"use strict";
var C = N.Core;
var toast = C.toast, safeSetHTML = C.safeSetHTML;
var S = window.S;

var CHAT = N.Chat.state;

var MAX_ATTACHMENT_BYTES =
  (N.Chat.settings && N.Chat.settings.max_attachment_bytes) || 10 * 1024 * 1024;

async function uploadAttachment(file) {
  if (!S.persona) {
    toast("ペルソナを選択してください", "error");
    return;
  }
  if (file && file.size > MAX_ATTACHMENT_BYTES) {
    toast(
      "ファイルが大きすぎます（上限" +
        Math.round(MAX_ATTACHMENT_BYTES / 1048576) +
        "MB）: " +
        (file.name || ""),
      "error"
    );
    return;
  }
  const formData = new FormData();
  formData.append("file", file);
  try {
    const res = await N.Core.api.rawFetch(
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
    img.src = N.Core.auth.sign(att.url);  // #102: img の src はヘッダを送れない
    img.alt = att.filename;
    img.onclick = () => openMediaViewer(att.url, "image");
    badge.appendChild(img);
  } else if (isVideo) {
    const vid = document.createElement("video");
    vid.className = "thumb";
    vid.src = N.Core.auth.sign(att.url);  // #102
    vid.muted = true;
    vid.onclick = () => openMediaViewer(att.url, "video");
    badge.appendChild(vid);
  } else if (isAudio) {
    const icon = document.createElement("span");
    safeSetHTML(icon, '<i data-lucide="volume-2"></i>');
    badge.appendChild(icon);
    badge.style.cursor = "pointer";
    badge.onclick = () => openMediaViewer(att.url, "audio", att.mime_type);
  } else {
    const icon = document.createElement("span");
    const ext = att.filename.split(".").pop().toLowerCase();
    if (ext === "pdf") {
      safeSetHTML(icon, '<i data-lucide="book"></i>');
      badge.appendChild(icon);
      badge.style.cursor = "pointer";
      badge.onclick = () => openMediaViewer(att.url, "pdf");
    } else {
      safeSetHTML(icon,
        ext === "zip" || ext === "tar" || ext === "gz"
          ? '<i data-lucide="package"></i>'
          : '<i data-lucide="file-text"></i>');
      badge.appendChild(icon);
    }
  }

  const nameSpan = document.createElement("span");
  nameSpan.className = "attach-name";
  nameSpan.textContent = att.filename;
  badge.appendChild(nameSpan);

  const removeBtn = document.createElement("button");
  removeBtn.className = "attach-remove";
  safeSetHTML(removeBtn, '<i data-lucide="x"></i>');
  removeBtn.onclick = () => {
    CHAT.attachments = CHAT.attachments.filter(
      (a) => a.filename !== att.filename,
    );
    badge.remove();
  };
  badge.appendChild(removeBtn);
  area.appendChild(badge);
}

function openMediaViewer(url, type, mimeType, data) {
  // #102 review: 前回の open から生きたままの audio/video は要素を外しても鳴り続ける
  innerOfViewer().pauseAll();
  url = N.Core.auth.sign(url);  // #102: img/audio は鍵を URL で受け取る
  const overlay = document.getElementById("media-viewer-overlay");
  const inner = document.getElementById("media-viewer-inner");
  if (!overlay || !inner) return;
  inner.textContent = "";
  if (type === "image") {
    const img = document.createElement("img");
    img.src = url;
    inner.appendChild(img);
      // Prompt info display
      if (data && (data.revised_prompt || data.negative_prompt)) {
        const promptsDiv = document.createElement("div");
        promptsDiv.className = "media-viewer-prompts";
        if (data.revised_prompt) {
          const label = document.createElement("div");
          label.className = "prompt-label";
          label.textContent = "生成プロンプト";
          promptsDiv.appendChild(label);
          const text = document.createElement("div");
          text.className = "prompt-text";
          text.textContent = data.revised_prompt;
          promptsDiv.appendChild(text);
        }
        if (data.negative_prompt) {
          const label = document.createElement("div");
          label.className = "prompt-label";
          label.textContent = "ネガティブプロンプト";
          promptsDiv.appendChild(label);
          const text = document.createElement("div");
          text.className = "prompt-text";
          text.textContent = data.negative_prompt;
          promptsDiv.appendChild(text);
        }
        // Clicks inside content never reach the overlay close handler
        // (delegation.js checks e.target.closest("#media-viewer-inner")).
        inner.appendChild(promptsDiv);
      }
  } else if (type === "video") {
    const vid = document.createElement("video");
    vid.src = url;
    vid.controls = true;
    vid.autoplay = true;
    inner.appendChild(vid);
  } else if (type === "pdf") {
    /* #102 review: middleware が全レスポンスに x-frame-options: DENY +
       frame-ancestors 'none' を付けるため iframe は描画されない（ネットワーク 200
       でもレンダリングが拒否される）。トップレベルの新タブは XFO の対象外なので
       window.open で開く — サーバ変更ゼロで iframe src に鍵を置く攻撃面も消える。 */
    /* #102 review: 添付 URL は same-origin 相対パスが前提 — 外部 URL は
       開かない (open redirect 防護)。 */
    try {
      if (new URL(url, location.href).origin !== location.origin) return;
    } catch { return; }
    // pi-lens-ignore: ast-grep:no-open-redirect-js
    window.open(url, "_blank", "noopener");
    return;
  } else if (type === "audio") {
    /* #102: 同上 — audio/source も DOMPurify ホワイトリスト外。 */
    const audio = document.createElement("audio");
    audio.controls = true;
    audio.autoplay = true;
    audio.style.maxWidth = "90vw";
    const source = document.createElement("source");
    source.src = url;
    source.type = mimeType || "audio/mpeg";
    audio.appendChild(source);
    inner.appendChild(audio);
  } else {
    const vid = document.createElement("video");
    vid.src = url;
    vid.controls = true;
    vid.autoplay = true;
    inner.appendChild(vid);
  }
  overlay.classList.add("visible");
  // Focus the close button so keyboard users can dismiss immediately.
  const closeBtn = overlay.querySelector(".media-viewer-close");
  if (closeBtn) closeBtn.focus();
  // ESC to close (single shared handler — removed on close, no leak)
  if (!openMediaViewer._escHandler) {
    openMediaViewer._escHandler = function (e) {
      if (e.key === "Escape") closeMediaViewer();
    };
  }
  document.removeEventListener("keydown", openMediaViewer._escHandler);
  document.addEventListener("keydown", openMediaViewer._escHandler);
}

function innerOfViewer() {
  const inner = document.getElementById("media-viewer-inner");
  return {
    el: inner,
    pauseAll() {
      if (!inner) return;
      inner.querySelectorAll("audio,video").forEach(function (m) { m.pause(); });
    },
  };
}

function closeMediaViewer() {
  const overlay = document.getElementById("media-viewer-overlay");
  const inner = document.getElementById("media-viewer-inner");
  if (overlay) overlay.classList.remove("visible");
  if (openMediaViewer._escHandler) {
    try { document.removeEventListener("keydown", openMediaViewer._escHandler); } catch {}
  }
  if (inner) {
    // #102 review: audio/video は要素を外しても鳴り続けるので必ず pause してから空にする
    inner.querySelectorAll("audio,video").forEach(function (m) { m.pause(); });
    inner.textContent = "";
  }
}

/* #107: staged-attachment clear, owned here (single source for state +
   badge area). Badges are class-rendered with no id, so wipe the area itself. */
function clearStagedAttachments() {
  CHAT.attachments = [];
  var area = document.getElementById("chat-attachments");
  if (area) area.textContent = "";
}

N.Chat.attachments = {
  upload: uploadAttachment,
  openViewer: openMediaViewer,
  closeViewer: closeMediaViewer,
  trigger: triggerFileAttach,
  clear: clearStagedAttachments,
};

function triggerFileAttach() {
  var input = document.createElement("input");
  input.type = "file";
  input.multiple = true;
  input.accept = "image/*,.pdf,.txt,.json,.csv,.py,.js,.ts,.md,.log,.zip";
  input.style.display = "none";
  input.addEventListener("change", function () {
    var files = Array.from(input.files);
    for (var i = 0; i < files.length; i++) {
      uploadAttachment(files[i]);
    }
    input.remove();
  });
  document.body.appendChild(input);
  input.click();
}

})(window.Nous);
