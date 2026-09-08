/* =================================================================
   REM monologue tests — display-only thinking bubble from the wiring
   stream (chat-send.js). Covers: bubble creation from kind=monologue,
   append behaviour, other kinds ignored, no history/save side effects,
   CSP-safe textContent rendering.
   ================================================================= */
import { loadCore, loadFile } from '../core/load-core.js';
import { readFileSync } from 'fs';
import { resolve, dirname } from 'path';
import { fileURLToPath } from 'url';

const __dirname = dirname(fileURLToPath(import.meta.url));

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
  N.Chat.tools = {
    label: (n) => (n === 'memory_search' ? '記憶をたどってる…' : '作業してる…'),
    icon: (n) => (n === 'memory_search' ? 'brain' : 'wrench'),
  };
  // api is captured at module load — stub before chat-history.js loads
  N.Core.api = vi.fn();
  loadFile('../chat/chat-history.js');
});

beforeEach(() => {
  document.body.innerHTML = '<div id="chat-messages"></div>';
  N.Chat.state.messages.length = 0;
  window.S.persona = 'p1';
  N.Chat._sseStreams = {}; // fresh stream registry per test
  N.Core.api.mockReset();
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
  it('keeps monologue bubbles unshrinkable inside the flex chat log', () => {
    // #chat-messages is a flex column; overflow:hidden would zero out the
    // automatic minimum size and collapse restored bubbles to their border
    // (2px line). The bubble must refuse to shrink instead.
    const css = readFileSync(resolve(__dirname, '../styles/chat.css'), 'utf-8');
    const block = css.slice(
      css.indexOf('.chat-monologue-bubble {'),
      css.indexOf('.chat-monologue-bubble summary'),
    );
    expect(block).toContain('flex-shrink: 0');
    expect(block).toContain('overflow: hidden'); // collapse guard stays for the summary
  });

  it('creates a collapsed details bubble with meta.text as textContent', () => {
    N.Chat.monologue.handle(monologueEvt('ふふ、まだ考えてる。'));
    const bs = bubbles();
    expect(bs.length).toBe(1);
    const b = bs[0];
    expect(b.tagName).toBe('DETAILS');
    expect(b.querySelector('summary').textContent).toBe('💭 独り言');
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
  it('opens the memory detail modal from the summary click', () => {
    const openMemory = vi.fn();
    N.Components = N.Components || {};
    N.Components.memModal = { openMemory };
    N.Chat.monologue.handle(monologueEvt('モーダルで読みたい。'));
    const summary = bubbles()[0].querySelector('summary');
    summary.click();
    expect(openMemory).toHaveBeenCalledTimes(1);
    expect(openMemory).toHaveBeenCalledWith({ content: 'モーダルで読みたい。', tags: ['monologue'] });
    // the click opens the modal, so the bubble itself stays collapsed
    expect(bubbles()[0].open).toBe(false);
  });

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

describe('history segment rendering (chat-history.js)', () => {
  function msgShell() {
    const div = document.createElement('div');
    div.className = 'chat-msg assistant';
    div.innerHTML = '<div class="chat-time">10:00</div><div class="chat-msg-actions"></div>';
    document.body.appendChild(div);
    return div;
  }

  it('folds thinking into one head bubble — reload matches live order', () => {
    // persisted order is [text, thinking] (server flushes text first)
    // but live shows thinking at the head of the message
    const div = msgShell();
    N.Chat.history.renderSegments({
      segments: [
        { type: 'text', content: '答えはこう。' },
        { type: 'thinking', content: 'まず考えた。' },
      ],
      time: '10:00',
    }, div);
    const kinds = Array.from(div.children).map((e) => e.className.split(' ')[0]);
    expect(kinds).toEqual(['chat-thinking-bubble', 'chat-bubble', 'chat-time', 'chat-msg-actions']);
    expect(div.querySelector('.chat-thinking-body').textContent).toBe('まず考えた。');
    expect(div.querySelector('.chat-bubble').textContent).toBe('答えはこう。');
  });

  it('merges multi-round thinking segments into the single head bubble', () => {
    const div = msgShell();
    N.Chat.history.renderSegments({
      segments: [
        { type: 'thinking', content: '一期目。' },
        { type: 'text', content: '本文。' },
        { type: 'tool_call', name: 'memory_search', id: 't1', input: {} },
        { type: 'text', content: '続き。' },
        { type: 'thinking', content: '二期目。' },
      ],
      time: '10:00',
    }, div);
    const bodies = Array.from(div.querySelectorAll('.chat-thinking-body'));
    expect(bodies.length).toBe(1); // one bubble, like live
    expect(bodies[0].textContent).toBe('一期目。二期目。');
    const kinds = Array.from(div.children).map((e) => e.className.split(' ')[0]);
    // thinking at head, then text → tool → text, chronological
    expect(kinds.slice(0, 4)).toEqual(['chat-thinking-bubble', 'chat-bubble', 'chat-tool-call', 'chat-bubble']);
  });

  it('renders restored tool chips with the immersive label and icon', () => {
    const div = msgShell();
    N.Chat.history.renderSegments({
      segments: [
        { type: 'tool_call', name: 'memory_search', id: 't9', input: { q: 'remember' } },
      ],
      time: '10:00',
    }, div);
    const chip = div.querySelector('.chat-tool-call');
    expect(chip).not.toBeNull();
    expect(chip.querySelector('strong').textContent).toBe('記憶をたどってる…'); // no raw name
    expect(chip.querySelector('strong').getAttribute('title')).toBe('memory_search'); // debug kept
    expect(chip.querySelector('.chat-tool-summary-left i').getAttribute('data-lucide')).toBe('brain');
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

describe('monologue restore from session events (chat-history.js)', () => {
  it('restores bubbles in chronological order after history render', async () => {
    N.Core.api.mockResolvedValueOnce({ events: [
      { event_type: 'brain.monologue', summary: '新しい独り言。' },
      { event_type: 'brain.monologue', summary: '古い独り言。' },
    ]});
    await N.Chat.monologue.restore();
    const texts = Array.from(document.querySelectorAll('.chat-monologue-text'))
      .map((e) => e.textContent);
    expect(texts).toEqual(['古い独り言。', '新しい独り言。']);
    // display-only: never enters the chat history array
    expect(N.Chat.state.messages.length).toBe(0);
  });

  it('re-fetches scoped to the persona and drops stale responses', async () => {
    N.Core.api.mockResolvedValueOnce({ events: [] });
    window.S.persona = 'p2';
    await N.Chat.monologue.restore();
    expect(N.Core.api).toHaveBeenLastCalledWith(
      '/api/session-events/p2?event_type=brain.monologue&limit=20&order=desc',
    );
    // a response that lands after the persona moved on appends nothing
    N.Core.api.mockResolvedValueOnce({ events: [
      { event_type: 'brain.monologue', summary: '遅れて着いた独り言。' },
    ]});
    const pending = N.Chat.monologue.restore(); // captures p2
    window.S.persona = 'p1';
    await pending;
    expect(bubbles().length).toBe(0);
  });

  it('swallows API failures quietly', async () => {
    N.Core.api.mockRejectedValueOnce(new Error('boom'));
    await expect(N.Chat.monologue.restore()).resolves.toBeUndefined();
    expect(bubbles().length).toBe(0);
  });
});
