/* =================================================================
   CHAT SETTINGS IMAGE — ComfyUI/LoRA image gen helpers
   Namespace: N.Chat.settings.*
   Depends on: chat-settings.js (S, N.Chat.settings)
   ================================================================= */
;(function(N) {
var C = N.Core;
var safeSetHTML = C.safeSetHTML;
"use strict";
var S = window.S;

// ------------------------------------------------------------------
// ComfyUI helper functions
// ------------------------------------------------------------------
function addLoraRow(path, weight) {
  var container = document.getElementById('chat-image-gen-lora-list');
  if (!container) return;
  var div = document.createElement('div');
  div.style.cssText = 'display:flex;gap:4px;align-items:center;';
  safeSetHTML(div, '<input type="text" class="chat-field-input lora-path" value="' + escHtml(path || '') + '" placeholder="lora.safetensors" style="flex:1;font-size:0.82rem;">'
    + '<input type="number" class="chat-field-input lora-weight" value="' + (weight ?? 1.0).toFixed(1) + '" min="0.1" max="2.0" step="0.1" style="width:55px;font-size:0.82rem;">'
    + '<button type="button" class="lora-delete-btn" style="color:var(--accent-red);background:none;border:none;cursor:pointer;font-size:1rem;">\u00d7</button>');
  div.querySelector('.lora-delete-btn').addEventListener('click', function() { div.remove(); });
  container.appendChild(div);
}

function collectLoraRows() {
  var container = document.getElementById('chat-image-gen-lora-list');
  if (!container) return [];
  var result = [];
  container.querySelectorAll('.lora-path').forEach(function(input, i) {
    var path = input.value.trim();
    if (path) {
      var weightEl = container.querySelectorAll('.lora-weight')[i];
      result.push({path: path, weight: parseFloat(weightEl ? weightEl.value : 1.0)});
    }
  });
  return result;
}

function updateImageGenSliderLabels() {
  // HTML側の oninput で処理するため、ここでは何もしない
}

function testImageGen() {
  var status = document.getElementById('chat-image-test-status');
  if (!status) return;
  status.textContent = '生成中...';
  status.style.color = 'var(--text-muted)';
  
  var payload = {
    checkpoint: document.getElementById('chat-image-gen-checkpoint')?.value || '',
    loras: collectLoraRows(),
    width: parseInt(document.getElementById('chat-image-gen-width')?.value || '1024'),
    height: parseInt(document.getElementById('chat-image-gen-height')?.value || '1024'),
    steps: parseInt(document.getElementById('chat-image-gen-steps')?.value || '28'),
    cfg: parseFloat(document.getElementById('chat-image-gen-cfg')?.value || '5.5'),
    sampler: document.getElementById('chat-image-gen-sampler')?.value || 'euler_ancestral',
    scheduler: document.getElementById('chat-image-gen-scheduler')?.value || 'normal',
    seed: parseInt(document.getElementById('chat-image-gen-seed')?.value || '0'),
    denoise: parseFloat(document.getElementById('chat-image-gen-denoise')?.value || '0.7'),
    prompt: document.getElementById('chat-image-gen-self-portrait-prompt')?.value.trim() || '1girl, herta, honkai star rail, solo, smile',
    negative_prompt: 'lowres, bad anatomy, bad hands, text, error',
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

function escHtml(s) {
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

// イベントリスナー初期化 (DOMContentLoaded 安全策)
(function initImageGenEvents() {
  function bind() {
    var addBtn = document.getElementById('chat-image-gen-lora-add');
    if (addBtn && !addBtn._bound) {
      addBtn._bound = true;
      addBtn.addEventListener('click', function() { addLoraRow('', 1.0); });
    }
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
  addLoraRow: addLoraRow,
  collectLoraRows: collectLoraRows,
});

// ImageGen sub-namespace for i2i reference upload
N.ImageGen = N.ImageGen || {};
N.ImageGen.uploadReferenceImage = uploadReferenceImage;

})(window.Nous);
