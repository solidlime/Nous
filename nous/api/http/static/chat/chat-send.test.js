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

function tick() {
  return new Promise((resolve) => setTimeout(resolve, 0));
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
  // rawFetch passes through to the (fetchMock-stubbed) global fetch so
  // attachment text reads keep working through the api wrapper (#123)
  N.Core.api.rawFetch = vi.fn((path, opts) => fetch(path, opts));
  N.Chat = {
    state: { messages: [], streaming: false, attachments: [] },
    // 整形結果を検知できるよう、素のテキストとは違う HTML を返す
    markdown: { render: (s) => '<p>' + s + '</p>' },
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
    attachments: { openViewer: vi.fn(), clear: vi.fn(() => { N.Chat.state.attachments = []; }) },
    showCharacterFlag: vi.fn(),
  };
  // chat-send.js split into send/*.js — load chunks in order
  // (reader path only; test logic unchanged).
  for (const f of ['send/render.js', 'send/turn.js', 'send/pending.js', 'send/turn-events.js']) {
    loadFile('../chat/' + f);
  }
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
  N.Chat.attachments.clear.mockClear();
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
    // Stage an attachment: the payload must be built BEFORE clear() wipes
    // the staged list — if clear ran first the attachment block would
    // silently vanish from the outgoing message (#106 review round 3).
    N.Chat.state.attachments = [
      { filename: 'a.txt', url: '/a.txt', workspace_path: 'a.txt', mime_type: 'text/plain' },
    ];
    await sendTurn('こんにちは');
    expect(N.Core.api).toHaveBeenCalledWith(
      '/api/chat/p1',
      expect.objectContaining({ method: 'POST' }),
    );
    const body = JSON.parse(N.Core.api.mock.calls[0][1].body);
    expect(body.message).toContain('こんにちは');
    expect(body.message).toContain('[添付ファイル: a.txt]');
    expect(N.Chat.state.attachments.length).toBe(0); // clear did run
    expect(body.session_id).toBe('main');
    // sending clears staged attachments (send/pending.js)
    expect(N.Chat.attachments.clear).toHaveBeenCalledTimes(1);
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
    // done で最終 markdown 描画
    expect(bubbles()[1].innerHTML).toBe('<p>げんきだよ</p>');
  });

  it('keeps the finalized markdown when a delta and done land in the same frame', async () => {
    const es = chatStream();
    await sendTurn('整形して');
    es.emit('message', JSON.stringify({ type: 'turn_started', user_message: '整形して', session_id: 'main' }), '1');
    // 同じタスクで text_delta と done — delta の rAF はまだ発火していない
    es.emit('message', JSON.stringify({ type: 'text_delta', content: '**太字**' }), '2');
    es.emit('message', JSON.stringify({ type: 'done', message: 'completed' }), '3');
    await raf();
    await raf();
    expect(bubbles()[1].innerHTML).toBe('<p>**太字**</p>');
  });

  it('409 holds the message, shows one info toast, and retries after the backoff', async () => {
    vi.useFakeTimers();
    chatStream();
    const conflict = new Error('Conflict');
    conflict.status = 409;
    N.Core.api.mockRejectedValueOnce(conflict);
    document.getElementById('chat-input').value = '二重送信';
    await N.Chat.send();
    // no error toast and no stranded user bubble — a calm info toast only
    expect(N.Core.toast.mock.calls.some((c) => String(c[0]).indexOf('送信失敗') !== -1)).toBe(false);
    expect(N.Core.toast.mock.calls.some((c) => String(c[0]).indexOf('処理が終わってから') !== -1)).toBe(true);
    expect(N.Chat.state.streaming).toBe(false);
    expect(document.getElementById('chat-send-btn').style.display).toBe('');
    expect(document.getElementById('chat-input').value).toBe('二重送信');
    expect(userBubbles().length).toBe(0);
    // the backoff retry fires and registers the turn
    N.Core.api.mockResolvedValueOnce({ turn_id: 't2' });
    await vi.advanceTimersByTimeAsync(2100);
    expect(N.Core.api).toHaveBeenCalledTimes(2);
    vi.useRealTimers();
  });

  it('holds a send made while a turn is streaming and flushes it on done', async () => {
    const es = chatStream();
    document.getElementById('chat-input').value = 'ひとつめ';
    N.Core.api.mockResolvedValueOnce({ turn_id: 't1' });
    await N.Chat.send();
    expect(N.Chat.state.streaming).toBe(true);
    // second message while the turn is live → held, not dropped
    document.getElementById('chat-input').value = 'ふたつめ';
    await N.Chat.send();
    expect(N.Core.api).toHaveBeenCalledTimes(1);
    expect(userBubbles().length).toBe(1);
    // the turn ends → the held message goes out
    N.Core.api.mockResolvedValueOnce({ turn_id: 't2' });
    es.emit('message', JSON.stringify({ type: 'done', message: 'completed', user_msg_id: 'u1', assistant_msg_id: 'a1' }), '1');
    expect(N.Core.api).toHaveBeenCalledTimes(2);
    const body = JSON.parse(N.Core.api.mock.calls[1][1].body);
    expect(body.message).toBe('ふたつめ');
  });

  it('clears a held message when draining fails with a non-409 error (no silent resend)', async () => {
    const es = chatStream();
    document.getElementById('chat-input').value = 'ひとつめ';
    N.Core.api.mockResolvedValueOnce({ turn_id: 't1' });
    await N.Chat.send();
    document.getElementById('chat-input').value = 'ふたつめ';
    await N.Chat.send(); // held while streaming
    expect(N.Core.api).toHaveBeenCalledTimes(1);
    // the turn ends → the held send drains and fails with 500
    const boom = new Error('Server Error');
    boom.status = 500;
    N.Core.api.mockRejectedValueOnce(boom);
    es.emit('message', JSON.stringify({ type: 'done', message: 'completed', user_msg_id: 'u1', assistant_msg_id: 'a1' }), '1');
    await tick();
    // the failure is visible, no stranded bubble, input restored
    expect(N.Core.toast.mock.calls.some((c) => String(c[0]).indexOf('送信失敗') !== -1)).toBe(true);
    expect(document.getElementById('chat-input').value).toBe('ふたつめ');
    expect(userBubbles().length).toBe(1); // only 'ひとつめ'
    // a later terminal event must NOT silently resend it
    N.Core.api.mockResolvedValueOnce({ turn_id: 't9' });
    es.emit('message', JSON.stringify({ type: 'done', message: 'completed' }), '2');
    await tick();
    expect(N.Core.api).toHaveBeenCalledTimes(2);
  });

  it('recovers a turn stuck >60s and sends instead of re-queueing forever', async () => {
    chatStream();
    document.getElementById('chat-input').value = 'ひとつめ';
    N.Core.api.mockResolvedValueOnce({ turn_id: 't1' });
    await N.Chat.send();
    expect(N.Chat.state.streaming).toBe(true);
    // simulate a stuck turn: no terminal event for >60s
    N.Chat.state._streamingSince = Date.now() - 61000;
    document.getElementById('chat-input').value = 'ふたつめ';
    N.Core.api.mockResolvedValueOnce({ turn_id: 't2' });
    await N.Chat.send();
    expect(N.Core.api).toHaveBeenCalledTimes(2);
    const body = JSON.parse(N.Core.api.mock.calls[1][1].body);
    expect(body.message).toBe('ふたつめ');
  });

  it('attachment-only send queued while streaming keeps a mid-wait draft', async () => {
    const es = chatStream();
    document.getElementById('chat-input').value = 'ひとつめ';
    N.Core.api.mockResolvedValueOnce({ turn_id: 't1' });
    await N.Chat.send();
    // attachment-only second send while the turn is live
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ text: () => Promise.resolve('hello') }));
    N.Chat.state.attachments = [
      { filename: 'a.txt', url: '/a.txt', workspace_path: 'a.txt', mime_type: 'text/plain' },
    ];
    await N.Chat.send();
    // user types while waiting
    document.getElementById('chat-input').value = '下書き';
    // the turn ends → the held attachment-only message goes out
    N.Core.api.mockResolvedValueOnce({ turn_id: 't2' });
    es.emit('message', JSON.stringify({ type: 'done', message: 'completed', user_msg_id: 'u1', assistant_msg_id: 'a1' }), '1');
    expect(N.Core.api).toHaveBeenCalledTimes(2);
    const body = JSON.parse(N.Core.api.mock.calls[1][1].body);
    expect(body.message).toContain('--- 添付: a.txt ---');
    // the mid-wait draft survives
    expect(document.getElementById('chat-input').value).toBe('下書き');
  });

  it('replays missed events on reconnect via last_seq', async () => {
    vi.useFakeTimers();
    const es = chatStream();
    await sendTurn('つづき');
    es.emit('message', JSON.stringify({ type: 'turn_started', user_message: 'つづき' }), 'e1a:1');
    es.emit('message', JSON.stringify({ type: 'text_delta', content: '途中まで' }), 'e1a:2');
    // connection drops — sse.js reconnects with the epoch-tagged last_seq
    // （サーバー側 _parse_last_seq が epoch 不一致で全量 replay するための基線）
    es.onerror();
    // 5000ms backoff only（watchdog interval を無限進行させる runAllTimers は使わない）
    await vi.advanceTimersByTimeAsync(5000);
    vi.useRealTimers(); // jsdom rAF rides real timers
    const reconnect = instances[instances.length - 1];
    expect(reconnect.url).toBe('/api/chat/p1/events?last_seq=e1a:2');
    // replayed duplicates are dropped (bubble content unchanged); genuinely
    // new deltas continue the same bubble
    await raf();
    expect(bubbles()[1].textContent).toBe('途中まで');
    reconnect.emit('message', JSON.stringify({ type: 'text_delta', content: '＋追加分' }), 'e1a:3');
    await raf();
    expect(bubbles()[1].textContent).toBe('途中まで＋追加分');
  });

  it('recovers an orphaned turn when the server restarts (epoch change)', async () => {
    vi.useFakeTimers();
    const es = chatStream();
    await sendTurn('たのんだ');
    es.emit('message', JSON.stringify({ type: 'turn_started', user_message: 'たのんだ' }), 'e1a:1');
    es.emit('message', JSON.stringify({ type: 'text_delta', content: '途中' }), 'e1a:2');
    // server restarts mid-turn: SSE drops, reconnects, and the first event
    // under the NEW epoch is a foreign turn — our own turn's events are gone
    es.onerror();
    await vi.advanceTimersByTimeAsync(5000);
    vi.useRealTimers();
    const reconnect = instances[instances.length - 1];
    expect(reconnect.url).toBe('/api/chat/p1/events?last_seq=e1a:2');
    reconnect.emit('message', JSON.stringify({ type: 'turn_started', user_message: 'よそのクライアント' }), 'e9f:1');
    await raf();
    // orphan recovery: turn state closed, status cleared, error toast,
    // history reload — and the user's input is never silently lost
    expect(N.Chat._send.turn()).toBe(null);
    expect(N.Core.toast).toHaveBeenCalledWith(
      expect.stringContaining('再起動'), 'error');
    expect(window.Nous.Chat.history.restore).toHaveBeenCalledWith(false);
    expect(document.getElementById('chat-status').textContent).toBe('');
    // この first event 自体は epoch 切替の合図として消費される — 同一 event で
    // ユーザーバブルは作らない（履歴 restore が実物を再構築する）。
    expect(userBubbles().length).toBe(1); // own echo only
    // 新 epoch の以後の event は viewer 语义で普通に描画される
    reconnect.emit('message', JSON.stringify({ type: 'turn_started', user_message: 'よそのクライアント2' }), 'e9f:2');
    await raf();
    reconnect.emit('message', JSON.stringify({ type: 'text_delta', content: 'よその返事' }), 'e9f:3');
    await raf();
    expect(userBubbles().length).toBe(2); // own echo + foreign #2
    expect(bubbles().length).toBeGreaterThanOrEqual(3); // + foreign assistant delta
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

  it('cancel stops local rendering without a server call and re-arms the composer', async () => {
    chatStream();
    await sendTurn('途中でやめる');
    expect(N.Chat.state.streaming).toBe(true);
    expect(document.getElementById('chat-cancel-btn').style.display).toBe('');
    expect(document.getElementById('chat-send-btn').style.display).toBe('none');

    N.Chat.cancel();

    expect(N.Chat.state.streaming).toBe(false);
    expect(document.getElementById('chat-status').textContent).toBe('中断しました');
    expect(document.getElementById('chat-cancel-btn').style.display).toBe('none');
    expect(document.getElementById('chat-send-btn').style.display).toBe('');
    expect(document.getElementById('chat-input').value).toBe('');
    expect(N.Core.api).toHaveBeenCalledTimes(1); // POST only — no cancel endpoint
  });
});

