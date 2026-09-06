/* =================================================================
   REM monologue tests — display-only thinking bubble from the wiring
   stream (chat-send.js). Covers: bubble creation from kind=monologue,
   append behaviour, other kinds ignored, no history/save side effects,
   CSP-safe textContent rendering.
   ================================================================= */
import { loadCore, loadFile } from '../core/load-core.js';

const instances = [];
let N;

function monologueEvt(text, persona) {
  return JSON.stringify({ kind: 'monologue', source: '', target: '', weight: 0, meta: { persona: persona || 'p1', text } });
}

function bubbles() {
  return document.querySelectorAll('#chat-messages .chat-monologue-bubble');
}

beforeAll(() => {
  loadCore();
  loadFile('sse.js');
  globalThis.DOMPurify = { sanitize: (html) => String(html) };
  globalThis.CSS = { escape: (s) => String(s) };
  N = window.Nous;
  window.S = { persona: 'p1' };
  N.Chat = N.Chat || {};
  N.Chat.state = { messages: [], streaming: false };
  N.Chat.markdown = { render: (s) => s };
  loadFile('../chat/chat-send.js');
});

beforeEach(() => {
  document.body.innerHTML = '<div id="chat-messages"></div>';
  N.Chat.state.messages.length = 0;
  window.S.persona = 'p1';
  N.Chat._sseStreams = {}; // fresh stream registry per test
  instances.length = 0;
  // jsdom (vitest env) lacks EventSource — minimal recording stub.
  vi.stubGlobal('EventSource', class {
    constructor(url) {
      this.url = url;
      this._listeners = {};
      this.close = vi.fn();
      instances.push(this);
    }
    addEventListener(ev, fn) { (this._listeners[ev] = this._listeners[ev] || []).push(fn); }
    removeEventListener(ev, fn) {
      const arr = this._listeners[ev] || [];
      const i = arr.indexOf(fn);
      if (i !== -1) arr.splice(i, 1);
    }
    emit(ev, data) { (this._listeners[ev] || []).forEach((fn) => fn({ data })); }
  });
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('monologue bubble rendering', () => {
  it('creates a collapsed details bubble with meta.text as textContent', () => {
    N.Chat.monologue.handle(monologueEvt('ふふ、まだ考えてる。'));
    const bs = bubbles();
    expect(bs.length).toBe(1);
    const b = bs[0];
    expect(b.tagName).toBe('DETAILS');
    expect(b.querySelector('summary').textContent).toBe('💭');
    expect(b.querySelector('.chat-monologue-text').textContent).toBe('ふふ、まだ考えてる。');
  });

  it('appends one bubble per event', () => {
    N.Chat.monologue.handle(monologueEvt('一つ目。'));
    N.Chat.monologue.handle(monologueEvt('二つ目。'));
    expect(bubbles().length).toBe(2);
    expect(bubbles()[1].querySelector('.chat-monologue-text').textContent).toBe('二つ目。');
  });

  it('ignores other wiring kinds', () => {
    N.Chat.monologue.handle(JSON.stringify({ kind: 'link_fire', source: 'a', target: 'b', weight: 0.5 }));
    N.Chat.monologue.handle(JSON.stringify({ kind: 'recall_boost', source: '', target: '', weight: 0, meta: {} }));
    expect(bubbles().length).toBe(0);
  });

  it('drops events from a stale persona', () => {
    N.Chat.monologue.handle(monologueEvt('他ペルソナの独り言', 'other'));
    expect(bubbles().length).toBe(0);
  });

  it('dedupes replayed ring-buffer events by seq and resets on persona switch', () => {
    N.Chat.monologue.connect('p1'); // reset seq guard via the persona funnel
    N.Chat.monologue.handle(JSON.stringify({ kind: 'monologue', seq: 5, meta: { persona: 'p1', text: '一回目。' } }));
    // reconnect replays the ring buffer with the same/lower seqs — no new bubbles
    N.Chat.monologue.handle(JSON.stringify({ kind: 'monologue', seq: 5, meta: { persona: 'p1', text: 'リプレイ。' } }));
    N.Chat.monologue.handle(JSON.stringify({ kind: 'monologue', seq: 3, meta: { persona: 'p1', text: '古いリプレイ。' } }));
    expect(bubbles().length).toBe(1);
    // a genuinely new event still renders
    N.Chat.monologue.handle(JSON.stringify({ kind: 'monologue', seq: 6, meta: { persona: 'p1', text: '新しい。' } }));
    expect(bubbles().length).toBe(2);
    expect(bubbles()[1].textContent).toContain('新しい。');
    // persona switch resets the guard — old seqs for the new persona render once
    window.S.persona = 'p2';
    N.Chat.monologue.connect('p2');
    N.Chat.monologue.handle(JSON.stringify({ kind: 'monologue', seq: 2, meta: { persona: 'p2', text: '新ペルソナ。' } }));
    expect(bubbles().length).toBe(3);
  });

  it('renders hostile text as text only — HTML fragments never parse', () => {
    N.Chat.monologue.handle(monologueEvt('<img src=x onerror=alert(1)>&<b>太字</b>'));
    const b = bubbles()[0];
    expect(b.querySelector('img')).toBeNull();
    expect(b.querySelector('b')).toBeNull();
    expect(b.textContent).toContain('<img src=x onerror=alert(1)>&<b>太字</b>');
  });
});

describe('monologue is display-only', () => {
  it('never touches the chat history array or a save API', async () => {
    const fetchSpy = vi.fn(() => Promise.resolve({ ok: true, json: () => Promise.resolve({}) }));
    vi.stubGlobal('fetch', fetchSpy);
    try {
      N.Chat.monologue.handle(monologueEvt('履歴に入らない。'));
      // let any accidental async work settle
      await Promise.resolve();
      expect(fetchSpy).not.toHaveBeenCalled();
      expect(N.Chat.state.messages.length).toBe(0);
      expect(bubbles().length).toBe(1);
    } finally {
      vi.unstubAllGlobals();
    }
  });
});

describe('monologue stream wiring', () => {
  it('opens the wiring-chat stream scoped to the persona', () => {
    N.Chat.monologue.connect('p1');
    expect(instances.length).toBe(1);
    expect(instances[0].url).toBe('/api/memory/wiring/stream?persona=p1');
    // end-to-end: a wiring event through the live socket renders a bubble
    instances[0].emit('wiring', monologueEvt('ソケット経由。'));
    expect(bubbles().length).toBe(1);
    // url() re-evaluates persona on scheduled reconnects
    window.S.persona = 'p2';
    N.Chat.monologue.connect('p2');
    expect(instances.length).toBe(2);
    expect(instances[1].url).toBe('/api/memory/wiring/stream?persona=p2');
  });
});
