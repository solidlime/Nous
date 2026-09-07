/* =================================================================
   Regression: a concurrent restore call rejected by the restore lock
   must NOT bump the generation counter — otherwise the in-flight
   restore's response fails the freshness check and is silently
   discarded (page-load backlog: loadChat's restore(true) races the
   chat-events hub replay's restore(false) from _syncAfterForeignDone,
   leaving the welcome screen and no console error).
   ================================================================= */
import { loadCore, loadFile } from '../core/load-core.js';

let apiImpl = async () => ({ messages: [], total: 0 });

beforeAll(() => {
  loadCore();
  window.S = { persona: 'test-persona' };
  window.Nous.Chat = window.Nous.Chat || {};
  window.Nous.Chat.state = { messages: [], attachments: [] };
  window.Nous.Chat.markdown = { render: (s) => String(s) };
  window.Nous.Chat.ui = {
    append(role, content, time) {
      const container = document.getElementById('chat-messages');
      const div = document.createElement('div');
      div.className = 'chat-msg ' + role;
      const bubble = document.createElement('div');
      bubble.className = 'chat-bubble';
      bubble.textContent = content;
      div.appendChild(bubble);
      container.appendChild(div);
    },
  };
  // Controllable API stub — chat-history.js captures C.api at load time.
  window.Nous.Core.api = (...args) => apiImpl(...args);
  loadFile('../chat/chat-history.js');
});

beforeEach(() => {
  document.body.innerHTML =
    '<div id="chat-messages"></div><div id="chat-status"></div>';
  window.Nous.Chat.state.messages = [];
});

const MESSAGES = [
  { role: 'user', id: 'm1', time: 'now', content: 'first' },
  { role: 'assistant', id: 'm2', time: 'now', content: 'second' },
];

describe('restore race: lock-rejected call keeps generation intact', () => {
  it('renders the in-flight restore even when a second call was lock-rejected', async () => {
    let resolveFetch;
    apiImpl = () =>
      new Promise((res) => {
        resolveFetch = res;
      });

    // Call 1: holds the restore lock while its fetch is pending.
    const p1 = window.Nous.Chat.history.restore(false);
    // Call 2: arrives while call 1 is in flight. It is rejected by the
    // lock — but must not invalidate call 1's generation.
    const p2 = window.Nous.Chat.history.restore(false);

    resolveFetch({ messages: MESSAGES, total: 2 });
    await p1;
    await p2;

    const container = document.getElementById('chat-messages');
    const rendered = container.querySelectorAll('.chat-msg');
    expect(rendered.length).toBe(2);
    expect(
      container.querySelector('.chat-msg.user .chat-bubble').textContent,
    ).toBe('first');
  });

  it('still invalidates a superseded restore after the lock is released (guard preserved)', async () => {
    let resolveA;
    let callCount = 0;
    apiImpl = () =>
      new Promise((res) => {
        if (callCount === 0) resolveA = res;
        callCount++;
      });

    // A in flight; B must queue-behind via the lock (bumped gen) and
    // render its own (newer) data once A completes.
    const pa = window.Nous.Chat.history.restore(false);
    const pb = window.Nous.Chat.history.restore(false);

    // A's response arrives with stale data and gets superseded.
    resolveA({ messages: [{ role: 'user', id: 'old', time: 't', content: 'stale' }], total: 1 });
    await pa;

    // Lock is free now — let B's fetch resolve with fresh data.
    await new Promise((r) => setTimeout(r, 0));
    apiImpl = async () => ({ messages: MESSAGES, total: 2 });
    // Re-run restore to simulate B's own fetch completing (lock released).
    await window.Nous.Chat.history.restore(false);
    await pb;

    const container = document.getElementById('chat-messages');
    // Latest restore wins: stale content must not linger.
    expect(container.textContent).not.toContain('stale');
    expect(
      container.querySelector('.chat-msg.user .chat-bubble').textContent,
    ).toBe('first');
  });
});
