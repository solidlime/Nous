/* =================================================================
   chat-wiring-feed tests — live synapse fire feed in the memory panel
   Covers: client top-N trim, limit 0 hides, single-flight reconnect,
   empty stream, invalid-kind drop, XSS escaping, panel visibility.
   ================================================================= */
import { readFileSync } from 'fs';
import { resolve, dirname } from 'path';
import { fileURLToPath } from 'url';
import { loadCore, loadFile } from '../core/load-core.js';

const __dirname = dirname(fileURLToPath(import.meta.url));

function loadChat(file) {
  const code = readFileSync(resolve(__dirname, file), 'utf-8');
  new Function(code)();
}

const instances = [];
let N;
let MP;

function wiringList() {
  return document.getElementById('memory-wiring-list');
}

function fire(seq, kind, source, target, weight) {
  return { seq, kind, source, target, weight, meta: {} };
}

beforeAll(() => {
  loadCore();
  loadFile('sse.js'); // loaded first so the disconnectSSE wrap engages
  // DOMPurify is a browser CDN global, absent in vitest. Identity
  // stand-in so feed markup parses here exactly as written — which is
  // what makes the XSS assertions below meaningful: if our escaping
  // ever regressed, the payload would parse into live elements.
  globalThis.DOMPurify = { sanitize: (html) => String(html) };
  N = window.Nous;
  window.S = { persona: 'p1' };
  N.Core.toast = N.Core.toast || (() => {});
  N.Core.showConfirm = N.Core.showConfirm || ((msg, cb) => { if (cb) cb(); });
  N.Core.showAlert = N.Core.showAlert || (() => {});
  N.Components.memoryCard = {
    renderEmotionBadges: () => '',
    renderBodyStateCompact: () => '',
  };
  loadChat('chat-memory-panel.js');
  MP = N.Chat.memoryPanel;
});

