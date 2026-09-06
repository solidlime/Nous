/* =================================================================
   graph flash tests — wiring SSE → node flash with generation tokens
   Covers: kind color + size pulse, 500ms restore, per-node single
   timer (newest flash wins), unknown kind / missing node rejection,
   flash-enabled gating of the wiring SSE subscription.
   ================================================================= */
import { readFileSync } from 'fs';
import { resolve, dirname } from 'path';
import { fileURLToPath } from 'url';
import { loadCore, loadFile } from '../core/load-core.js';

const __dirname = dirname(fileURLToPath(import.meta.url));

const instances = [];
let G;

function fakeNodes(initial) {
  const store = initial || {};
  return {
    store,
    get: (id) => store[id] || null,
    update: (patch) => { Object.assign(store[patch.id], patch); },
  };
}

beforeAll(() => {
  loadCore();
  loadFile('sse.js'); // graph flash rides the shared stream manager
  window.S = { persona: 'p1', tab: 'graph' };
  globalThis.N = window.Nous; // graph.js references bare N (script-tag global)
  const code = readFileSync(resolve(__dirname, 'graph.js'), 'utf-8');
  new Function(code)();
  G = window.Nous.Features.Graph;
});

beforeEach(() => {
  instances.length = 0;
  vi.useFakeTimers();
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
    emit(ev, data) {
      (this._listeners[ev] || []).forEach((fn) => fn({ data }));
    }
  });
  G.disconnectGraphFlash();
  G.setGraphFlashDataSet(null);
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

describe('flash generation tokens', () => {
  it('flashes with the kind color + size pulse, restores after 500ms', () => {
    const nodes = fakeNodes({
      m1: { id: 'm1', size: 20, color: { background: '#aaa', border: '#aaa' } },
    });
    G.setGraphFlashDataSet({ nodes });
    expect(G.handleWiringEvent({ kind: 'novelty_gate', source: 'm1', target: '' })).toBe(true);
    const n = nodes.store.m1;
    expect(n.color.background).toBe(G.FLASH_COLORS.novelty_gate);
    expect(n.size).toBe(40); // novelty is the biggest pulse (×2.0)
    vi.advanceTimersByTime(500);
    expect(n.color.background).toBe('#aaa');
    expect(n.size).toBe(20);
  });

  it('coalesces consecutive flashes to one timer per node — newest wins', () => {
    const nodes = fakeNodes({
      m1: { id: 'm1', size: 10, color: { background: '#aaa', border: '#aaa' } },
    });
    G.setGraphFlashDataSet({ nodes });
    G.flashNodeOn(nodes, 'm1', 'link_fire');
    vi.advanceTimersByTime(400);
    G.flashNodeOn(nodes, 'm1', 'replay_fire');
    // generation token: the new flash cleared the old timer
    expect(Object.keys(G._flashTimers()).length).toBe(1);
    vi.advanceTimersByTime(100); // t=500 — the first (cleared) timer would have fired
    expect(nodes.store.m1.color.background).toBe(G.FLASH_COLORS.replay_fire);
    vi.advanceTimersByTime(400); // t=900 — the second timer fires
    expect(nodes.store.m1.color.background).toBe('#aaa');
    expect(nodes.store.m1.size).toBe(10);
    expect(Object.keys(G._flashTimers()).length).toBe(0);
  });

  it('rejects unknown kinds and missing nodes without timers', () => {
    const nodes = fakeNodes({});
    G.setGraphFlashDataSet({ nodes });
    expect(G.flashNodeOn(nodes, 'm1', 'nope')).toBe(false);
    expect(G.flashNodeOn(nodes, 'ghost', 'link_fire')).toBe(false);
    expect(Object.keys(G._flashTimers()).length).toBe(0);
  });
});

describe('wiring SSE subscription', () => {
  it('flashes both endpoints of a wiring event', () => {
    window.S.tab = 'graph';
    const nodes = fakeNodes({
      a: { id: 'a', size: 10, color: { background: '#aaa', border: '#aaa' } },
      b: { id: 'b', size: 10, color: { background: '#bbb', border: '#bbb' } },
    });
    G.setGraphFlashDataSet({ nodes });
    expect(G.handleWiringEvent({ kind: 'link_fire', source: 'a', target: 'b' })).toBe(true);
    expect(Object.keys(G._flashTimers()).length).toBe(2);
  });

  it('gates on flash setting + graph tab, drops bad JSON, single-flight socket', () => {
    window.S.tab = 'graph';
    const nodes = fakeNodes({
      m1: { id: 'm1', size: 10, color: { background: '#aaa', border: '#aaa' } },
    });
    G.setGraphFlashDataSet({ nodes });
    G.setFlashEnabled(true);
    G.setFlashEnabled(true); // single-flight: no second socket
    expect(instances.length).toBe(1);
    expect(instances[0].url).toBe('/api/memory/wiring/stream?persona=p1');
    instances[0].emit('wiring', JSON.stringify({ seq: 1, kind: 'recall_boost', source: 'm1', target: '' }));
    expect(nodes.store.m1.color.background).toBe(G.FLASH_COLORS.recall_boost);
    // off-graph tab: events ignored (socket stays — memory-panel manners)
    window.S.tab = 'memories';
    expect(G.handleWiringEvent({ kind: 'link_fire', source: 'm1', target: '' })).toBe(false);
    window.S.tab = 'graph';
    expect(() => instances[0].emit('wiring', 'not-json{{{')).not.toThrow();
    // disable → socket closed; re-enable → fresh socket
    G.setFlashEnabled(false);
    expect(instances[0].close).toHaveBeenCalled();
    G.setFlashEnabled(true);
    expect(instances.length).toBe(2);
  });

  it('reconnects with backoff through the core stream manager', () => {
    window.S.tab = 'graph';
    G.setGraphFlashDataSet({ nodes: fakeNodes({}) });
    G.setFlashEnabled(true);
    instances[0].onerror();
    expect(N.Core._sseStreams['graph-flash'].timer).not.toBeNull();
    vi.runAllTimers();
    // backoff reconnect now matches the main stream (was: dead socket)
    expect(instances.length).toBe(2);
    expect(instances[1].url).toBe('/api/memory/wiring/stream?persona=p1');
  });

  it('disconnect cancels a pending reconnect timer', () => {
    window.S.tab = 'graph';
    G.setGraphFlashDataSet({ nodes: fakeNodes({}) });
    G.setFlashEnabled(true);
    instances[0].onerror();
    G.setFlashEnabled(false);
    expect(N.Core._sseStreams['graph-flash'].timer).toBeNull();
    vi.runAllTimers();
    expect(instances.length).toBe(1); // no reconnect after teardown
  });
});
