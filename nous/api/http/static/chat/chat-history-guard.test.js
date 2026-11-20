/* =================================================================
   Regression: chat-history segment rendering must degrade gracefully.
   Without DOMPurify (CDN blocked), safeSetHTML falls back to textContent,
   so sanitizer-built nodes (e.g. .chat-thinking-body) are absent —
   restoreChatHistory must skip the segment, not fail the whole restore.
   ================================================================= */
import { loadCore, loadFile } from '../core/load-core.js';

/* session.js captures C.showConfirm at load (var showConfirm = C.showConfirm),
   so the stub is installed in beforeAll BEFORE history/*.js load — and it must
   be MUTABLE (confirmAnswer), not an `async () => true` literal, to test the
   cancel path. A fixed stub silently passes even if clear() drops files on
   cancel (caught in review round 2). */
let confirmAnswer = true;
let confirmCalls = 0;
let toastCalls = [];
let apiCalls = [];

beforeAll(() => {
  loadCore();
  // Minimal chat shell expected by chat-history.js at load time.
  window.S = { persona: 'test-persona' };
  window.Nous.Chat = window.Nous.Chat || {};
  window.Nous.Chat.state = { messages: [], attachments: [] };
  // session.js captures C.showConfirm at load, so the stub must exist BEFORE
  // history/*.js chunks are loaded (see note above the import).
  window.Nous.Core.showConfirm = async () => {
    confirmCalls++;
    return confirmAnswer;
  };
  window.Nous.Core.toast = (msg, kind) => { toastCalls.push({ msg, kind }); }; // captured as var toast = C.toast
  // getChatSessionId() returns fixed "main" → clear() always DELETEs; stub it.
  window.fetch = async () => ({ ok: true });
  window.Nous.Chat.markdown = { render: (s) => String(s) };
  window.Nous.Chat.ui = {
    append(role, content, time) {
      const container = document.getElementById('chat-messages');
      const div = document.createElement('div');
      div.className = 'chat-msg ' + role;
      const bubble = document.createElement('div');
      bubble.className = 'chat-bubble';
      bubble.textContent = content;
      const t = document.createElement('div');
      t.className = 'chat-time';
      if (time) t.textContent = time;
      div.appendChild(bubble);
      div.appendChild(t);
      container.appendChild(div);
    },
  };
  // Stub API before chat-history.js captures the reference at load.
  window.Nous.Core.api = async (url, opts) => {
    apiCalls.push({ url, opts });
    return ({
    messages: [
      {
        role: 'assistant', id: 'm1', time: 'now',
        segments: [{ type: 'thinking', content: 'covert reasoning' }],
      },
      { role: 'user', id: 'm2', time: 'now', content: 'hello' },
    ],
    total: 2,
    });
  };
  // chat-history.js split into history/*.js — load chunks in order
  // (reader path only; test logic unchanged).
  // #107: clear() delegates to the real attachments.clear — load the owner
  // module first so N.Chat.attachments exists.
  loadFile('../chat/chat-attachments.js');
  for (const f of ['history/render.js', 'history/session.js', 'history/restore.js']) {
    loadFile('../chat/' + f);
  }
});

beforeEach(() => {
  confirmAnswer = true;
  confirmCalls = 0;
  document.body.innerHTML =
    '<div id="chat-messages"></div><div id="chat-status"></div>';
  window.Nous.Chat.state.messages = [];
});

describe('restoreChatHistory degradation', () => {
  it('restores history with thinking segments and no DOMPurify (no throw)', async () => {
    expect(typeof DOMPurify).toBe('undefined');
    await expect(
      window.Nous.Chat.history.restore(false),
    ).resolves.toBeUndefined();
    const container = document.getElementById('chat-messages');
    // Restore did not fail wholesale: the user bubble is rendered.
    expect(
      container.querySelector('.chat-msg.user .chat-bubble').textContent,
    ).toBe('hello');
  });
});

/* =================================================================
   Regression (#107): clear() must wipe #chat-attachments in BOTH paths.
   Badges carry no id (class-rendered), so the old getElementById hunt
   never fired. The clear runs before the empty-history early return,
   otherwise a badge-only state (no messages yet) survives the clear and
   the staged files silently attach to the next message.
   ================================================================= */
