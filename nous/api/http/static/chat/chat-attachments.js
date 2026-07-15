;/* =================================================================
   CHAT ATTACHMENTS — File upload, badge rendering, media viewer
   Extracted from chat.js (Phase 3c)
   ================================================================= */
(function(N) {
"use strict";
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
      esc(url) +
      '" width="100%" height="80vh" style="border:none;border-radius:8px;"></iframe>';
  } else if (type === "audio") {
    inner.innerHTML =
      '<audio controls autoplay style="max-width:90vw;"><source src="' +
      esc(url) +
      '" type="' +
      esc(mimeType || "audio/mpeg") +
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

N.Chat.attachments = {
  upload: uploadAttachment,
  openViewer: openMediaViewer,
  closeViewer: closeMediaViewer,
};

window.uploadAttachment = uploadAttachment;
window.openMediaViewer = openMediaViewer;
window.closeMediaViewer = closeMediaViewer;

})(window.Nous);
