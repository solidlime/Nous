/* base.test.js — persona ブート経路の挙動保証 (回帰: 265cdfb4)。
   265cdfb4 は getStoredPersona() を「未使用」と誤判定して削除したが、
   init() が personas>0 のパスで呼び続けていたため実行時 ReferenceError
   （既存の網はソース文字列の in 検査のみ）。
   ここでは base.js 全体を jsdom 上で実行し、文字列一致でなく
   ブート挙動（保存 persona 復元・catch/toast 不発・SSE 接続）で検証する。 */
import { readFileSync } from 'fs';
import { resolve, dirname } from 'path';
import { fileURLToPath } from 'url';
import { loadCore, loadStore } from './core/load-core.js';

const __dirname = dirname(fileURLToPath(import.meta.url));

beforeAll(() => {
  loadCore();
});

beforeEach(() => {
  loadStore();
  localStorage.clear();
  localStorage.setItem('mmcp-persona', 'herta');
  document.body.innerHTML =
    '<div class="tab-bar"></div><div id="main-content"></div>' +
    '<div id="overview-content"></div>' +
    '<select id="persona-select"></select>' +
    '<button id="dark-toggle"></button>' +
    '<button id="create-persona-btn"></button>' +
    '<button id="create-persona-cancel"></button>' +
    '<form id="create-persona-form"></form>' +
    '<button id="delete-persona-btn"></button>' +
    '<button id="hamburger-btn"></button>' +
    '<button id="nav-drawer-close"></button>' +
    '<div id="mem-modal-overlay"></div>' +
    '<div id="shortcut-help-overlay"><button id="shortcut-help-close-btn"></button></div>';
});

it('boots without ReferenceError and restores the saved persona', async () => {
  const C = window.Nous.Core;
  C.api = vi.fn(async () => ({ personas: ['herta', 'ruan'] }));
  C.applyTheme = vi.fn();
  C.connectSSE = vi.fn();
  C.toast = vi.fn();
  window.Nous.Components = { skeleton: { show: vi.fn(), hide: vi.fn() } };
  window.Nous.Features = { Overview: { loadOverview: vi.fn(async () => {}) } };

  const code = readFileSync(resolve(__dirname, 'base.js'), 'utf-8');
  new Function(code)(); // jsdom readyState is 'complete' → init() runs now

  await vi.waitFor(() => {
    expect(document.getElementById('persona-select').value).toBe('herta');
  });

  // getStoredPersona() 誤削除時は ReferenceError → catch → toast('Failed to load personas: …')
  expect(C.toast).not.toHaveBeenCalled();
  expect(C.connectSSE).toHaveBeenCalledWith('herta');
  expect(window.Nous.Features.Overview.loadOverview).toHaveBeenCalled();
});