describe('clear() attachment badge cleanup (#107)', () => {
  beforeEach(() => {
    document.body.innerHTML =
      '<div id="chat-messages"></div><div id="chat-status"></div>' +
      '<div id="chat-attachments"></div>';
    window.Nous.Chat.state.messages = [];
    window.Nous.Chat.state.attachments = [];
  });

  const stageBadge = () => {
    window.Nous.Chat.state.attachments.push({ filename: 'a.png' });
    document.getElementById('chat-attachments').appendChild(
      document.createElement('div'),
    );
  };

  it('clears badge-only state without confirm (empty-history early return)', async () => {
    stageBadge();
    await window.Nous.Chat.history.clear();
    expect(document.getElementById('chat-attachments').children.length).toBe(0);
    expect(window.Nous.Chat.state.attachments.length).toBe(0);
    expect(confirmCalls).toBe(0); // no history → no dialog
  });

  it('clears attachments area after confirmed clear (messages present)', async () => {
    window.Nous.Chat.state.messages.push({ role: 'user', content: 'x' });
    stageBadge();
    await window.Nous.Chat.history.clear();
    expect(confirmCalls).toBe(1);
    expect(document.getElementById('chat-attachments').children.length).toBe(0);
    expect(window.Nous.Chat.state.attachments.length).toBe(0);
    expect(window.Nous.Chat.state.messages.length).toBe(0);
    // DOMPurify is absent here, so safeSetHTML falls back to textContent — a
    // non-empty text means resetToWelcome actually rendered.
    expect(document.getElementById('chat-messages').textContent).not.toBe('');
  });

  /* Review round 2 blocker: clearing before confirm dropped staged files even
     on cancel. Clear must run AFTER `if (!ok) return`, so cancel keeps both
     the state entries and the rendered badges (incl. their File refs). */
  it('keeps staged attachments when confirm is cancelled', async () => {
    window.Nous.Chat.state.messages.push({ role: 'user', content: 'x' });
    stageBadge();
    confirmAnswer = false;
    await window.Nous.Chat.history.clear();
    expect(confirmCalls).toBe(1);
    expect(window.Nous.Chat.state.attachments.length).toBe(1);
    expect(document.getElementById('chat-attachments').children.length).toBe(1);
    expect(window.Nous.Chat.state.messages.length).toBe(1);
    // Guard the view too: resetToWelcome must not run on cancel (same
    // textContent fallback trick as the confirmed-clear test above).
    expect(document.getElementById('chat-messages').textContent).toBe('');
  });
});

/* =================================================================
   Regression (#105): the numeric-index guard used one misleading
   「応答処理中」 toast for two distinct failure modes. An element that is
   gone from the DOM (e.g. after a list re-render) must report
   「見つかりません」; only a present element with an empty data-msg-id
   (response still streaming, id not yet assigned) may say 「応答処理中」.
   A present element with a msgId must resolve to the UUID and reach the API.
   ================================================================= */
describe('numeric-index guard toasts (#105)', () => {
  const msgDiv = (index, id) => {
    const d = document.createElement('div');
    d.className = 'chat-msg assistant';
    d.dataset.msgIndex = String(index);
    if (id !== undefined) d.dataset.msgId = id;
    document.getElementById('chat-messages').appendChild(d);
    return d;
  };

  beforeEach(() => {
    apiCalls = [];
    toastCalls = [];
  });

  it('missing element reports 見つかりません, not 応答処理中, and skips the API', async () => {
    await window.Nous.Chat.history.rollback(0, false);
    expect(toastCalls.length).toBe(1);
    expect(toastCalls[0].msg).toContain('見つかりません');
    expect(apiCalls.length).toBe(0);
  });

  it('present element with empty msgId (streaming) keeps the 応答処理中 toast', async () => {
    msgDiv(0, '');
    await window.Nous.Chat.history.rollback(0, false);
    expect(toastCalls.length).toBe(1);
    expect(toastCalls[0].msg).toContain('応答処理中');
    expect(apiCalls.length).toBe(0);
  });

  it('present element with msgId resolves to the UUID and reaches the rollback API', async () => {
    msgDiv(0, 'uuid-abc');
    await window.Nous.Chat.history.rollback(0, false);
    expect(toastCalls.length).toBe(1);
    expect(toastCalls[0].msg).toContain('ロールバックしました');
    expect(toastCalls[0].kind).toBe('info');
    expect(apiCalls.length).toBe(1);
    expect(apiCalls[0].url).toContain('/rollback');
    expect(apiCalls[0].url).toContain('/rollback');
    expect(JSON.parse(apiCalls[0].opts.body).from_id).toBe('uuid-abc');
  });
});

/* =================================================================
   Regression (#120): history-mutation cleanup called a module-local
   `_endSession` via `typeof _endSession === "function"` — always
   undefined from session.js, and N.Chat.tts never exported it either,
   so TTS playback kept running after clear/rollback/delete. Fixed by
   exporting endSession on N.Chat.tts and calling through the namespace.
   ================================================================= */
describe('TTS session cleanup on history mutation (#120)', () => {
  let endSessionCalls;

  beforeEach(() => {
    document.body.innerHTML =
      '<div id="chat-messages"></div><div id="chat-status"></div>' +
      '<div id="chat-attachments"></div>';
    window.Nous.Chat.state.messages = [{ role: 'user', content: 'x' }];
    window.Nous.Chat.state.attachments = [];
    confirmAnswer = true;
    endSessionCalls = 0;
    window.Nous.Chat.tts = {
      endSession: () => {
        endSessionCalls++;
      },
    };
  });

  // The spy pollutes the shared window across describes: #105's rollback
  // test was written against a bare `N.Chat.tts` (undefined) and its toast
  // expectations flip when our stub survives. Drop it after each test.
  afterEach(() => {
    delete window.Nous.Chat.tts;
  });

  it('exports endSession on N.Chat.tts (the old code never did)', () => {
    loadFile('../chat/chat-tts.js');
    expect(typeof window.Nous.Chat.tts.endSession).toBe('function');
  });

  it('clear() stops TTS playback via N.Chat.tts.endSession', async () => {
    await window.Nous.Chat.history.clear();
    expect(endSessionCalls).toBeGreaterThan(0);
  });

  it('rollback() stops TTS playback before DOM rebuild', async () => {
    const d = document.createElement('div');
    d.className = 'chat-msg assistant';
    d.dataset.msgIndex = '0';
    d.dataset.msgId = 'uuid-1';
    document.getElementById('chat-messages').appendChild(d);
    await window.Nous.Chat.history.rollback(0, false);
    expect(endSessionCalls).toBeGreaterThan(0);
  });
});
