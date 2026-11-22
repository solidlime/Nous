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

// chat-memory-panel.js split into memory-panel/*.js — load chunks in
// order (reader path only; test logic unchanged).
const MEMORY_PANEL_CHUNKS = [
  'memory-panel/panel.js',
  'memory-panel/wiring.js',
  'memory-panel/wiring-stream.js',
  'memory-panel/wiring-detail.js',
  'memory-panel/detail.js',
];
function loadMemoryPanel() {
  for (const f of MEMORY_PANEL_CHUNKS) loadChat(f);
}

function ensurePanel() {
  if (!window.Nous.Chat.memoryPanel || typeof window.Nous.Chat.memoryPanel.update !== 'function') {
    loadMemoryPanel();
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
      <div id="memory-reflection-list"></div>
    </div>`;
});

describe('chat-memory-panel registration', () => {
  it('registers on first load when N.Chat.memoryPanel starts undefined (no _delegated crash)', () => {
    expect(N.Chat.memoryPanel).toBeUndefined();
    expect(() => loadMemoryPanel()).not.toThrow();
    for (const fn of ['update', 'updateReflection', 'sessionSummarized', 'contextCompressed', 'deleteCard']) {
      expect(typeof N.Chat.memoryPanel[fn]).toBe('function');
    }
    // goals removal: the goal_manage wrapper must stay gone
    expect(N.Chat.memoryPanel.completeGoal).toBeUndefined();
  });

  it('renders reflection without inline onclick (CSP-safe)', () => {
    ensurePanel();
    N.Chat.memoryPanel.updateReflection(['insight one']);
    expect(document.getElementById('memory-reflection-list').innerHTML).toContain('insight one');
  });

  it('delegation routes delete clicks, single-bound on double-load', () => {
    ensurePanel();
    loadMemoryPanel();
    loadMemoryPanel(); // double-load must not double-bind
    const del = vi.fn();
    N.Chat.memoryPanel.deleteCard = del;
    document.getElementById('memory-retrieved-list').innerHTML =
      '<button type="button" data-mem-action="delete" data-mem-key="g1">削除</button>';
    document.querySelector('[data-mem-key="g1"]').dispatchEvent(new window.MouseEvent('click', { bubbles: true }));
    expect(del).toHaveBeenCalledTimes(1);
    expect(del).toHaveBeenCalledWith('g1');
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
    N.Chat.memoryPanel.update([{ key: 'm1', content: 'fact one', importance: 0.6, tags: [], score: 0.9 }]);
    const card = document.querySelector('#memory-retrieved-list .memory-item-card');
    expect(card.getAttribute('data-panel-kind')).toBe('memory');
    card.dispatchEvent(new window.MouseEvent('click', { bubbles: true }));
    expect(open).toHaveBeenCalledWith('m1');
  });

  it('memory row without a key falls back to openMemory(partial)', () => {
    N.Chat.memoryPanel.update(undefined, [{ key: '', content: 'partial fact', importance: 0.4, tags: ['a', 'b'] }]);
    const card = document.querySelector('#memory-saved-list .memory-item-card');
    card.dispatchEvent(new window.MouseEvent('click', { bubbles: true }));
    expect(open).not.toHaveBeenCalled();
    expect(openMemory).toHaveBeenCalledWith(expect.objectContaining({ content: 'partial fact', importance: 0.4 }));
  });

  it('object insights render content (not [object Object]) and open the memory modal by key', () => {
    N.Chat.memoryPanel.updateReflection([{ content: 'insight body', key: 'r1', created_at: '2026-09-07T10:00:00' }]);
    const row = document.querySelector('#memory-reflection-list .reflection-insight');
    expect(row.textContent).toContain('insight body');
    expect(row.getAttribute('data-panel-kind')).toBe('reflection');
    row.dispatchEvent(new window.MouseEvent('click', { bubbles: true }));
    // Reflections carry a full memory key → unified memModal.
    expect(open).toHaveBeenCalledWith('r1');
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
