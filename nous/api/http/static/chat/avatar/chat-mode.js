/* =================================================================
   Character chat mode — toggle, avatar lifecycle, SSE wiring,
   VRM model selection/upload UI.
   Consumes the "nous:chat-sse" CustomEvent (detail: {type, data})
   dispatched by chat-send.js. Absent event = no-op, never crashes.
   ================================================================= */

const MODE_KEY = 'nous.chatMode';
const MODEL_KEY = 'nous.avatarModel';
const TALK_IDLE_MS = 2000;
const LOG_RATIO_KEY = 'nous.chat.logRatio';
const LOG_RATIO_MIN = 15;
const LOG_RATIO_MAX = 70;
const LOG_RATIO_DEFAULT = 30;

let avatarHandle = null;      // { setExpression, setTalking, setPose, playGesture, dispose } | null
let talkIdleTimer = null;
let emotionSeenThisTurn = false;

function persona() {
  return (window.S && window.S.persona) || '';
}

function isCharacterMode() {
  return localStorage.getItem(MODE_KEY) === 'character';
}

function modelUrlFor(name) {
  const p = encodeURIComponent(persona());
  if (name) return `/api/chat/${p}/avatar/model?name=${encodeURIComponent(name)}`;
  return `/api/chat/${p}/avatar/model`;
}

/* ── mode switch ─────────────────────────────────────────────── */

async function applyCharacterMode(on) {
  const main = document.getElementById('chat-main');
  const layer = document.getElementById('chat-avatar-layer');
  const btn = document.getElementById('chat-mode-toggle-btn');
  if (btn) btn.title = on ? '通常チャットに戻る' : 'キャラチャットモードに切替';
  if (!main || !layer) return;

  if (on) {
    main.classList.add('character-mode');
    layer.hidden = false;
    ensureStageUi();
    applyLogRatio(readLogRatio(), false);
    if (!avatarHandle) {
      try {
        const mod = await import('./avatar.js');
        const container = document.getElementById('chat-avatar-canvas-container');
        const saved = localStorage.getItem(MODEL_KEY) || '';
        avatarHandle = await mod.initAvatar(container, modelUrlFor(saved));
        // 検証・デバッグ用フック（本番動作には影響なし）
        window.__avatarDebug = avatarHandle;
        refreshModelList();
        populateExpressionSelect();
      } catch (e) {
        console.warn('[chat-mode] avatar init failed:', e);
      }
    }
  } else {
    main.classList.remove('character-mode');
    layer.hidden = true;
    resetStageUiExpression();
    if (avatarHandle) {
      try { avatarHandle.dispose(); } catch (e) { console.warn('[chat-mode] dispose failed:', e); }
      avatarHandle = null;
    }
  }
}

export function toggleCharacterMode() {
  const on = !isCharacterMode();
  localStorage.setItem(MODE_KEY, on ? 'character' : 'normal');
  return applyCharacterMode(on);
}

/* ── SSE consumption (nous:chat-sse, detail: {type, data}) ──── */

const EMOTION_MAP = {
  joy: 'happy',
  love: 'happy',
  happiness: 'happy',
  sadness: 'sad',
  anger: 'angry',
  angry: 'angry',
  surprise: 'surprised',
  surprised: 'surprised',
  fear: 'surprised',
  relaxed: 'relaxed',
  calm: 'relaxed',
  neutral: 'neutral',
};

// 感情→ジェスチャー（応答完了時に一度きり再生）
const EMOTION_GESTURE = {
  happy: 'bounce',
  surprised: 'shake',
  sad: 'nod',
};

function applyEmotion(raw, weight) {
  const mapped = EMOTION_MAP[String(raw || '').toLowerCase()] || 'neutral';
  if (avatarHandle) avatarHandle.setExpression(mapped, weight);
  return mapped;
}

export function handleChatSse(type, data) {
  if (!avatarHandle) return;
  if (type === 'turn_started') {
    emotionSeenThisTurn = false;
    avatarHandle.playGesture('wave'); // 挨拶
  } else if (type === 'text_delta') {
    avatarHandle.setTalking(true);
    clearTimeout(talkIdleTimer);
    talkIdleTimer = setTimeout(() => avatarHandle && avatarHandle.setTalking(false), TALK_IDLE_MS);
  } else if (type === 'context_update') {
    // ペルソナ状態更新のライブ通知（update.emotion）を表情へ反映
    const emotion = data && data.update && data.update.emotion;
    if (emotion) {
      emotionSeenThisTurn = true;
      const mapped = applyEmotion(emotion, 0.7);
      const g = EMOTION_GESTURE[mapped];
      if (g) avatarHandle.playGesture(g);
    }
  } else if (type === 'response_replaced') {
    // 修復が走った → 驚きの表情で反応（次の context_update で上書き）
    avatarHandle.setExpression('surprised', 0.6);
    avatarHandle.playGesture('shake');
  } else if (type === 'done') {
    clearTimeout(talkIdleTimer);
    avatarHandle.setTalking(false);
    if (!emotionSeenThisTurn) fetchEmotionAndApply(); // フォールバック
  } else if (type === 'error') {
    clearTimeout(talkIdleTimer);
    avatarHandle.setTalking(false);
  }
}

