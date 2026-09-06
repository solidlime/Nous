/* =================================================================
   Tests for components/mem-modal.js — the unified memory detail modal
   Covers: open(key) fetch path, openMemory(mem) render, close,
   Escape key, sanitizer-safe bar markup (data-fill, no style=).
   ================================================================= */
import { loadCore, loadFile } from '../core/load-core.js';

let N;

function modalDom() {
  document.body.innerHTML =
    '<div id="mem-modal-overlay" class="mem-modal-overlay">' +
    '<div class="mem-modal" id="mem-modal-content"></div></div>';
}

const mem = {
  key: 'k1',
  content: '黒いロングコートの記憶',
  importance: 0.5,
  emotion: 'joy',
  emotion_intensity: 0.8,
  tags: ['fashion'],
  created_at: '2026-09-06T07:00:02+09:00',
  updated_at: '2026-09-06T07:00:02+09:00',
};

beforeAll(() => {
  loadCore();
  window.S = { persona: 'p1' };
  N = window.Nous;
  // toast is captured at module load — record calls on a stable array.
  globalThis.__toasts = [];
  N.Core.toast = (msg, kind) => { globalThis.__toasts.push(msg + ':' + kind); };
  // DOMPurify absent in vitest → safeSetHTML falls back to textContent.
  // Identity stand-in so generated markup parses exactly as written —
  // this is what makes the no-inline-style assertion meaningful.
  globalThis.DOMPurify = { sanitize: (html) => String(html) };
  // Feature-side collaborators are runtime lookups — stub them.
  N.Features.Memories = N.Features.Memories || {};
  N.Features.Memories.tagChipHtml = (t) => '<span class="tag-chip">' + t + '</span>';
  N.Features.Memories.openEditModal = () => {};
  N.Features.Memories.deleteMemory = () => {};
  N.Components.memoryCard = {
    renderBodyStateBars: () => '',
    renderEmotionBars: () => '',
  };
  loadFile('../components/mem-modal.js');
});

beforeEach(() => {
  modalDom();
  // api is captured at module load; stub the fetch beneath it instead.
  vi.stubGlobal('fetch', vi.fn((url) => {
    globalThis.__apiUrl = String(url);
    return Promise.resolve({
      ok: true,
      headers: { get: () => 'application/json' },
      json: () => Promise.resolve({ memory: mem }),
    });
  }));
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('N.Components.memModal — open(key) fetch path', () => {
  it('fetches by key, then opens with the returned memory', async () => {
    await N.Components.memModal.open('k1');
    expect(globalThis.__apiUrl).toBe('/api/memories/p1/k1');
    const overlay = document.getElementById('mem-modal-overlay');
    expect(overlay.classList.contains('show')).toBe(true);
    expect(overlay.querySelector('.mem-modal-content').textContent)
      .toContain('黒いロングコート');
  });

  it('toasts (does not throw) when the memory is missing', async () => {
    globalThis.__toasts.length = 0;
    vi.stubGlobal('fetch', vi.fn(() => Promise.resolve({
      ok: true,
      headers: { get: () => 'application/json' },
      json: () => Promise.resolve({}),
    })));
    await N.Components.memModal.open('missing');
    expect(globalThis.__toasts[0]).toBe('Memory not found:error');
    expect(document.getElementById('mem-modal-overlay').classList.contains('show')).toBe(false);
  });
});

describe('N.Components.memModal — openMemory(mem) render', () => {
  it('renders rows with data-fill bars and never inline style', () => {
    N.Components.memoryCard.renderBodyStateBars = (bs) =>
      bs && bs.fatigue != null
        ? '<div class="mem-bar-fill" data-fill="50" data-color="#f87171"></div>'
        : '';
    N.Components.memoryCard.renderEmotionBars = (emo, i) =>
      '<div class="mem-bar-fill" data-fill="80" data-color="#fbbf24"></div>';
    N.Components.memModal.openMemory(mem);
    const overlay = document.getElementById('mem-modal-overlay');
    expect(overlay.classList.contains('show')).toBe(true);
    const html = overlay.innerHTML;
    expect(html).toContain('data-fill="50"'); // importance 0.5
    expect(html).toContain('data-fill="80"'); // emotion 0.8
    expect(html).toContain('fashion');
    expect(html).not.toContain('style=');
    expect(html).not.toContain('onclick');
  });

  it('close() hides the overlay again', () => {
    N.Components.memModal.openMemory(mem);
    N.Components.memModal.close();
    expect(document.getElementById('mem-modal-overlay').classList.contains('show')).toBe(false);
  });

  it('Escape closes the modal', () => {
    N.Components.memModal.openMemory(mem);
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }));
    expect(document.getElementById('mem-modal-overlay').classList.contains('show')).toBe(false);
  });
});