// ------------------------------------------------------------------
// #58: キャラ修復は done 後に届く — turn が閉じていても差し替える
// ------------------------------------------------------------------
describe('response_replaced after done', () => {
  it('replaces the bubble of the matching msg_id', () => {
    document.getElementById('chat-messages').innerHTML =
      '<div class="chat-msg assistant" data-msg-id="m1"><div class="chat-bubble">元の応答</div></div>';
    N.Chat._send.applyReplaceAfterTurn({ content: '修復済みの応答', assistant_msg_id: 'm1' });
    const bubble = document.querySelector('.chat-msg[data-msg-id="m1"] .chat-bubble');
    expect(bubble.textContent).toBe('修復済みの応答');
  });

  it('falls back to the last assistant message when msg_id is missing', () => {
    document.getElementById('chat-messages').innerHTML =
      '<div class="chat-msg assistant"><div class="chat-bubble">古い</div></div>' +
      '<div class="chat-msg assistant"><div class="chat-bubble">元の応答</div></div>';
    N.Chat._send.applyReplaceAfterTurn({ content: '差し替え後' });
    const nodes = document.querySelectorAll('.chat-msg.assistant .chat-bubble');
    expect(nodes[0].textContent).toBe('古い');
    expect(nodes[1].textContent).toBe('差し替え後');
  });

  it('does nothing when there is no assistant message', () => {
    document.getElementById('chat-messages').innerHTML = '';
    expect(() => N.Chat._send.applyReplaceAfterTurn({ content: 'x' })).not.toThrow();
  });
});

