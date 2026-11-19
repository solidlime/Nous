/* =================================================================
   settings-save tests — builtin preset drift warning
   BUILTIN_PROFILES は直書きのまま残す（撤去しない）。適用値がサーバ既定
   （GET /api/settings 応答の default_value）と食い違うときだけ警告する。
   ================================================================= */
import { loadCore, loadFile } from '../../core/load-core.js';

let apiStub, toastStub, confirmStub, S, FS;

beforeAll(() => {
  loadCore();
  S = {};
  window.S = S;
  apiStub = vi.fn(async () => ({ success: true }));
  toastStub = vi.fn();
  confirmStub = vi.fn(() => true);
  globalThis.confirm = confirmStub;
  globalThis.N = window.Nous; // settings-save.js は bare N を参照する
  window.Nous.Core.api = apiStub;
  window.Nous.Core.toast = toastStub;
  window.Nous.Core.safeSetHTML = window.Nous.Core.safeSetHTML;
  loadFile('../features/settings/settings-save.js');
  FS = window.Nous.Features.Settings;
  FS.loadSettings = () => {}; // 再読込タイマーの呼び先（このテストでは不要）
});

beforeEach(() => {
  apiStub.mockClear();
  toastStub.mockClear();
  confirmStub.mockClear();
  confirmStub.mockReturnValue(true);
  clearInterval(S.statusPoll);
  S.statusPoll = null;
  S.settingsData = {
    server: { port: { value: 26262, default_value: 26262 } },
    general: { log_level: { value: 'INFO', default_value: 'INFO' } },
    embedding: { device: { value: 'cpu', default_value: 'cpu' } },
  };
});

afterEach(() => {
  clearInterval(S.statusPoll);
  S.statusPoll = null;
});

it('builtin プリセットがサーバ既定と違う値を持つとき警告する', async () => {
  await FS.loadSettingsProfile('Development', FS.BUILTIN_PROFILES.Development);
  const msg = confirmStub.mock.calls[0][0];
  expect(msg).toContain('サーバ既定値と異なる');
  expect(msg).toContain('general.log_level');
  // 既定と一致する項目は挙げない
  expect(msg).not.toContain('server.port');
});

it('ドリフトが無ければ従来どおりの確認文だけ出す', async () => {
  S.settingsData.general.log_level.default_value = 'DEBUG';
  S.settingsData.embedding.device.default_value = 'cpu';
  S.settingsData.server.port.default_value = 26262;
  const p = { embedding: { device: 'cpu' }, general: { log_level: 'DEBUG' } };
  await FS.loadSettingsProfile('p', p);
  const msg = confirmStub.mock.calls[0][0];
  expect(msg).not.toContain('サーバ既定値と異なる');
});

it('再起動が要るカテゴリを含むプリセットは再読込ポーリングを開始する', async () => {
  await FS.loadSettingsProfile('Development', FS.BUILTIN_PROFILES.Development);
  expect(S.statusPoll).not.toBeNull();
});
