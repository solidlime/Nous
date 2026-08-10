/* =================================================================
   CHAT SETTINGS IMAGE — ComfyUI/LoRA image gen helpers
   Namespace: N.Chat.settings.*
   Depends on: chat-settings.js (S, N.Chat.settings)
   ================================================================= */
;(function(N) {
var C = N.Core;
"use strict";
var S = window.S;

// ------------------------------------------------------------------
// ComfyUI helper functions
// ------------------------------------------------------------------
function updateImageGenSliderLabels() {
  // HTML側の oninput で処理するため、ここでは何もしない（reasoning ラベルのみ同期）
  var reasoningVal = document.getElementById("chat-reasoning-effort-val");
  var reasoningSlider = document.getElementById("chat-reasoning-effort");
  if (reasoningVal && reasoningSlider) {
    var labels = ["low", "medium", "high", "max"];
    reasoningVal.textContent = labels[parseInt(reasoningSlider.value, 10)] || "medium";
  }
}

function testImageGen() {
  var status = document.getElementById('chat-image-test-status');
  if (!status) return;
  status.textContent = '生成中...';
  status.style.color = 'var(--text-muted)';
  
  var payload = {
    width: parseInt(document.getElementById('chat-image-gen-width')?.value || '1024'),
    height: parseInt(document.getElementById('chat-image-gen-height')?.value || '1024'),
    prompt: document.getElementById('chat-image-gen-self-portrait-prompt')?.value.trim() || '',
    negative_prompt: document.getElementById('chat-image-gen-negative-prompt')?.value || '',
  };
  
  fetch('/api/chat/' + (S.persona || '') + '/image-gen/test', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(payload)
  })
  .then(function(r) { return r.json(); })
  .then(function(d) {
    if (d.error) { status.textContent = '\ud83d\udd34 ' + d.error; status.style.color = 'var(--accent-red)'; return; }
    status.textContent = '\u2705 \u751f\u6210\u5b8c\u4e86 (' + (d.images ? d.images.length : 0) + '\u679a)';
    status.style.color = 'var(--accent-green)';
  })
  .catch(function(e) {
    status.textContent = '\ud83d\udd34 ' + e.message;
    status.style.color = 'var(--accent-red)';
  });
}

async function uploadReferenceImage() {
  var fileInput = document.getElementById("chat-image-gen-ref-file");
  var statusEl = document.getElementById("chat-image-gen-ref-status");
  if (!fileInput || !fileInput.files || !fileInput.files.length) {
    if (statusEl) statusEl.textContent = "ファイルを選択してください";
    return;
  }
  var file = fileInput.files[0];
  var persona = window.N?.Chat?.persona || document.querySelector("[data-persona]")?.dataset?.persona || "default";
  var formData = new FormData();
  formData.append("file", file);
  
  var btn = document.getElementById("chat-image-gen-ref-upload-btn");
  if (btn) { btn.disabled = true; btn.innerHTML = "アップロード中..."; }
  if (statusEl) statusEl.textContent = "";
  
  try {
    var resp = await fetch("/api/chat/" + persona + "/image-gen/reference", { method: "POST", body: formData });
    var data = await resp.json();
    if (data.ok) {
      if (statusEl) statusEl.textContent = "\u2713 \u30a2\u30c3\u30d7\u30ed\u30fc\u30c9\u5b8c\u4e86 (" + (data.size / 1024).toFixed(1) + " KB)";
      // Show thumbnail preview after upload
      var thumb = document.getElementById("chat-image-gen-ref-thumb");
      if (thumb) {
        thumb.src = "/api/chat/" + persona + "/persona/images/reference.png?_=" + Date.now();
        thumb.style.display = "block";
      }
    } else {
      if (statusEl) statusEl.textContent = "\u2717 " + (data.error || "\u30a8\u30e9\u30fc");
    }
  } catch (e) {
    if (statusEl) statusEl.textContent = "\u2717 \u901a\u4fe1\u30a8\u30e9\u30fc";
  }
  if (btn) { btn.disabled = false; btn.innerHTML = '<i data-lucide="upload"></i> \u30a2\u30c3\u30d7\u30ed\u30fc\u30c9'; }
}

function checkComfyUIHealth() {
  var url = document.getElementById('chat-image-gen-comfyui-url').value.trim();
  var status = document.getElementById('chat-image-status');
  if (!url) { status.textContent = '⚠ URLを入力してください'; status.style.color = 'var(--accent-yellow)'; return; }
  status.textContent = '確認中...';
  status.style.color = 'var(--text-secondary)';
  var controller = new AbortController();
  var timeoutId = setTimeout(function() { controller.abort(); }, 10000);
  fetch('/api/image-gen/health?url=' + encodeURIComponent(url), { signal: controller.signal })
    .then(function(r) { return r.json(); })
    .then(function(d) {
      clearTimeout(timeoutId);
      if (d.healthy) {
        status.textContent = '🟢 接続OK';
        status.style.color = 'var(--accent-green)';
      } else {
        status.textContent = '🔴 ' + (d.error || '接続失敗');
        status.style.color = 'var(--accent-red)';
      }
    })
    .catch(function(e) {
      clearTimeout(timeoutId);
      status.textContent = '🔴 ' + (e.name === 'AbortError' ? 'タイムアウト' : e.message);
      status.style.color = 'var(--accent-red)';
    });
}

// イベントリスナー初期化 (DOMContentLoaded 安全策)
(function initImageGenEvents() {
  function bind() {
    // ページロード時にComfyUI URLが設定済みなら疎通確認
    if (document.getElementById('chat-image-gen-comfyui-url')?.value) {
      checkComfyUIHealth();
    }
  }
  if (document.readyState !== 'loading') bind();
  else document.addEventListener('DOMContentLoaded', bind);
})();

// ------------------------------------------------------------------
// Register namespace additions
// ------------------------------------------------------------------
N.Chat.settings = N.Chat.settings || {};
Object.assign(N.Chat.settings, {
  checkComfyUI: checkComfyUIHealth,
  updateSliderLabels: updateImageGenSliderLabels,
  testImageGen: testImageGen,
});

// ImageGen sub-namespace for i2i reference upload
N.ImageGen = N.ImageGen || {};
N.ImageGen.uploadReferenceImage = uploadReferenceImage;

})(window.Nous);
