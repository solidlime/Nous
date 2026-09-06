/* =================================================================
   chat-memory-panel regression tests — memoryPanel registration
   (delegation added in b2b02d09 read N.Chat.memoryPanel before it was
   assigned, aborting the IIFE so update/updateReflection never
   registered → chat-core crash + dead panel buttons)
   ================================================================= */
import { readFileSync } from 'fs';
import { resolve, dirname } from 'path';
import { fileURLToPath } from 'url';
import { loadCore } from '../core/load-core.js';

const __dirname = dirname(fileURLToPath(import.meta.url));

function loadChat(file) {
  const code = readFileSync(resolve(__dirname, file), 'utf-8');
  new Function(code)();
}

function ensurePanel() {
  if (!window.Nous.Chat.memoryPanel || typeof window.Nous.Chat.memoryPanel.update !== 'function') {
    loadChat('chat-memory-panel.js');
  }
}

let N;

beforeAll(() => {
  loadCore();
  N = window.Nous;
  window.S = { persona: 'p1' };
  N.Core.toast = N.Core.toast || (() => {});
  N.Core.showConfirm = N.Core.showConfirm || ((msg, cb) => { if (cb) cb(); });
  N.Core.showAlert = N.Core.showAlert || (() => {});
  N.Components.memoryCard = {
    renderEmotionBadges: () => '',
    renderBodyStateCompact: () => '',
  };
});

beforeEach(() => {
  document.body.innerHTML = `
    <div id="memory-panel">
      <div id="reflection-header"></div>
      <div id="memory-retrieved-list"></div>
      <div id="memory-saved-list"></div>
      <div id="memory-goals-list"></div>
      <div id="memory-promises-list"></div>
      <div id="memory-reflection-list"></div>
    </div>`;
});

describe('chat-memory-panel registration', () => {
  it('registers on first load when N.Chat.memoryPanel starts undefined (no _delegated crash)', () => {
    expect(N.Chat.memoryPanel).toBeUndefined();
    expect(() => loadChat('chat-memory-panel.js')).not.toThrow();
    for (const fn of ['update', 'updateReflection', 'sessionSummarized', 'contextCompressed', 'deleteCard', 'completeGoal']) {
      expect(typeof N.Chat.memoryPanel[fn]).toBe('function');
    }
  });

  it('renders goals + reflection without inline onclick (CSP-safe)', () => {
    ensurePanel();
    N.Chat.memoryPanel.update(undefined, undefined, [{ key: 'g1', content: 'goal one', importance: 0.8, tags: [] }]);
    const goals = document.getElementById('memory-goals-list').innerHTML;
    expect(goals).toContain('goal one');
    expect(goals).not.toContain('onclick');
    expect(goals).toContain('data-mem-action="complete"');
    N.Chat.memoryPanel.updateReflection(['insight one']);
    expect(document.getElementById('memory-reflection-list').innerHTML).toContain('insight one');
  });

  it('delegation routes delete/complete clicks, single-bound on double-load', () => {
    ensurePanel();
    loadChat('chat-memory-panel.js');
    loadChat('chat-memory-panel.js'); // double-load must not double-bind
    const del = vi.fn();
    const done = vi.fn();
    N.Chat.memoryPanel.deleteCard = del;
    N.Chat.memoryPanel.completeGoal = done;
    document.getElementById('memory-goals-list').innerHTML =
      '<button type="button" data-mem-action="delete" data-mem-key="g1">削除</button>' +
      '<button type="button" data-mem-action="complete" data-mem-key="g2" data-mem-content="goal two">完了</button>';
    document.querySelector('[data-mem-key="g1"]').dispatchEvent(new window.MouseEvent('click', { bubbles: true }));
    document.querySelector('[data-mem-key="g2"]').dispatchEvent(new window.MouseEvent('click', { bubbles: true }));
    expect(del).toHaveBeenCalledTimes(1);
    expect(del).toHaveBeenCalledWith('g1');
    expect(done).toHaveBeenCalledTimes(1);
    expect(done).toHaveBeenCalledWith('g2', 'goal two');
  });
});