beforeEach(() => {
  instances.length = 0;
  vi.useFakeTimers();
  // jsdom's localStorage is unavailable here — in-memory stand-in.
  const _store = {};
  Object.defineProperty(window, 'localStorage', {
    value: {
      getItem: (k) => (k in _store ? _store[k] : null),
      setItem: (k, v) => { _store[k] = String(v); },
      removeItem: (k) => { delete _store[k]; },
      clear: () => { for (const k of Object.keys(_store)) delete _store[k]; },
    },
    configurable: true,
  });
  N.Core._wiringSSE = null;
  N.Core._wiringTimer = null;
  N.Core._wiringBackoff = 5000;
  vi.stubGlobal('EventSource', class {
    constructor(url) {
      this.url = url;
      this._listeners = {};
      this.close = vi.fn();
      instances.push(this);
    }
    addEventListener(ev, fn) {
      (this._listeners[ev] = this._listeners[ev] || []).push(fn);
    }
    removeEventListener(ev, fn) {
      const arr = this._listeners[ev] || [];
      const i = arr.indexOf(fn);
      if (i !== -1) arr.splice(i, 1);
    }
    emit(ev, data) {
      (this._listeners[ev] || []).forEach((fn) => fn({ data }));
    }
  });
  document.body.innerHTML = `
    <div id="memory-panel">
      <div class="memory-panel-section">
        <div class="memory-section-header" id="reflection-header">リフレクション</div>
        <div id="memory-reflection-list"></div>
      </div>
      <div id="memory-retrieved-list"></div>
      <div id="memory-saved-list"></div>
      <div id="memory-goals-list"></div>
      <div id="memory-promises-list"></div>
    </div>
    <details data-category="reflection"><div class="details-body">
      <input type="number" id="chat-reflection-threshold" value="1.0" />
    </div></details>`;
  MP.setWiringVisible(true);
  MP.disconnectWiring(); // kills sockets/timers, resets flush suppression
  window.S.persona = 'p1';
  MP.switchWiringPersona('p1'); // resets persona scoping + clears buffer
  MP.setFireLimit(8);
  // Start each test disconnected with zero sockets; tests connect explicitly.
  MP.disconnectWiring();
  instances.length = 0;
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

describe('wiring feed trim + render', () => {
  it('keeps newest-first and trims to top-N (default 8)', () => {
    for (let i = 1; i <= 10; i++) {
      expect(MP.pushWiringEvent(fire(i, 'link_fire', 'a' + i, 'b' + i, 0.5))).toBe(true);
    }
    const items = wiringList().querySelectorAll('.wiring-fire-item');
    expect(items.length).toBe(8);
    expect(items[0].getAttribute('data-seq')).toBe('10');
    expect(items[7].getAttribute('data-seq')).toBe('3');
    expect(items[0].classList.contains('is-fresh')).toBe(true);
    expect(items[1].classList.contains('is-fresh')).toBe(false);
  });

  it('honours a custom limit and persists it', () => {
    MP.setFireLimit(3);
    expect(MP.getFireLimit()).toBe(3);
    expect(window.localStorage.getItem('nous_wiring_limit')).toBe('3');
    for (let i = 1; i <= 5; i++) {
      MP.pushWiringEvent(fire(i, 'recall_boost', 'x', 'y', 0.9));
    }
    expect(wiringList().querySelectorAll('.wiring-fire-item').length).toBe(3);
  });

  it('limit 0 hides the section and renders nothing', () => {
    MP.pushWiringEvent(fire(1, 'link_fire', 'a', 'b', 0.5));
    MP.setFireLimit(0);
    expect(document.getElementById('memory-wiring-section').classList.contains('is-hidden')).toBe(true);
    expect(wiringList().querySelectorAll('.wiring-fire-item').length).toBe(0);
    MP.setFireLimit(8);
    expect(document.getElementById('memory-wiring-section').classList.contains('is-hidden')).toBe(false);
    expect(wiringList().querySelectorAll('.wiring-fire-item').length).toBe(1);
  });

  it('empty stream shows the quiet placeholder without throwing', () => {
    MP.clearWiring();
    expect(() => MP.renderWiringFeed()).not.toThrow();
    expect(wiringList().innerHTML).toContain('まだシナプスは静か');
  });

  it('renders the replay_fire kind with the リプレイ badge', () => {
    expect(MP.pushWiringEvent(fire(1, 'replay_fire', 'a', 'b', 0.6))).toBe(true);
    const item = wiringList().querySelector('.wiring-fire-item');
    expect(item.classList.contains('wiring-kind-replay_fire')).toBe(true);
    expect(item.querySelector('.wiring-kind-badge').textContent).toBe('リプレイ');
  });

  it('drops unknown kinds, dedupes replayed seqs, escapes XSS', () => {
    expect(MP.pushWiringEvent(fire(1, 'nope', 'a', 'b', 1))).toBe(false);
    expect(MP.pushWiringEvent(null)).toBe(false);
    MP.pushWiringEvent(fire(7, 'ppr_hit', 'k1', 'k2', 0.77));
    expect(MP.pushWiringEvent(fire(7, 'ppr_hit', 'k1', 'k2', 0.77))).toBe(false); // ring replay
    MP.pushWiringEvent(fire(8, 'link_fire', '<img src=x onerror=alert(1)>', 'b&c', 0.1));
    const list = wiringList();
    expect(list.querySelector('img')).toBeNull();
    expect(list.querySelector('[onerror]')).toBeNull();
    // content-first rows: unresolved target key falls back to the raw key
    expect(list.textContent).toContain('b&c');
    expect(list.querySelectorAll('.wiring-fire-item').length).toBe(2);
    // the hostile source key never parses into live elements — it shows
    // up escaped in the detail modal's Edge row
    MP.openWiringDetail('b&c');
    const overlay = document.getElementById('wiring-detail-overlay');
    expect(overlay.style.display).toBe('flex');
    expect(overlay.querySelector('img')).toBeNull();
    expect(overlay.querySelector('.wiring-edge-detail').textContent)
      .toContain('<img src=x onerror=alert(1)>');
    MP.closeWiringDetail();
    expect(overlay.style.display).toBe('none');
  });

  it('injects the feed next to reflection and the numeric setting without inline handlers', () => {
    MP.renderWiringFeed();
    const section = document.getElementById('memory-wiring-section');
    expect(section).not.toBeNull();
    const reflection = document.getElementById('memory-reflection-list')
      .closest('.memory-panel-section');
    expect(reflection.nextSibling).toBe(section);
    const input = document.getElementById('chat-wiring-fire-limit');
    expect(input).not.toBeNull();
    expect(input.getAttribute('oninput')).toBeNull();
    expect(input.getAttribute('onchange')).toBeNull();
    expect(wiringList().getAttribute('aria-live')).toBe('polite');
  });
});

describe('wiring SSE single-flight + visibility', () => {
  it('connects once, closes the old socket on reconnect', () => {
    MP.connectWiring();
    expect(instances.length).toBe(1);
    expect(instances[0].url).toBe('/api/memory/wiring/stream?persona=p1');
    MP.connectWiring();
    expect(instances[0].close).toHaveBeenCalled();
    expect(instances.length).toBe(2);
    expect(N.Core._wiringSSE).toBe(instances[1]);
  });

  it('live events land in the feed, newest on top', () => {
    MP.connectWiring();
    instances[0].emit('wiring', JSON.stringify(fire(1, 'link_fire', 'm1', 'm2', 0.42)));
    instances[0].emit('wiring', 'not-json{{{');
    instances[0].emit('wiring', JSON.stringify(fire(2, 'recall_boost', 'm3', 'm4', 0.9)));
    const items = wiringList().querySelectorAll('.wiring-fire-item');
    expect(items.length).toBe(2);
    expect(items[0].getAttribute('data-seq')).toBe('2');
  });

  it('error schedules exactly one reconnect (single-flight)', () => {
    MP.connectWiring();
    expect(instances.length).toBe(1);
    instances[0].onerror();
    instances[0].onerror();
    expect(N.Core._wiringTimer).not.toBeNull();
    vi.runAllTimers();
    /* second error cancelled the first timer: exactly one reconnect */
    expect(instances.length).toBe(2);
    expect(N.Core._wiringSSE).toBe(instances[1]);
  });

  it('panel hidden cuts the stream, reshown reconnects', () => {
    MP.connectWiring();
    expect(N.Core._wiringSSE).not.toBeNull();
    MP.setWiringVisible(false);
    expect(N.Core._wiringSSE).toBeNull();
    MP.setWiringVisible(true);
    expect(N.Core._wiringSSE).not.toBeNull();
    expect(instances.length).toBe(2);
  });

  it('disconnectSSE also tears down the wiring stream', () => {
    MP.connectWiring();
    const es = instances[0];
    es.onerror();
    expect(N.Core._wiringTimer).not.toBeNull();
    N.Core.disconnectSSE();
    expect(N.Core._wiringTimer).toBeNull();
    expect(N.Core._wiringSSE).toBeNull();
  });
});

describe('persona scoping', () => {
  const wiringSockets = () => instances.filter(
    (es) => es.url.indexOf('/api/memory/wiring/stream') === 0);

  it('persona switch clears the feed and resockets scoped', () => {
    MP.connectWiring();
    expect(wiringSockets().length).toBe(1);
    wiringSockets()[0].emit('wiring',
      JSON.stringify(fire(1, 'link_fire', 'a', 'b', 0.5)));
    expect(wiringList().querySelectorAll('.wiring-fire-item').length).toBe(1);
    N.Core.connectSSE('p2'); // main connect drives the wiring switch
    expect(wiringSockets()[0].close).toHaveBeenCalled();
    expect(wiringSockets().length).toBe(2);
    expect(wiringSockets()[1].url).toBe('/api/memory/wiring/stream?persona=p2');
    expect(wiringList().querySelectorAll('.wiring-fire-item').length).toBe(0);
    expect(wiringList().innerHTML).toContain('まだシナプスは静か');
  });

  it('same-persona main reconnect keeps the feed (no needless clear)', () => {
    MP.connectWiring();
    wiringSockets()[0].emit('wiring',
      JSON.stringify(fire(1, 'link_fire', 'a', 'b', 0.5)));
    N.Core.connectSSE('p1');
    expect(wiringSockets().length).toBe(1);
    expect(wiringList().querySelectorAll('.wiring-fire-item').length).toBe(1);
  });
});

describe('backoff + flush batching', () => {
  it('resets backoff to 5000 on open (main-stream manners)', () => {
    MP.connectWiring();
    instances[0].onerror();
    expect(N.Core._wiringBackoff).toBe(10000);
    vi.runAllTimers();
    expect(instances.length).toBe(2);
    instances[1].onopen();
    expect(N.Core._wiringBackoff).toBe(5000);
  });

  it('batches the connect flush into a single paint', () => {
    MP.connectWiring();
    instances[0].emit('connected', '{}');
    for (let i = 1; i <= 5; i++) {
      instances[0].emit('wiring',
        JSON.stringify(fire(i, 'link_fire', 's' + i, 't' + i, 0.5)));
    }
    // Suppressed mid-flush: still the quiet placeholder.
    expect(wiringList().querySelectorAll('.wiring-fire-item').length).toBe(0);
    expect(wiringList().innerHTML).toContain('まだシナプスは静か');
    vi.advanceTimersByTime(500);
    const items = wiringList().querySelectorAll('.wiring-fire-item');
    expect(items.length).toBe(5);
    expect(items[0].getAttribute('data-seq')).toBe('5');
  });

  it('live events past the flush window paint immediately', () => {
    MP.connectWiring();
    instances[0].emit('connected', '{}');
    vi.advanceTimersByTime(500);
    instances[0].emit('wiring',
      JSON.stringify(fire(1, 'link_fire', 'a', 'b', 0.5)));
    expect(wiringList().querySelectorAll('.wiring-fire-item').length).toBe(1);
  });
});

describe('recall_boost evidence', () => {
  it('shows recall_count/stability instead of the flat ≈1.00 weight', () => {
    MP.pushWiringEvent({
      seq: 1, kind: 'recall_boost', source: 'k', target: '',
      weight: 1.0, meta: { recall_count: 3, stability: 0.82, persona: 'p1' },
    });
    const item = wiringList().querySelector('.wiring-fire-item');
    expect(item.querySelector('.wiring-meta').textContent).toContain('×3回');
    expect(item.querySelector('.wiring-meta').textContent).toContain('0.82');
    expect(item.querySelector('.wiring-weight')).toBeNull();
  });

  it('falls back to weight when recall meta is absent', () => {
    MP.pushWiringEvent(fire(1, 'recall_boost', 'k', '', 0.97));
    const item = wiringList().querySelector('.wiring-fire-item');
    expect(item.querySelector('.wiring-meta')).toBeNull();
    expect(item.querySelector('.wiring-weight').textContent).toBe('0.97');
  });
});

describe('toggleMemory drives the feed', () => {
  it('hides/shows the wiring stream with the panel', async () => {
    loadChat('chat-core.js');
    const seen = [];
    const orig = MP.setWiringVisible;
    MP.setWiringVisible = function (open) { seen.push(open); };
    try {
      N.Chat.core.toggleMemory(); // open -> closed
      expect(seen[seen.length - 1]).toBe(false);
      N.Chat.core.toggleMemory(); // closed -> open
      expect(seen[seen.length - 1]).toBe(true);
    } finally {
      MP.setWiringVisible = orig;
    }
  });
});

describe('content-first rows (memory resolution + weight bar)', () => {
  function flushMicrotasks() {
    // ~10 ticks covers fetch -> json -> remember -> allSettled -> re-render
    let p = Promise.resolve();
    for (let i = 0; i < 10; i++) p = p.then(() => {});
    return p;
  }

  function fetchMemoriesByKey(payload) {
    return vi.fn((url) => {
      const key = decodeURIComponent(String(url).split('/').pop());
      return Promise.resolve({
        ok: true,
        headers: { get: () => 'application/json' },
        json: () => Promise.resolve({ memory: payload(key) }),
      });
    });
  }

  const memFor = (key) => ({
    key,
    // fresh keys (w1/w2) — earlier tests mark their keys as fetch-failed in
    // the panel's cache, and that map intentionally persists per file
    content: key === 'w2' ? '彼女は黒いロングコートを選んだ — なかなかの選択ね' : 'old memory w1',
    kind: 'semantic',
    importance: 0.5,
    tags: ['fashion'],
    created_at: '2026-09-06T07:00:02+09:00',
    related_keys: [],
  });

  it('shows the content summary and a data-fill weight bar', async () => {
    vi.stubGlobal('fetch', fetchMemoriesByKey((key) => memFor(key)));
    MP.clearWiring();
    MP.pushWiringEvent(fire(1, 'link_fire', 'w1', 'w2', 0.24));
    await flushMicrotasks();
    const row = wiringList().querySelector('[data-wiring-open="w2"]');
    expect(row).not.toBeNull();
    expect(row.textContent).toContain('黒いロングコート');
    expect(row.getAttribute('role')).toBe('button');
    expect(row.getAttribute('tabindex')).toBe('0');
    const fill = row.querySelector('.mem-bar-fill');
    expect(fill.getAttribute('data-fill')).toBe('24');
    expect(row.querySelector('.wiring-weight').textContent).toBe('0.24');
  });

  it('opens the detail modal with full content, kind, tags, importance bar', async () => {
    vi.stubGlobal('fetch', fetchMemoriesByKey((key) => memFor(key)));
    MP.clearWiring();
    MP.pushWiringEvent(fire(1, 'link_fire', 'w1', 'w2', 0.24));
    await flushMicrotasks();
    const row = wiringList().querySelector('[data-wiring-open="w2"]');
    row.focus();
    row.click();
    const overlay = document.getElementById('wiring-detail-overlay');
    expect(overlay.style.display).toBe('flex');
    expect(overlay.querySelector('.wiring-detail-text').textContent)
      .toContain('黒いロングコートを選んだ');
    expect(overlay.textContent).toContain('semantic');
    expect(overlay.textContent).toContain('fashion');
    expect(overlay.querySelector('.modal-progress-fill').getAttribute('data-fill')).toBe('50');
    expect(overlay.textContent).toContain('w1');
    // Escape closes and restores focus to the opening row
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }));
    expect(overlay.style.display).toBe('none');
    expect(document.activeElement).toBe(row);
  });
});
