/* =================================================================
   chat settings save — collect → POST → toast/apply/button state.
   Covers the guards users actually hit (no persona, empty Base URL)
   and the success/failure paths of the 設定を保存 button.
   ================================================================= */
import { loadCore } from '../core/load-core.js';
import { loadFile } from '../core/load-core.js';

let apiStub;
let toastStub;
let applyStub;
let S;

// ids saveChatConfig reads without optional chaining
const REQUIRED = [
  ['input', 'chat-model', 'test-model'],
  ['input', 'chat-base-url', 'https://api.example.com'],
  ['input', 'chat-temperature', '0.7'],
  ['input', 'chat-max-tokens', '8192'],
  ['input', 'chat-stored-msgs', '200'],
  ['input', 'chat-context-max-tokens', ''],
  ['input', 'chat-compression-threshold', '80'],
  ['select', 'chat-compression-mode', 'auto'],
  ['input', 'chat-keep-recent', '2'],
  ['input', 'chat-compress-system', 'true'],
  ['input', 'chat-compress-history', 'true'],
  ['input', 'chat-memory-preload', '5'],
  ['input', 'chat-parallel-tools', 'true'],
  ['textarea', 'chat-system-prompt', ''],
];

function buildForm({ baseUrl = 'https://api.example.com' } = {}) {
  const fields = REQUIRED.map(([tag, id, value]) => {
    if (tag === 'select') return `<select id="${id}"><option value="${value}">${value}</option></select>`;
    if (id === 'chat-compress-system' || id === 'chat-compress-history') {
      return `<input type="checkbox" id="${id}" checked />`;
    }
    if (id === 'chat-base-url') return `<input id="${id}" value="${baseUrl}" />`;
    return `<${tag} id="${id}" value="${value}"></${tag}>`;
  }).join('');
  document.body.innerHTML = `${fields}<button class="chat-save-btn">設定を保存</button>`;
}

beforeAll(() => {
  loadCore();
  window.S = { persona: 'p1' };
  apiStub = vi.fn();
  toastStub = vi.fn();
  applyStub = vi.fn();
  window.Nous.Core.api = apiStub;
  window.Nous.Core.toast = toastStub;
  window.Nous.Chat = {
    state: { enabledSkills: [], disabledTools: new Set() },
    settings: {
      parseMcpJson: () => [],
      BUILTIN_SKILLS: ['search'],
      _defaultOf: () => undefined,
      apply: applyStub,
    },
  };
  // api/toast/apply are captured by save.js at load time
  loadFile('../chat/settings/save.js');
  S = window.S;
});

beforeEach(() => {
  apiStub.mockReset();
  apiStub.mockResolvedValue({ model: 'test-model' });
  toastStub.mockClear();
  applyStub.mockClear();
  S.persona = 'p1';
  buildForm();
});

test('no persona → error toast, no request', async () => {
  S.persona = '';
  await window.Nous.Chat.settings.save();
  expect(toastStub).toHaveBeenCalledWith('ペルソナを選択してください', 'error');
  expect(apiStub).not.toHaveBeenCalled();
});

test('empty Base URL → error toast, no request', async () => {
  buildForm({ baseUrl: '   ' });
  await window.Nous.Chat.settings.save();
  expect(toastStub).toHaveBeenCalledWith('Base URL は必須です', 'error');
  expect(apiStub).not.toHaveBeenCalled();
});

test('success POSTs the collected form, applies the response and restores the button', async () => {
  buildForm();
  await window.Nous.Chat.settings.save();

  const [url, opts] = apiStub.mock.calls[0];
  expect(url).toBe('/api/chat/p1/config');
  expect(opts.method).toBe('POST');
  const payload = JSON.parse(opts.body);
  expect(payload.model).toBe('test-model');
  expect(payload.base_url).toBe('https://api.example.com');
  expect(payload.temperature).toBe(0.7);
  expect(payload.max_tokens).toBe(8192);
  expect(payload.context_max_tokens).toBeNull(); // empty input → null, not NaN
  expect(payload.context_compression_threshold).toBe(0.8); // 80% → 0.8
  expect(payload.top_p).toBeNull(); // top-p disabled
  expect(payload.mcp_servers).toEqual([]);
  expect(payload.enabled_skills).toEqual(['search']);

  expect(applyStub).toHaveBeenCalledWith({ model: 'test-model' });
  expect(toastStub).toHaveBeenCalledWith('チャット設定を保存しました', 'success');
  const btn = document.querySelector('.chat-save-btn');
  expect(btn.disabled).toBe(false);
  expect(btn.textContent).toContain('設定を保存');
});

test('failure shows the error toast, skips apply and re-enables the button', async () => {
  apiStub.mockRejectedValueOnce(new Error('boom'));
  await window.Nous.Chat.settings.save();

  expect(toastStub).toHaveBeenCalledWith('保存失敗: boom', 'error');
  expect(applyStub).not.toHaveBeenCalled();
  const btn = document.querySelector('.chat-save-btn');
  expect(btn.disabled).toBe(false);
  expect(btn.textContent).toContain('設定を保存');
});
