/* =================================================================
   SSE single-flight tests — Task 7 (no double-connect on error)
   ================================================================= */
import { loadCore, loadFile } from './load-core.js';

const instances = [];
let N;

function loadSSE() {
  loadFile('sse.js');
}

beforeAll(() => {
  loadCore();
  loadSSE();
  N = window.Nous;
});

beforeEach(() => {
  instances.length = 0;
  vi.useFakeTimers();
  N.Core._sse = null;
  N.Core._sseTimer = null;
  N.Core._sseBackoff = 5000;
  N.Core.store = { get: () => 'p1' };
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
  });
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.useRealTimers();
  delete N.Core.store;
});

describe('sse single-flight', () => {
  it('does not double-connect on error', () => {
    let connects = 0;
    const orig = N.Core.connectSSE;
    N.Core.connectSSE = function (p) { connects++; return orig(p); };
    try {
      N.Core.connectSSE('p1');
      expect(connects).toBe(1);
      const es = instances[0];
      es.onerror();
      es.onerror();
      vi.runAllTimers();
      /* second error cancels the first timer: exactly one reconnect */
      expect(connects).toBe(2);
    } finally {
      N.Core.connectSSE = orig;
    }
  });

  it('closes the old connection on reconnect', () => {
    N.Core.connectSSE('p1');
    const first = instances[0];
    N.Core.connectSSE('p1');
    expect(first.close).toHaveBeenCalled();
    expect(instances.length).toBe(2);
    expect(N.Core._sse).toBe(instances[1]);
  });

  it('disconnectSSE tears down connection and timer', () => {
    N.Core.connectSSE('p1');
    const es = instances[0];
    es.onerror();
    expect(N.Core._sseTimer).not.toBeNull();
    N.Core.disconnectSSE();
    expect(N.Core._sseTimer).toBeNull();
    expect(N.Core._sse).toBeNull();
  });
});
