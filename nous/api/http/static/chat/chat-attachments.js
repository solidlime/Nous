;/* =================================================================
   CHAT ATTACHMENTS — File upload, badge rendering, media viewer
   Extracted from chat.js (Phase 3c)
   ================================================================= */
(function(N) {
"use strict";
var C = N.Core;
var esc = C.esc, toast = C.toast, safeSetHTML = C.safeSetHTML;
var S = window.S;

var CHAT = N.Chat.state;

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
      // Prevent click propagation to overlay (for future click-to-close)
      promptsDiv.addEventListener("click", function (e) {
        e.stopPropagation();
      });
      inner.appendChild(promptsDiv);
    }
  } else if (type === "video") {
    const vid = document.createElement("video");
    vid.src = url;
    vid.controls = true;
    vid.autoplay = true;
    inner.appendChild(vid);
  } else if (type === "pdf") {
    safeSetHTML(inner,
      '<iframe src="' +
      esc(url) +
      '" width="100%" height="80vh" style="border:none;border-radius:8px;"></iframe>');
  } else if (type === "audio") {
    safeSetHTML(inner,
      '<audio controls autoplay style="max-width:90vw;"><source src="' +
      esc(url) +
      '" type="' +
      esc(mimeType || "audio/mpeg") +
      '"></audio>');
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
    inner.textContent = "";
  }
}

N.Chat.attachments = {
  upload: uploadAttachment,
  openViewer: openMediaViewer,
  closeViewer: closeMediaViewer,
  trigger: triggerFileAttach,
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
