/* =================================================================
   Regression: chat-history segment rendering must degrade gracefully.
   Without DOMPurify (CDN blocked), safeSetHTML falls back to textContent,
   so sanitizer-built nodes (e.g. .chat-thinking-body) are absent —
   restoreChatHistory must skip the segment, not fail the whole restore.
   ================================================================= */
import { loadCore, loadFile } from '../core/load-core.js';

beforeAll(() => {
  loadCore();
  // Minimal chat shell expected by chat-history.js at load time.
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
  loadFile('../chat/chat-history.js');
});

beforeEach(() => {
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