// ------------------------------------------------------------------
// サーバー再起動＝epoch 切替。素の seq 基線は再起動で 1 に巻き戻るため、
// 旧実装は再起動後の全イベントを「リプレイ重複」と誤判して凍った
// （2026-11-21 実機 freeze の直接原因）。id "<epoch>:<seq>" で基線の
// リセットを検出し、再起動を跨いだ turn は即回復する。
// ------------------------------------------------------------------
describe('epoch baseline (server restart recovery)', () => {
  it('restart resets the seq baseline instead of dropping new events', async () => {
    const es = chatStream();
    es.onopen(); // idle 接続直後 — burst swallow モード
    // 旧 epoch e1 で seq 5 まで見た（接続時バーストは swallow される）
    es.emit('message', JSON.stringify({ type: 'turn_started', user_message: '旧ターン' }), 'e1:4');
    es.emit('message', JSON.stringify({ type: 'done', message: '旧完了' }), 'e1:5');
    // サーバー再起動: 新 epoch で seq が 1 に戻る。旧実装では 1 <= 5 で
    // 全部落ちた（freeze の直接原因）
    es.emit('message', JSON.stringify({ type: 'turn_started', user_message: '再起動後' }), 'e2:1');
    expect(N.Chat.state.streaming).toBe(true);
    es.emit('message', JSON.stringify({ type: 'text_delta', content: '再起動後の応答' }), 'e2:2');
    await raf();
    expect(bubbles()[1].textContent).toBe('再起動後の応答');
    es.emit('message', JSON.stringify({ type: 'done', message: '完了' }), 'e2:3');
    expect(N.Chat.state.streaming).toBe(false);
  });

  it('bare numeric ids keep the legacy behavior (no epoch)', async () => {
    const es = chatStream();
    es.emit('message', JSON.stringify({ type: 'turn_started', user_message: 'a' }), '7');
    // duplicate seq 7 — dropped as replay, no crash
    es.emit('message', JSON.stringify({ type: 'done', message: 'dup' }), '7');
    expect(N.Chat.state.streaming).toBe(true);
    es.emit('message', JSON.stringify({ type: 'done', message: 'ok' }), '8');
    expect(N.Chat.state.streaming).toBe(false);
  });

  it('mid-turn restart: reconnect probe recovers the orphaned turn', async () => {
    vi.useFakeTimers();
    const es = chatStream();
    es.onopen();
    // 接続バーストを閉じる
    es.emit('message', JSON.stringify({ type: 'done', message: '旧' }), 'e1:1');
    // 自ターンを開始（e1 のまま進行中）
    await sendTurn('途中で落ちる');
    es.emit('message', JSON.stringify({ type: 'turn_started', user_message: '途中で落ちる' }), 'e1:2');
    es.emit('message', JSON.stringify({ type: 'text_delta', content: '途中まで' }), 'e1:3');
    expect(N.Chat.state.streaming).toBe(true);
    // 少し時間が流れてから SSE 落下 → 再接続完了（stub は onopen を自動発火しないので手動で呼ぶ）
    await vi.advanceTimersByTimeAsync(1000);
    es.onerror();
    N.Core.api.mockResolvedValueOnce({ epoch: 'e2' }); // epoch probe: 再起動済み
    es.onopen();
    await vi.advanceTimersByTimeAsync(0);
    expect(N.Core.toast).toHaveBeenCalledWith('サーバーが再起動されたため応答が途切れました', 'error');
    expect(N.Chat.state.streaming).toBe(false);
    expect(N.Chat.history.restore).toHaveBeenCalledWith(false);
    expect(document.getElementById('chat-status').textContent).toBe('');
    // probe 採用は seq 基線のリセットを伴うこと: 新 epoch の低 seq event が
    // 旧基線（この時点で 3）に握り潰されずに描画される（#136 の反実仮想）
    es.emit('message', JSON.stringify({ type: 'turn_started', user_message: '新epochの誰か' }), 'e2:1');
    vi.useRealTimers(); // jsdom rAF rides real timers
    await raf();
    expect(userBubbles().length).toBe(2); // 自ターンのエコー + 新epochの誰か
  });

  it('probe with a matching epoch leaves the live turn alone', async () => {
    vi.useFakeTimers();
    const es = chatStream();
    es.onopen();
    es.emit('message', JSON.stringify({ type: 'done', message: '旧' }), 'e1:1');
    await sendTurn('続行');
    es.emit('message', JSON.stringify({ type: 'turn_started', user_message: '続行' }), 'e1:2');
    await vi.advanceTimersByTimeAsync(1000);
    es.onerror();
    N.Core.api.mockResolvedValueOnce({ epoch: 'e1' }); // same epoch: 再起動していない
    es.onopen();
    await vi.advanceTimersByTimeAsync(0);
    expect(N.Core.toast.mock.calls.some((c) => String(c[0]).indexOf('再起動') !== -1)).toBe(false);
    expect(N.Chat.state.streaming).toBe(true); // turn keeps rendering
    vi.useRealTimers();
  });

  it('epoch change mid-own-turn (event path, not probe) recovers it too', async () => {
    const es = chatStream();
    es.onopen();
    es.emit('message', JSON.stringify({ type: 'done', message: '旧' }), 'e1:1');
    await sendTurn('イベント経路');
    es.emit('message', JSON.stringify({ type: 'turn_started', user_message: 'イベント経路' }), 'e1:2');
    // サーバー再起動後に他クライアントの turn が始まる → 新 epoch の id が届く
    es.emit('message', JSON.stringify({ type: 'turn_started', user_message: '別クライアント' }), 'e2:1');
    expect(N.Core.toast).toHaveBeenCalledWith('サーバーが再起動されたため応答が途切れました', 'error');
    expect(N.Chat.state.streaming).toBe(false);
  });
});

