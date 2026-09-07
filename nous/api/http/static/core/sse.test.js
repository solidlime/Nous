/* =================================================================
   SSE tests — named multi-stream manager in core/sse.js
   Covers: main stream single-flight, live-persona reconnect,
   backoff doubling + reset on open, teardown, stream independence,
   gated streams (url() → null opens nothing), config.updated
   settings sync listener.
   ================================================================= */
import { loadCore, loadFile } from './load-core.js';

const instances = [];
let N;

beforeAll(() => {
  loadCore();
  loadFile('sse.js');
  N = window.Nous;
});

beforeEach(() => {
  instances.length = 0;
  vi.useFakeTimers();
  N.Core._sseStreams = {};
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
    emit(ev, data) {
      (this._listeners[ev] || []).forEach((fn) => fn({ data }));
    }
  });
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.useRealTimers();
  delete N.Core.store;
});

describe('main stream (connectSSE)', () => {
  it('does not double-connect on error', () => {
    N.Core.connectSSE('p1');
    instances[0].onerror();
    instances[0].onerror();
    vi.runAllTimers();
    /* second error cancels the first timer: exactly one reconnect */
    expect(instances.length).toBe(2);
    expect(N.Core.streamSocket('main')).toBe(instances[1]);
  });

  it('closes the old connection on reconnect', () => {
    N.Core.connectSSE('p1');
    const first = instances[0];
    N.Core.connectSSE('p1');
    expect(first.close).toHaveBeenCalled();
    expect(instances.length).toBe(2);
    expect(N.Core.streamSocket('main')).toBe(instances[1]);
  });

  it('reconnect follows the live persona from the store', () => {
    N.Core.connectSSE('p1');
    N.Core.store = { get: () => 'p2' };
    instances[0].onerror();
    vi.runAllTimers();
    expect(instances[1].url)
      .toBe('/api/events/p2?topics=memory,context,emotion,body,session,config');
  });

  it('no reconnect when the store has no persona', () => {
    N.Core.connectSSE('p1');
    N.Core.store = { get: () => null };
    instances[0].onerror();
    vi.runAllTimers();
    expect(instances.length).toBe(1);
  });

  it('backoff doubles and resets on open', () => {
    N.Core.connectSSE('p1');
    instances[0].onerror();
    expect(N.Core._sseStreams.main.backoff).toBe(10000);
    vi.runAllTimers();
    instances[1].onopen();
    expect(N.Core._sseStreams.main.backoff).toBe(5000);
  });

  it('disconnectSSE tears down connection and timer', () => {
    N.Core.connectSSE('p1');
    instances[0].onerror();
    expect(N.Core._sseStreams.main.timer).not.toBeNull();
    N.Core.disconnectSSE();
    expect(N.Core._sseStreams.main.timer).toBeNull();
    expect(N.Core.streamSocket('main')).toBeNull();
  });
});

describe('stream engine (multi-stream)', () => {
  it('named streams are independent', () => {
    N.Core.connectSSE('p1');
    N.Core.connectStream('wiring', {
      url: () => '/api/memory/wiring/stream?persona=p1',
      handlers: {},
    });
    expect(instances.length).toBe(2);
    N.Core.disconnectStream('wiring');
    expect(N.Core.streamSocket('wiring')).toBeNull();
    expect(N.Core.streamSocket('main')).toBe(instances[0]);
  });

  it('url() returning null opens no socket (gated stream)', () => {
    N.Core.connectStream('gated', { url: () => null, handlers: {} });
    expect(instances.length).toBe(0);
    expect(N.Core.streamSocket('gated')).toBeNull();
  });

  it('connectStream detaches handlers from the old socket', () => {
    const handler = vi.fn();
    N.Core.connectStream('s', {
      url: () => '/api/x',
      handlers: { tick: handler },
    });
    const first = instances[0];
    N.Core.connectStream('s', {
      url: () => '/api/x',
      handlers: { tick: handler },
    });
    first.emit('tick', '{}');
    expect(handler).not.toHaveBeenCalled();
  });
});

describe('config sync listener (config.updated)', () => {
  beforeEach(() => {
    document.body.innerHTML =
      '<span id="sse-status"></span>' +
      '<div id="settings-panel"><input id="chat-model" value="m" /></div>';
    N.Chat = { state: {}, settings: { load: vi.fn(() => Promise.resolve({})) } };
  });

  it('subscribes to the config topic', () => {
    N.Core.connectSSE('p1');
    expect(instances[0].url).toContain('topics=memory,context,emotion,body,session,config');
    expect(instances[0]._listeners['config.updated']).toHaveLength(1);
  });

  it('reloads settings once per burst while the panel is open', () => {
    N.Core.connectSSE('p1');
    const es = instances[0];
    es.emit('config.updated', '{}');
    es.emit('config.updated', '{}'); // burst — debounce collapses it
    expect(N.Chat.settings.load).not.toHaveBeenCalled(); // not yet
    vi.advanceTimersByTime(900);
    expect(N.Chat.settings.load).toHaveBeenCalledTimes(1);
  });

  it('does not reload while the settings panel is closed', () => {
    document.body.innerHTML =
      '<span id="sse-status"></span>' +
      '<div id="settings-panel" class="collapsed"><input id="chat-model" value="m" /></div>';
    N.Core.connectSSE('p1');
    instances[0].emit('config.updated', '{}');
    vi.advanceTimersByTime(5000);
    expect(N.Chat.settings.load).not.toHaveBeenCalled();
  });
});
