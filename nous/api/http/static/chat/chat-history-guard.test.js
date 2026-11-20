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
  window.Nous.Core.toast = () => {}; // captured as var toast = C.toast
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
  window.Nous.Core.api = async () => ({
    messages: [
      {
        role: 'assistant', id: 'm1', time: 'now',
        segments: [{ type: 'thinking', content: 'covert reasoning' }],
      },
      { role: 'user', id: 'm2', time: 'now', content: 'hello' },
    ],
    total: 2,
  });
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
