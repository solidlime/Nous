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
