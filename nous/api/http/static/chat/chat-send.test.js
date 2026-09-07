/* =================================================================
   chat-send tests — chat send rides the server-side turn hub stream.
   Covers: 202 registration → hub events render, turn_started dedupe,
   409 error toast, reconnect last_seq resume, remote-viewer done
   history reload, backlog swallow.
   ================================================================= */
import { loadCore, loadFile } from '../core/load-core.js';

const instances = [];
let N;

function raf() {
  return new Promise((resolve) => requestAnimationFrame(resolve));
}

function bubbles() {
  return document.querySelectorAll('#chat-messages .chat-bubble:not(.chat-typing)');
}

function userBubbles() {
  return document.querySelectorAll('#chat-messages .chat-msg.user .chat-bubble');
}

beforeAll(() => {
  loadCore();
  loadFile('sse.js');
  globalThis.DOMPurify = { sanitize: (html) => String(html) };
  globalThis.CSS = { escape: (s) => String(s) };
  N = window.Nous;
  window.S = { persona: 'p1' };
  // toast is captured at module load — mock before chat-send.js loads
  N.Core.toast = vi.fn();
  // api is captured at module load — stub before chat-send.js loads
  N.Core.api = vi.fn();
  N.Chat = {
    state: { messages: [], streaming: false, attachments: [] },
    markdown: { render: (s) => s },
    history: {
      getSessionId: () => 'main',
      restore: vi.fn(),
      edit: vi.fn(),
      delete: vi.fn(),
      rollback: vi.fn(),
    },
    tools: {
      append: vi.fn(() => document.createElement('div')),
      icon: () => 'wrench',
      label: () => '作業してる…',
      showGenSpinner: vi.fn(),
      showGenResult: vi.fn(),
    },
    core: { debug: vi.fn(), loadCommitments: vi.fn() },
    equipment: { update: vi.fn() },
    tts: { play: vi.fn(), autoPlay: vi.fn() },
    attachments: { openViewer: vi.fn() },
    showCharacterFlag: vi.fn(),
  };
  loadFile('../chat/chat-send.js');
});

beforeEach(() => {
  document.body.innerHTML = `
    <div id="chat-messages"></div>
    <textarea id="chat-input"></textarea>
    <button id="chat-send-btn"></button>
    <button id="chat-cancel-btn" style="display:none"></button>
    <div id="chat-status"></div>
    <input type="checkbox" id="chat-debug-mode" />`;
  instances.length = 0;
  N.Chat.state.messages.length = 0;
  N.Chat.state.streaming = false;
  window.S.persona = 'p1';
  N.Core._sseStreams = {};
  N.Core.api.mockReset();
  N.Core.toast.mockClear();
  N.Chat.history.restore.mockClear();
  // End any turn session leaked by a previous test (module-level _turn)
  N.Chat.cancel();
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
    emit(ev, data, id) {
      (this._listeners[ev] || []).forEach((fn) => fn({ data, lastEventId: id }));
    }
  });
});

afterEach(() => {
  vi.unstubAllGlobals();
});

function chatStream() {
  N.Core.connectSSE('p1'); // persona funnel — subscribes main + wiring-chat + chat-events
  return instances.find((s) => s.url.indexOf('/api/chat/p1/events') === 0);
}

async function sendTurn(message) {
  document.getElementById('chat-input').value = message;
  N.Core.api.mockResolvedValueOnce({ turn_id: 't1' });
  await N.Chat.send();
}