// ------------------------------------------------------------------
// done 後のステータス残留 — 最終 memory_activity が来ない場合の保険と、
// var 宣言欠落で memory_activity が ReferenceError を起こしていた回帰。
// ------------------------------------------------------------------
describe('post-done status lifecycle', () => {
  it('memory_activity after done clears the status without ReferenceError', async () => {
    const es = chatStream();
    await sendTurn('記憶');
    es.emit('message', JSON.stringify({ type: 'turn_started', user_message: '記憶' }), '1');
    es.emit('message', JSON.stringify({ type: 'done', message: 'ok' }), '2');
    expect(document.getElementById('chat-status').textContent).toBe('ちょっと考えてる…');
    es.emit('message', JSON.stringify({ type: 'memory_activity', retrieved: 1, saved: 1 }), '3');
    expect(document.getElementById('chat-status').textContent).toBe('');
  });

  it('status fallback clears a stranded ちょっと考えてる… after 30s', async () => {
    vi.useFakeTimers();
    const es = chatStream();
    await sendTurn('残留');
    es.emit('message', JSON.stringify({ type: 'turn_started', user_message: '残留' }), '1');
    es.emit('message', JSON.stringify({ type: 'done', message: 'ok' }), '2');
    expect(document.getElementById('chat-status').textContent).toBe('ちょっと考えてる…');
    await vi.advanceTimersByTimeAsync(30000);
    expect(document.getElementById('chat-status').textContent).toBe('');
    vi.useRealTimers();
  });

  it('watchdog recovers a turn that receives no events for 5 minutes', async () => {
    vi.useFakeTimers();
    const es = chatStream();
    es.emit('message', JSON.stringify({ type: 'done', message: '旧' }), '1');
    await sendTurn('無言');
    es.emit('message', JSON.stringify({ type: 'turn_started', user_message: '無言' }), '2');
    expect(N.Chat.state.streaming).toBe(true);
    await vi.advanceTimersByTimeAsync(610000);
    expect(N.Core.toast).toHaveBeenCalledWith('応答が途切れたため、このターンを打ち切り履歴を再取得しました', 'error');
    expect(N.Chat.state.streaming).toBe(false);
    vi.useRealTimers();
  });
});
