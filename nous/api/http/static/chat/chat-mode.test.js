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

/* リロード経路のリグレッション: ページ読込時点では S.persona が未設定（base.js が
   /api/personas の応答を待っている）。この間にアバターを初期化すると
   `/api/chat//avatar/model` を取得して 404 → fallback 画像になっていた。 */
describe('reload path: avatar init waits for the persona', () => {
  it('does not init while S.persona is empty, then inits once the persona is known', async () => {
    vi.resetModules();
    localStorage.clear();
    localStorage.setItem('nous.chatMode', 'character');
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
    window.S = { persona: '' };
    const { initAvatar } = await import('./avatar/avatar.js');
    initAvatar.mockClear();

    const mode = await import('./avatar/chat-mode.js');
    // 起動時の applyCharacterMode(true) は走るが、アバターは初期化されない
    expect(document.getElementById('chat-main').classList.contains('character-mode')).toBe(true);
    expect(initAvatar).not.toHaveBeenCalled();

    // ペルソナ確定後（chat-core.js の loadChat 経由）に初期化され、URL も正しい
    window.S.persona = 'herta';
    await mode.syncCharacterMode();
    expect(initAvatar).toHaveBeenCalledTimes(1);
    expect(initAvatar.mock.calls[0][1]).toBe('/api/chat/herta/avatar/model');

    // 同じペルソナでの再呼び出しは作り直さない（loadChat の多重呼び出し対策）
    await mode.syncCharacterMode();
    expect(initAvatar).toHaveBeenCalledTimes(1);
  });

  it('rebuilds the avatar when the persona changes', async () => {
    vi.resetModules();
    localStorage.clear();
    localStorage.setItem('nous.chatMode', 'character');
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
    window.S = { persona: 'herta' };
    const { initAvatar } = await import('./avatar/avatar.js');
    initAvatar.mockClear();
    const mode = await import('./avatar/chat-mode.js');

    // 起動時にペルソナが確定していれば初期化される
    await mode.syncCharacterMode();
    expect(initAvatar.mock.calls.map((c) => c[1])).toEqual(['/api/chat/herta/avatar/model']);

    // ペルソナが変わったら作り直す
    window.S.persona = 'other';
    await mode.syncCharacterMode();
    expect(initAvatar.mock.calls.map((c) => c[1])).toEqual([
      '/api/chat/herta/avatar/model',
      '/api/chat/other/avatar/model',
    ]);
  });

  /* モデル差し替え・アップロード経路は `disposeAvatar(); applyCharacterMode(true)` の順で
     呼ぶため、disposeAvatar() が avatarPersona を null に戻さないと「同じペルソナ」判定で
     早期 return し、差し替えたモデルが反映されない。 */
  it('re-inits the same persona after the mode is toggled off and on', async () => {
    vi.resetModules();
    localStorage.clear();
    localStorage.setItem('nous.chatMode', 'character');
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
    window.S = { persona: 'herta' };
    const { initAvatar } = await import('./avatar/avatar.js');
    initAvatar.mockClear();
    const mode = await import('./avatar/chat-mode.js');

    await mode.syncCharacterMode();
    expect(initAvatar).toHaveBeenCalledTimes(1);

    // OFF → disposeAvatar() → avatarPersona がリセットされる
    await mode.toggleCharacterMode();
    expect(localStorage.getItem('nous.chatMode')).toBe('normal');
    expect(document.getElementById('chat-main').classList.contains('character-mode')).toBe(false);

    // ON → ペルソナが同じでも作り直される
    await mode.toggleCharacterMode();
    expect(initAvatar).toHaveBeenCalledTimes(2);
    expect(initAvatar.mock.calls[1][1]).toBe('/api/chat/herta/avatar/model');
  });
});

describe('loadChat integration point', () => {
  it('exposes syncCharacterMode as window.Nous.Chat.mode.syncCharacterMode', async () => {
    vi.resetModules();
    localStorage.clear();
    localStorage.setItem('nous.chatMode', 'normal');
    const mode = await import('./avatar/chat-mode.js');
    // chat-core.js の loadChat() は N.Chat.mode.syncCharacterMode 経由で呼ぶ
    expect(window.Nous.Chat.mode.syncCharacterMode).toBe(mode.syncCharacterMode);
  });
});