describe('panel detail modals + row delegation', () => {
  let open, openMemory;
  beforeAll(() => {
    ensurePanel();
    // DOMPurify is a browser CDN global, absent in vitest. Identity stub
    // so safeSetHTML builds real DOM (same trick as chat-wiring-feed.test.js).
    globalThis.DOMPurify = { sanitize: (html) => String(html) };
  });
  beforeEach(() => {
    N.Components.memModal = {
      open: open = vi.fn(),
      openMemory: openMemory = vi.fn(),
      close: vi.fn(),
    };
  });

  it('memory row with a complete key opens the unified mem modal by key', () => {
    N.Chat.memoryPanel.update([{ key: 'm1', content: 'fact one', importance: 0.6, tags: [], score: 0.9 }], undefined, undefined, undefined);
    const card = document.querySelector('#memory-retrieved-list .memory-item-card');
    expect(card.getAttribute('data-panel-kind')).toBe('memory');
    card.dispatchEvent(new window.MouseEvent('click', { bubbles: true }));
    expect(open).toHaveBeenCalledWith('m1');
  });

  it('memory row without a key falls back to openMemory(partial)', () => {
    N.Chat.memoryPanel.update(undefined, [{ key: '', content: 'partial fact', importance: 0.4, tags: ['a', 'b'] }], undefined, undefined);
    const card = document.querySelector('#memory-saved-list .memory-item-card');
    card.dispatchEvent(new window.MouseEvent('click', { bubbles: true }));
    expect(open).not.toHaveBeenCalled();
    expect(openMemory).toHaveBeenCalledWith(expect.objectContaining({ content: 'partial fact', importance: 0.4 }));
  });

  it('goal row opens the panel detail modal with 完了/削除 buttons', () => {
    N.Chat.memoryPanel.update(undefined, undefined, [{ key: 'g1', content: 'run the marathon', importance: 0.8, tags: ['goal', 'active'] }], undefined);
    const card = document.querySelector('#memory-goals-list .memory-item-card');
    expect(card.getAttribute('data-panel-kind')).toBe('goal');
    card.dispatchEvent(new window.MouseEvent('click', { bubbles: true }));
    const overlay = document.getElementById('panel-detail-overlay');
    expect(overlay.classList.contains('show')).toBe(true);
    expect(overlay.textContent).toContain('run the marathon');
    expect(overlay.querySelector('[data-mem-action="complete"]')).not.toBeNull();
    expect(overlay.querySelector('[data-mem-action="delete"]')).not.toBeNull();
  });

  it('promise row opens the detail modal (約束 kicker)', () => {
    N.Chat.memoryPanel.update(undefined, undefined, undefined, [{ key: 'p1', content: 'call back tomorrow', importance: 0.8, tags: [] }]);
    const card = document.querySelector('#memory-promises-list .memory-item-card');
    card.dispatchEvent(new window.MouseEvent('click', { bubbles: true }));
    const overlay = document.getElementById('panel-detail-overlay');
    expect(overlay.classList.contains('show')).toBe(true);
    expect(overlay.textContent).toContain('約束');
    expect(overlay.textContent).toContain('call back tomorrow');
  });

  it('complete inside the modal closes it and routes to completeGoal', () => {
    const done = vi.fn();
    N.Chat.memoryPanel.completeGoal = done;
    N.Chat.memoryPanel.update(undefined, undefined, [{ key: 'g1', content: 'run the marathon', importance: 0.8, tags: [] }], undefined);
    document.querySelector('#memory-goals-list .memory-item-card')
      .dispatchEvent(new window.MouseEvent('click', { bubbles: true }));
    document.querySelector('#panel-detail-overlay [data-mem-action="complete"]')
      .dispatchEvent(new window.MouseEvent('click', { bubbles: true }));
    expect(done).toHaveBeenCalledWith('g1', 'run the marathon');
    expect(document.getElementById('panel-detail-overlay').classList.contains('show')).toBe(false);
  });

  it('Escape closes the panel detail modal', () => {
    N.Chat.memoryPanel.update(undefined, undefined, [{ key: 'g1', content: 'run the marathon', importance: 0.8, tags: [] }], undefined);
    document.querySelector('#memory-goals-list .memory-item-card')
      .dispatchEvent(new window.MouseEvent('click', { bubbles: true }));
    document.dispatchEvent(new window.KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
    expect(document.getElementById('panel-detail-overlay').classList.contains('show')).toBe(false);
  });

  it('object insights render content (not [object Object]) and open the memory modal by key', () => {
    N.Chat.memoryPanel.updateReflection([{ content: 'insight body', key: 'r1', created_at: '2026-09-07T10:00:00' }]);
    const row = document.querySelector('#memory-reflection-list .reflection-insight');
    expect(row.textContent).toContain('insight body');
    expect(row.getAttribute('data-panel-kind')).toBe('reflection');
    row.dispatchEvent(new window.MouseEvent('click', { bubbles: true }));
    // Reflections carry a full memory key → unified memModal, not the
    // sparse panel modal (which is goal/promise only).
    expect(open).toHaveBeenCalledWith('r1');
    // Panel modal is goal/promise only — never shown for reflections.
    expect(document.querySelector('#panel-detail-overlay.show')).toBeNull();
  });

  it('keyless reflection insights fall back to openMemory(partial)', () => {
    N.Chat.memoryPanel.updateReflection([{ content: 'no-key insight', key: '', created_at: null }]);
    const row = document.querySelector('#memory-reflection-list .reflection-insight');
    row.dispatchEvent(new window.MouseEvent('click', { bubbles: true }));
    expect(open).not.toHaveBeenCalled();
    expect(openMemory).toHaveBeenCalledWith(expect.objectContaining({ content: 'no-key insight' }));
  });

  it('string insights (legacy format) still render', () => {
    N.Chat.memoryPanel.updateReflection(['legacy insight']);
    expect(document.querySelector('#memory-reflection-list .reflection-insight').textContent)
      .toContain('legacy insight');
  });
});

describe('loadChatCommitments guard', () => {
  it('skips quietly (no toast) when memoryPanel is not registered', async () => {
    N.Core.toast = vi.fn();
    loadChat('chat-core.js');
    const saved = N.Chat.memoryPanel;
    delete N.Chat.memoryPanel;
    try {
      await expect(N.Chat.core.loadCommitments()).resolves.toBeUndefined();
      expect(N.Core.toast).not.toHaveBeenCalled();
    } finally {
      if (saved) N.Chat.memoryPanel = saved;
    }
  });

  it('toasts once and clears reflection when the API fails', async () => {
    const toast = vi.fn();
    N.Core.toast = toast;
    ensurePanel();
    loadChat('chat-core.js');
    const cleared = vi.fn();
    N.Chat.memoryPanel.updateReflection = cleared;
    await N.Chat.core.loadCommitments();
    expect(toast).toHaveBeenCalledTimes(1);
    expect(String(toast.mock.calls[0][0])).toContain('リフレクション読込失敗');
    expect(cleared).toHaveBeenCalledWith([]);
  });
});
