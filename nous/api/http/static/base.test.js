/* base.test.js — persona ブート経路の挙動保証 (回帰: 265cdfb4)。
   265cdfb4 は getStoredPersona() を「未使用」と誤判定して削除したが、
   init() が personas>0 のパスで呼び続けていたため実行時 ReferenceError
   （既存の網はソース文字列の in 検査のみ）。
   ここでは base.js 全体を jsdom 上で実行し、文字列一致でなく
   ブート挙動（保存 persona 復元・catch/toast 不発・SSE 接続）で検証する。 */
import { loadCore, loadFile, loadStore } from './core/load-core.js';

beforeAll(() => {
  loadCore();
});

beforeEach(() => {
  loadStore();
  localStorage.clear();
  localStorage.setItem('mmcp-persona', 'herta');
  document.body.innerHTML =
    '<div class="tab-bar">' +
    // SSR nav (dashboard.py render_nav) — data-* wiring as of #93
    '<button class="tab-btn" data-tab="overview" data-loader="Nous.Features.Overview.loadOverview"></button>' +
    '<button class="tab-btn" data-tab="memories" data-loader="Nous.Features.Memories.loadMemories"></button>' +
    '<button class="tab-btn" data-tab="activity" data-loader="Nous.Features.Activity.loadActivity" data-loader-args="[true]" data-self-managed="true"></button>' +
    '</div><div class="header-controls"></div><div id="main-content"></div>' +
    '<div id="tab-overview" class="tab-panel active"><div id="overview-content"></div></div>' +
    '<div id="tab-memories" class="tab-panel"><div id="memories-content"></div></div>' +
    '<div id="tab-activity" class="tab-panel"><div id="activity-content"></div></div>' +
    '<select id="persona-select"></select>' +
    '<button id="dark-toggle"></button>' +
    '<button id="create-persona-btn"></button>' +
    '<div id="create-persona-modal"><button id="create-persona-cancel"></button></div>' +
    '<form id="create-persona-form"></form>' +
    '<button id="delete-persona-btn"></button>' +
    '<div id="mem-modal-overlay"></div>' +
    '<div id="shortcut-help-overlay"><button id="shortcut-help-close-btn"></button></div>';
});

it('boots without ReferenceError and restores the saved persona', async () => {
  const C = window.Nous.Core;
  // personas[0]='ruan' ≠ saved 'herta': 復元経路だけが 'herta' を選び得る。
  // (getStoredPersona() が壊れたら fallback 'ruan' になりアサーションが赤になる)
  C.api = vi.fn(async () => ({ personas: ['ruan', 'herta'] }));
  C.applyTheme = vi.fn();
  C.connectSSE = vi.fn();
  C.toast = vi.fn();
  window.Nous.Components = { skeleton: { show: vi.fn(), hide: vi.fn() } };
  window.Nous.Features = { Overview: { loadOverview: vi.fn(async () => {}) } };

  loadFile('../base.js'); // jsdom readyState is 'complete' → init() runs now

  await vi.waitFor(() => {
    expect(document.getElementById('persona-select').value).toBe('herta');
  });

  // getStoredPersona() 誤削除時は ReferenceError → catch → toast('Failed to load personas: …')
  expect(C.toast).not.toHaveBeenCalled();
  expect(C.connectSSE).toHaveBeenCalledWith('herta');
  expect(window.Nous.Features.Overview.loadOverview).toHaveBeenCalled();
});

it('loads a tab via its data-loader attributes with args (#93)', async () => {
  const C = window.Nous.Core;
  C.api = vi.fn(async () => ({ personas: ['ruan', 'herta'] }));
  C.applyTheme = vi.fn();
  C.connectSSE = vi.fn();
  C.toast = vi.fn();
  window.Nous.Components = { skeleton: { show: vi.fn(), hide: vi.fn() } };
  window.Nous.Features = {
    Overview: { loadOverview: vi.fn(async () => {}) },
    Memories: { loadMemories: vi.fn() },
  };

  loadFile('../base.js');
  await vi.waitFor(() =>
    expect(document.getElementById('persona-select').value).toBe('herta')
  );

  // switchTab → loadTab resolves data-loader and applies data-loader-args
  // (memories has no args — call arity must stay 0, like SSR)
  C.switchTab('memories');
  expect(window.Nous.Features.Memories.loadMemories).toHaveBeenCalledWith();
  // activity carries a complete JSON array ([true]) → parsed args
  window.Nous.Features.Activity = { loadActivity: vi.fn() };
  C.switchTab('activity');
  expect(window.Nous.Features.Activity.loadActivity).toHaveBeenCalledWith(true);
});

it('keeps wiring alive with 0 personas and shows guidance, not skeletons (#93)', async () => {
  const C = window.Nous.Core;
  C.api = vi.fn(async () => ({ personas: [] }));
  C.applyTheme = vi.fn();
  C.connectSSE = vi.fn();
  C.toast = vi.fn();
  window.Nous.Components = {
    skeleton: {
      show: vi.fn(),
      hide: vi.fn(),
      emptyState: (_icon, title) => '<div class="empty-state">' + title + '</div>',
      panelContentEl: (tabId) =>
        document.querySelector('#tab-' + tabId + ' > [id$="-content"]'),
    },
  };
  window.Nous.Features = { Memories: { loadMemories: vi.fn() } };

  loadFile('../base.js');
  await vi.waitFor(() =>
    expect(typeof document.getElementById('create-persona-btn').onclick).toBe('function')
  );

  // #93: no early return — modal bindings and keyboard wiring stay alive
  expect(C.toast).not.toHaveBeenCalled();
  expect(typeof document.getElementById('create-persona-cancel').onclick).toBe('function');
  // overview shows guidance (not “No personas found” raw HTML)
  expect(document.getElementById('overview-content').innerHTML).toContain('ペルソナがありません');

  // switching tabs with no persona draws guidance instead of leaving the
  // skeleton up forever (loadTab early return used to reproduce #91)
  C.switchTab('memories');
  expect(document.getElementById('memories-content').innerHTML).toContain('ペルソナがありません');
  expect(window.Nous.Features.Memories.loadMemories).not.toHaveBeenCalled();
  // self-managed panels without a -content child (activity) must be left
  // untouched — renderNoPersona used to replace the panel root and
  // destroy #act-feed until reload
  document.getElementById('tab-activity').innerHTML = '<div id="act-feed"></div>';
  C.switchTab('activity');
  expect(document.getElementById('act-feed')).not.toBeNull();
});

it('falls back to the overview tab for an unknown stored tab (#93)', async () => {
  localStorage.setItem('mmcp-tab', 'bogus');
  const C = window.Nous.Core;
  C.api = vi.fn(async () => ({ personas: ['ruan', 'herta'] }));
  C.applyTheme = vi.fn();
  C.connectSSE = vi.fn();
  C.toast = vi.fn();
  window.Nous.Components = { skeleton: { show: vi.fn(), hide: vi.fn() } };
  window.Nous.Features = { Overview: { loadOverview: vi.fn(async () => {}) } };

  loadFile('../base.js');
  await vi.waitFor(() =>
    expect(document.getElementById('persona-select').value).toBe('herta')
  );

  // boot already loaded overview for the stored 'bogus' tab — clear the
  // mock so the fallback below proves exactly one reload
  window.Nous.Features.Overview.loadOverview.mockClear();
  C.switchTab('bogus');
  expect(document.querySelector('.tab-panel.active').id).toBe('tab-overview');
  expect(window.Nous.Features.Overview.loadOverview).toHaveBeenCalledTimes(1);
});
