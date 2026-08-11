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
  var result = document.getElementById('chat-image-test-result');
  if (result) result.style.display = 'none';
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
    if (d.images && d.images.length && d.images[0].base64 && result) {
      var img = document.getElementById('chat-image-test-img');
      if (img) {
        img.src = 'data:image/png;base64,' + d.images[0].base64;
        result.style.display = 'block';
      }
    }
  })
  .catch(function(e) {
    status.textContent = '\ud83d\udd34 ' + e.message;
    status.style.color = 'var(--accent-red)';
  });
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

})(window.Nous);