async function fetchEmotionAndApply() {
  try {
    // 既存ペルソナ状態API（dashboard集約の context.emotion）から感情を取得
    const p = encodeURIComponent(persona());
    const res = await fetch(`/api/dashboard/${p}`);
    if (!res.ok) return;
    const json = await res.json();
    const raw = String((json.context && json.context.emotion) || 'neutral');
    applyEmotion(raw, 0.7);
  } catch (e) {
    console.debug('[chat-mode] emotion fetch skipped:', e);
  }
}

/* ── VRM model selection / upload ────────────────────────────── */

async function refreshModelList() {
  const select = document.getElementById('chat-avatar-model-select');
  if (!select) return;
  try {
    const p = encodeURIComponent(persona());
    const res = await fetch(`/api/chat/${p}/avatar/models`);
    if (!res.ok) return;
    const json = await res.json();
    const models = Array.isArray(json.models) ? json.models : [];
    const defaultName = (json && json.default) || 'sample.vrm';
    select.innerHTML = '';
    const optDefault = document.createElement('option');
    optDefault.value = '';
    optDefault.textContent = `${defaultName} (default)`;
    select.appendChild(optDefault);
    for (const name of models) {
      const opt = document.createElement('option');
      opt.value = name;
      opt.textContent = name;
      select.appendChild(opt);
    }
    const saved = localStorage.getItem(MODEL_KEY) || '';
    if (models.includes(saved)) select.value = saved;
  } catch (e) {
    console.debug('[chat-mode] model list refresh failed:', e);
  }
}

async function onModelSelected() {
  const select = document.getElementById('chat-avatar-model-select');
  if (!select) return;
  const name = select.value;
  if (name) localStorage.setItem(MODEL_KEY, name);
  else localStorage.removeItem(MODEL_KEY);
  // アバター再ロード
  if (avatarHandle) {
    try { avatarHandle.dispose(); } catch { /* noop */ }
    avatarHandle = null;
  }
  await applyCharacterMode(true);
}

async function onUpload(file) {
  if (!file || !file.name.toLowerCase().endsWith('.vrm')) {
    window.Nous?.Core?.toast?.('VRMファイル (.vrm) のみアップロードできます', 'error');
    return;
  }
  try {
    const p = encodeURIComponent(persona());
    const form = new FormData();
    form.append('file', file, file.name);
    const res = await fetch(`/api/chat/${p}/avatar/model`, { method: 'POST', body: form });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      window.Nous?.Core?.toast?.(err.error || 'アップロードに失敗しました', 'error');
      return;
    }
    const json = await res.json();
    localStorage.setItem(MODEL_KEY, json.filename);
    await refreshModelList();
    const select = document.getElementById('chat-avatar-model-select');
    if (select) select.value = json.filename;
    // アップロードしたモデルへ切替
    if (avatarHandle) {
      try { avatarHandle.dispose(); } catch { /* noop */ }
      avatarHandle = null;
    }
    await applyCharacterMode(true);
  } catch (e) {
    console.warn('[chat-mode] upload failed:', e);
  }
}

/* ── stage UI: log ratio slider + expression picker（DOM 注入）── */

function clampLogRatio(v) {
  return Math.min(LOG_RATIO_MAX, Math.max(LOG_RATIO_MIN, v));
}

function readLogRatio() {
  const raw = localStorage.getItem(LOG_RATIO_KEY);
  if (raw === null) return LOG_RATIO_DEFAULT;
  const v = Number(raw);
  if (!Number.isFinite(v)) return LOG_RATIO_DEFAULT;
  return clampLogRatio(v);
}

function applyLogRatio(percent, save = true) {
  const v = clampLogRatio(Number(percent));
  const main = document.getElementById('chat-main');
  if (main) main.style.setProperty('--chat-log-h', v + '%');
  const slider = document.getElementById('chat-log-ratio');
  const label = document.getElementById('chat-log-ratio-value');
  if (slider) slider.value = String(v);
  if (label) label.textContent = v + '%';
  if (save) localStorage.setItem(LOG_RATIO_KEY, String(v));
  return v;
}