describe('chat hub — send flow', () => {
  it('POST registers the turn and the persistent chat-events stream carries it', async () => {
    const es = chatStream();
    expect(es).toBeTruthy();
    await sendTurn('こんにちは');
    expect(N.Core.api).toHaveBeenCalledWith(
      '/api/chat/p1',
      expect.objectContaining({ method: 'POST' }),
    );
    const body = JSON.parse(N.Core.api.mock.calls[0][1].body);
    expect(body.message).toBe('こんにちは');
    expect(body.session_id).toBe('main');
    // turn_started dedupes against the locally rendered user bubble
    es.emit('message', JSON.stringify({ type: 'turn_started', user_message: 'こんにちは', session_id: 'main' }), '1');
    expect(userBubbles().length).toBe(1);
    // deltas render into an assistant div
    es.emit('message', JSON.stringify({ type: 'text_delta', content: 'げんきだよ' }), '2');
    await raf();
    expect(bubbles().length).toBe(2); // user + assistant text
    // done finalizes: streaming ends, msg ids reflected, no history reload (sender)
    es.emit('message', JSON.stringify({ type: 'done', message: 'completed', user_msg_id: 'u1', assistant_msg_id: 'a1' }), '3');
    expect(N.Chat.state.streaming).toBe(false);
    expect(document.getElementById('chat-send-btn').style.display).toBe('');
    const userDiv = document.querySelector('.chat-msg.user');
    expect(userDiv.dataset.msgId).toBe('u1');
    expect(N.Chat.history.restore).not.toHaveBeenCalled();
  });

  it('409 turns into the existing error toast path', async () => {
    chatStream();
    N.Core.api.mockRejectedValueOnce(new Error('Conflict'));
    document.getElementById('chat-input').value = '二重送信';
    await N.Chat.send();
    expect(N.Core.toast.mock.calls.some((c) => String(c[0]).indexOf('送信失敗') !== -1)).toBe(true);
    expect(N.Chat.state.streaming).toBe(false);
    expect(document.getElementById('chat-send-btn').style.display).toBe('');
  });

  it('replays missed events on reconnect via last_seq', async () => {
    vi.useFakeTimers();
    const es = chatStream();
    await sendTurn('つづき');
    es.emit('message', JSON.stringify({ type: 'turn_started', user_message: 'つづき' }), '1');
    es.emit('message', JSON.stringify({ type: 'text_delta', content: '途中まで' }), '2');
    // connection drops — sse.js reconnects with the advanced last_seq
    es.onerror();
    vi.runAllTimers();
    vi.useRealTimers(); // jsdom rAF rides real timers
    const reconnect = instances[instances.length - 1];
    expect(reconnect.url).toBe('/api/chat/p1/events?last_seq=2');
    // replayed duplicates are dropped (bubble content unchanged); genuinely
    // new deltas continue the same bubble
    await raf();
    expect(bubbles()[1].textContent).toBe('途中まで');
    reconnect.emit('message', JSON.stringify({ type: 'text_delta', content: '＋追加分' }), '3');
    await raf();
    expect(bubbles()[1].textContent).toBe('途中まで＋追加分');
  });

  it('remote viewer renders the turn and reloads history on done', async () => {
    const es = chatStream();
    // no local send — the tab is a viewer
    es.emit('message', JSON.stringify({ type: 'turn_started', user_message: '他クライアントから' }), '1');
    expect(userBubbles().length).toBe(1);
    es.emit('message', JSON.stringify({ type: 'text_delta', content: 'リモート応答' }), '2');
    await raf();
    expect(bubbles().length).toBe(2);
    es.emit('message', JSON.stringify({ type: 'done', message: 'completed' }), '3');
    expect(N.Chat.state.streaming).toBe(false);
    expect(N.Chat.history.restore).toHaveBeenCalledWith(false);
  });

  it('swallows the page-load backlog burst until its terminal event, then renders live turns', async () => {
    const es = chatStream();
    es.onopen(); // connect-time burst begins while the tab is idle
    // history restore already displayed this turn — hub replays it on connect
    const restored = document.createElement('div');
    restored.className = 'chat-msg user';
    restored.innerHTML = '<div class="chat-bubble">復元済みの発言</div>';
    document.getElementById('chat-messages').appendChild(restored);
    es.emit('message', JSON.stringify({ type: 'turn_started', user_message: '復元済みの発言' }), '1');
    expect(userBubbles().length).toBe(1); // no duplicate from the burst
    es.emit('message', JSON.stringify({ type: 'text_delta', content: '過去の応答' }), '2');
    await raf();
    expect(bubbles().length).toBe(1); // backlog deltas drop while idle
    // the burst's terminal event ends skip mode and re-syncs the viewer
    es.emit('message', JSON.stringify({ type: 'done', message: 'completed' }), '3');
    expect(N.Chat.history.restore).toHaveBeenCalledWith(false);
    // a LIVE remote turn after the burst renders normally
    es.emit('message', JSON.stringify({ type: 'turn_started', user_message: '生きターン' }), '4');
    expect(userBubbles().length).toBe(2);
    es.emit('message', JSON.stringify({ type: 'text_delta', content: 'ライブ応答' }), '5');
    await raf();
    expect(bubbles()[2].textContent).toBe('ライブ応答');
  });

  it('never swallows a live remote turn just because its text repeats the last user bubble', async () => {
    const es = chatStream();
    // no connect burst pending — viewer is watching (skip mode already cleared)
    const restored = document.createElement('div');
    restored.className = 'chat-msg user';
    restored.innerHTML = '<div class="chat-bubble">こんにちは</div>';
    document.getElementById('chat-messages').appendChild(restored);
    // the other client sends the SAME text again (retry / repeat)
    es.emit('message', JSON.stringify({ type: 'turn_started', user_message: 'こんにちは' }), '10');
    expect(userBubbles().length).toBe(2); // rendered, not swallowed
    es.emit('message', JSON.stringify({ type: 'text_delta', content: '返事' }), '11');
    await raf();
    expect(bubbles()[2].textContent).toBe('返事');
    es.emit('message', JSON.stringify({ type: 'done', message: 'completed' }), '12');
    expect(N.Chat.history.restore).toHaveBeenCalledWith(false);
  });

  it('backlog with several turns: burst ends at its first done, next turn renders live', async () => {
    const es = chatStream();
    es.onopen();
    es.emit('message', JSON.stringify({ type: 'turn_started', user_message: '過去1' }), '20');
    es.emit('message', JSON.stringify({ type: 'text_delta', content: 'A' }), '21');
    es.emit('message', JSON.stringify({ type: 'done', message: 'completed' }), '22');
    expect(N.Chat.history.restore).toHaveBeenCalledWith(false);
    expect(userBubbles().length).toBe(0); // burst still swallowed up to here
    es.emit('message', JSON.stringify({ type: 'turn_started', user_message: '過去2' }), '23');
    es.emit('message', JSON.stringify({ type: 'text_delta', content: 'B' }), '24');
    await raf();
    expect(userBubbles().length).toBe(1); // rendered (transient duplicate is acceptable)
    expect(bubbles()[1].textContent).toBe('B');
    es.emit('message', JSON.stringify({ type: 'done', message: 'completed' }), '25');
    expect(N.Chat.history.restore).toHaveBeenCalledTimes(2);
  });
});
