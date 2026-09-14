/* =================================================================
   chat-mode.js unit tests — mode toggle, localStorage persistence,
   nous:chat-sse consumption (talking / done→emotion mapping).
   avatar handle is mocked; fetch is stubbed.
   ================================================================= */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const fakeAvatar = {
  setExpression: vi.fn(),
  setTalking: vi.fn(),
  dispose: vi.fn(),
};

vi.mock('./avatar/avatar.js', () => ({
  initAvatar: vi.fn(() => Promise.resolve(fakeAvatar)),
}));

let chatMode;

beforeEach(async () => {
  vi.resetModules();
  localStorage.clear();
  document.body.innerHTML = `
    <div id="chat-main">
      <div id="chat-avatar-layer" hidden>
        <div id="chat-avatar-canvas-container"></div>
      </div>
      <div id="chat-messages"></div>
    </div>
    <button id="chat-mode-toggle-btn"></button>
    <select id="chat-avatar-model-select"></select>
  `;
  window.S = { persona: 'p1' };
  chatMode = await import('./avatar/chat-mode.js');
});

afterEach(() => {
  vi.useRealTimers();
  vi.clearAllMocks();
  document.body.innerHTML = '';
});

describe('toggleCharacterMode', () => {
  it('adds character-mode class and persists to localStorage', async () => {
    await chatMode.toggleCharacterMode();
    expect(document.getElementById('chat-main').classList.contains('character-mode')).toBe(true);
    expect(localStorage.getItem('nous.chatMode')).toBe('character');
    expect(document.getElementById('chat-avatar-layer').hidden).toBe(false);
  });

  it('toggles back to normal: class removed, avatar disposed, persisted', async () => {
    await chatMode.toggleCharacterMode();
    await chatMode.toggleCharacterMode();
    expect(document.getElementById('chat-main').classList.contains('character-mode')).toBe(false);
    expect(localStorage.getItem('nous.chatMode')).toBe('normal');
    expect(fakeAvatar.dispose).toHaveBeenCalled();
    expect(document.getElementById('chat-avatar-layer').hidden).toBe(true);
  });

  it('re-entering character mode re-inits avatar', async () => {
    await chatMode.toggleCharacterMode();
    await chatMode.toggleCharacterMode();
    await chatMode.toggleCharacterMode();
    const { initAvatar } = await import('./avatar/avatar.js');
    expect(initAvatar).toHaveBeenCalledTimes(2);
  });
});

describe('handleChatSse', () => {
  it('ignores events when avatar is not initialized', () => {
    expect(() => chatMode.handleChatSse('text_delta', {})).not.toThrow();
    expect(fakeAvatar.setTalking).not.toHaveBeenCalled();
  });

  it('text_delta triggers setTalking(true) and 2s idle auto-stop', async () => {
    vi.useFakeTimers();
    await chatMode.toggleCharacterMode();
    fakeAvatar.setTalking.mockClear();
    chatMode.handleChatSse('text_delta', {});
    expect(fakeAvatar.setTalking).toHaveBeenLastCalledWith(true);
    await vi.advanceTimersByTimeAsync(2000);
    expect(fakeAvatar.setTalking).toHaveBeenLastCalledWith(false);
  });

  it('error stops talking', async () => {
    await chatMode.toggleCharacterMode();
    fakeAvatar.setTalking.mockClear();
    chatMode.handleChatSse('error', {});
    expect(fakeAvatar.setTalking).toHaveBeenCalledWith(false);
  });
});

describe('nous:chat-sse CustomEvent consumption', () => {
  it('done fetches emotion and maps to expression', async () => {
    await chatMode.toggleCharacterMode();
    fakeAvatar.setExpression.mockClear();
    const fetchMock = vi.fn(() =>
      Promise.resolve({ ok: true, json: () => Promise.resolve({ context: { emotion: 'joy' } }) })
    );
    vi.stubGlobal('fetch', fetchMock);
    document.dispatchEvent(new CustomEvent('nous:chat-sse', { detail: { type: 'done', data: {} } }));
    await vi.waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith('/api/dashboard/p1');
      expect(fakeAvatar.setExpression).toHaveBeenCalledWith('happy', 0.7);
    });
    vi.unstubAllGlobals();
  });

  it('maps sadness/anger/surprise and unknown → neutral', async () => {
    await chatMode.toggleCharacterMode();
    const cases = [
      ['sadness', 'sad'],
      ['anger', 'angry'],
      ['surprise', 'surprised'],
      ['fear', 'surprised'],
      ['mystery', 'neutral'],
    ];
    for (const [raw, mapped] of cases) {
      fakeAvatar.setExpression.mockClear();
      vi.stubGlobal(
        'fetch',
        vi.fn(() => Promise.resolve({ ok: true, json: () => Promise.resolve({ context: { emotion: raw } }) }))
      );
      document.dispatchEvent(new CustomEvent('nous:chat-sse', { detail: { type: 'done', data: {} } }));
      await vi.waitFor(() => expect(fakeAvatar.setExpression).toHaveBeenCalledWith(mapped, 0.7));
      vi.unstubAllGlobals();
    }
  });

  it('does not crash without the CustomEvent or with malformed detail', () => {
    expect(() => document.dispatchEvent(new Event('nous:chat-sse'))).not.toThrow();
    expect(() => document.dispatchEvent(new CustomEvent('nous:chat-sse', { detail: {} }))).not.toThrow();
  });
});