function ensureStageUi() {
  const stage = document.getElementById('chat-avatar-stage-ui');
  if (!stage) return;
  if (document.getElementById('chat-log-ratio')) return; // 既に注入済み
  const row = (labelText, el) => {
    const div = document.createElement('div');
    div.className = 'chat-stage-row';
    const label = document.createElement('label');
    label.textContent = labelText;
    label.htmlFor = el.id;
    div.appendChild(label);
    div.appendChild(el);
    return div;
  };
  const logSlider = document.createElement('input');
  logSlider.type = 'range';
  logSlider.id = 'chat-log-ratio';
  logSlider.min = String(LOG_RATIO_MIN);
  logSlider.max = String(LOG_RATIO_MAX);
  logSlider.step = '1';
  logSlider.value = String(LOG_RATIO_DEFAULT);
  const logLabel = document.createElement('span');
  logLabel.id = 'chat-log-ratio-value';
  logLabel.textContent = LOG_RATIO_DEFAULT + '%';
  const exprSelect = document.createElement('select');
  exprSelect.id = 'chat-avatar-expression';
  exprSelect.disabled = true;
  const weightSlider = document.createElement('input');
  weightSlider.type = 'range';
  weightSlider.id = 'chat-avatar-expression-weight';
  weightSlider.min = '0';
  weightSlider.max = '1';
  weightSlider.step = '0.05';
  weightSlider.value = '1';
  stage.appendChild(row('ログ高さ', logSlider));
  stage.querySelector('.chat-stage-row').appendChild(logLabel);
  stage.appendChild(row('表情', exprSelect));
  stage.appendChild(row('強さ', weightSlider));
  logSlider.addEventListener('input', () => {
    applyLogRatio(Number(logSlider.value));
  });
  exprSelect.addEventListener('change', onExpressionChange);
  weightSlider.addEventListener('input', onExpressionChange);
}

function onExpressionChange() {
  const select = document.getElementById('chat-avatar-expression');
  const weight = document.getElementById('chat-avatar-expression-weight');
  if (!select || !weight || !avatarHandle) return;
  avatarHandle.setExpression(select.value || 'neutral', Number(weight.value));
}

function populateExpressionSelect() {
  const select = document.getElementById('chat-avatar-expression');
  if (!select) return;
  select.innerHTML = '';
  const none = document.createElement('option');
  none.value = 'neutral';
  none.textContent = 'なし';
  select.appendChild(none);
  select.disabled = true;
  if (!avatarHandle || typeof avatarHandle.listExpressions !== 'function') return;
  try {
    const groups = avatarHandle.listExpressions();
    const defs = [['emotions', '表情'], ['mouths', '口'], ['other', 'その他']];
    for (const [key, label] of defs) {
      const names = Array.isArray(groups && groups[key]) ? groups[key] : [];
      const items = names.filter((n) => n && n !== 'neutral');
      if (!items.length) continue;
      const og = document.createElement('optgroup');
      og.label = label;
      for (const n of items) {
        const opt = document.createElement('option');
        opt.value = n;
        opt.textContent = n;
        og.appendChild(opt);
      }
      select.appendChild(og);
    }
    select.disabled = false;
  } catch (e) {
    console.warn('[chat-mode] listExpressions failed:', e);
  }
}

function resetStageUiExpression() {
  const select = document.getElementById('chat-avatar-expression');
  const weight = document.getElementById('chat-avatar-expression-weight');
  if (select) select.value = 'neutral';
  if (weight) weight.value = '1';
}

/* ── DOM wiring ──────────────────────────────────────────────── */

export function initChatMode() {
  const btn = document.getElementById('chat-mode-toggle-btn');
  if (btn) btn.addEventListener('click', () => { toggleCharacterMode(); });

  const select = document.getElementById('chat-avatar-model-select');
  if (select) select.addEventListener('change', () => { onModelSelected(); });

  const uploadInput = document.getElementById('chat-avatar-upload');
  const uploadBtn = document.getElementById('chat-avatar-upload-btn');
  if (uploadInput && uploadBtn) {
    uploadBtn.addEventListener('click', () => uploadInput.click());
    uploadInput.addEventListener('change', () => {
      const f = uploadInput.files && uploadInput.files[0];
      if (f) onUpload(f);
      uploadInput.value = '';
    });
  }

  // SSE イベント（chat-send.js が発火。未実装環境では何も来ない＝無害）
  document.addEventListener('nous:chat-sse', (e) => {
    const detail = e && e.detail;
    if (detail && detail.type) handleChatSse(detail.type, detail.data);
  });

  // 初期状態の復元
  if (isCharacterMode()) applyCharacterMode(true);
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', initChatMode);
} else {
  initChatMode();
}
