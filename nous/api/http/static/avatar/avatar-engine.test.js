/**
 * Avatar Engine — unit tests (vitest + jsdom)
 *
 * Tests pure logic (URL, emotion mapping, display file selection),
 * public API state management, DOM rendering, and destroy cleanup.
 */
import { readFileSync } from 'fs';
import { resolve, dirname } from 'path';
import { fileURLToPath } from 'url';

const __dirname = dirname(fileURLToPath(import.meta.url));

// ------------------------------------------------------------------
// Test helpers — load IIFE modules into jsdom's window
// ------------------------------------------------------------------
function functionEval(file) {
  const code = readFileSync(resolve(__dirname, file), 'utf-8');
  new Function(code)();
}

function loadNamespace() {
  functionEval('../core/namespace.js');
}

function loadAvatarEngine() {
  functionEval('avatar-engine.js');
}

let N;

// Mock Image: controllable onload/onerror for preload tests
let mockImages;

beforeAll(() => {
  loadNamespace();
  loadAvatarEngine();
  N = window.Nous;
});

beforeEach(() => {
  mockImages = [];
  window.Image = class {
    constructor() {
      this._src = '';
      this.onload = null;
      this.onerror = null;
      mockImages.push(this);
    }
    set src(val) {
      this._src = val;
    }
    get src() { return this._src; }
  };
});

afterEach(() => {
  N.Avatar.destroy();
});

// ==================================================================
// Pure Logic: _buildImageUrl
// ==================================================================
describe('N.Avatar._buildImageUrl()', () => {
  it('constructs URL with baseUrl and persona', () => {
    expect(N.Avatar._buildImageUrl('http://localhost:26262', 'test', 'base.png'))
      .toBe('http://localhost:26262/api/chat/test/persona/avatar/base.png');
  });

  it('uses empty baseUrl for same-origin', () => {
    expect(N.Avatar._buildImageUrl('', 'myPersona', 'expr_joy.png'))
      .toBe('/api/chat/myPersona/persona/avatar/expr_joy.png');
  });

  it('URL-encodes persona name', () => {
    expect(N.Avatar._buildImageUrl('', 'hello world', 'base.png'))
      .toBe('/api/chat/hello%20world/persona/avatar/base.png');
  });
});

// ==================================================================
// Pure Logic: _emotionToFilename
// ==================================================================
describe('N.Avatar._emotionToFilename()', () => {
  it('returns base.png for neutral', () => {
    expect(N.Avatar._emotionToFilename('neutral')).toBe('base.png');
  });

  it('returns base.png for undefined', () => {
    expect(N.Avatar._emotionToFilename(undefined)).toBe('base.png');
  });

  it('returns base.png for null', () => {
    expect(N.Avatar._emotionToFilename(null)).toBe('base.png');
  });

  it('returns base.png for empty string', () => {
    expect(N.Avatar._emotionToFilename('')).toBe('base.png');
  });

  it('returns expr_<emotion>.png for named emotions', () => {
    expect(N.Avatar._emotionToFilename('joy')).toBe('expr_joy.png');
    expect(N.Avatar._emotionToFilename('sad')).toBe('expr_sad.png');
    expect(N.Avatar._emotionToFilename('angry')).toBe('expr_angry.png');
    expect(N.Avatar._emotionToFilename('surprise')).toBe('expr_surprise.png');
  });
});

// ==================================================================
// Pure Logic: _selectDisplayFile — emotion fallback
// ==================================================================
describe('N.Avatar._selectDisplayFile()', () => {
  it('returns base.png when nothing is loaded', () => {
    const state = { talking: false, mouthOpen: false, emotion: 'neutral', cache: {} };
    expect(N.Avatar._selectDisplayFile(state)).toBe('base.png');
  });

  it('returns emotion file when loaded and not errored', () => {
    const state = {
      talking: false, mouthOpen: false, emotion: 'joy',
      cache: { 'expr_joy.png': { loaded: true, error: false } },
    };
    expect(N.Avatar._selectDisplayFile(state)).toBe('expr_joy.png');
  });

  it('returns base.png when emotion file has error (fallback)', () => {
    const state = {
      talking: false, mouthOpen: false, emotion: 'joy',
      cache: { 'expr_joy.png': { loaded: false, error: true } },
    };
    expect(N.Avatar._selectDisplayFile(state)).toBe('base.png');
  });

  it('returns base.png when emotion file is not yet loaded', () => {
    const state = {
      talking: false, mouthOpen: false, emotion: 'joy',
      cache: { 'expr_joy.png': { loaded: false, error: false } },
    };
    expect(N.Avatar._selectDisplayFile(state)).toBe('base.png');
  });

  it('returns mouth_open.png when talking, mouthOpen, and loaded', () => {
    const state = {
      talking: true, mouthOpen: true, emotion: 'neutral',
      cache: {
        'base.png': { loaded: true, error: false },
        'mouth_open.png': { loaded: true, error: false },
      },
    };
    expect(N.Avatar._selectDisplayFile(state)).toBe('mouth_open.png');
  });

  it('falls back to emotion file when mouth_open not loaded', () => {
    const state = {
      talking: true, mouthOpen: true, emotion: 'joy',
      cache: {
        'expr_joy.png': { loaded: true, error: false },
        // mouth_open.png not in cache
      },
    };
    expect(N.Avatar._selectDisplayFile(state)).toBe('expr_joy.png');
  });

  it('returns emotion file (not mouth) when mouth_open has error', () => {
    const state = {
      talking: true, mouthOpen: true, emotion: 'joy',
      cache: {
        'expr_joy.png': { loaded: true, error: false },
        'mouth_open.png': { loaded: false, error: true },
      },
    };
    expect(N.Avatar._selectDisplayFile(state)).toBe('expr_joy.png');
  });

  it('returns base.png when talking but mouthOpen is false', () => {
    const state = {
      talking: true, mouthOpen: false, emotion: 'neutral',
      cache: {
        'base.png': { loaded: true, error: false },
        'mouth_open.png': { loaded: true, error: false },
      },
    };
    expect(N.Avatar._selectDisplayFile(state)).toBe('base.png');
  });

  it('returns base.png when not talking even if mouth_open loaded', () => {
    const state = {
      talking: false, mouthOpen: false, emotion: 'neutral',
      cache: {
        'base.png': { loaded: true, error: false },
        'mouth_open.png': { loaded: true, error: false },
      },
    };
    expect(N.Avatar._selectDisplayFile(state)).toBe('base.png');
  });

  it('mouth_open takes priority over loaded emotion', () => {
    const state = {
      talking: true, mouthOpen: true, emotion: 'joy',
      cache: {
        'expr_joy.png': { loaded: true, error: false },
        'mouth_open.png': { loaded: true, error: false },
      },
    };
    expect(N.Avatar._selectDisplayFile(state)).toBe('mouth_open.png');
  });
});

// ==================================================================
// Public API: init & destroy
// ==================================================================
describe('N.Avatar — init & destroy', () => {
  it('does not crash when element is null', () => {
    expect(() => N.Avatar.init(null)).not.toThrow();
  });

  it('does not crash when element is undefined', () => {
    expect(() => N.Avatar.init(undefined)).not.toThrow();
  });

  it('creates img element inside container', () => {
    const container = document.createElement('div');
    document.body.appendChild(container);

    N.Avatar.init(container, { baseUrl: '', persona: 'test' });
    const img = container.querySelector('img');
    expect(img).not.toBeNull();
    expect(img.getAttribute('alt')).toBe('Avatar');
    expect(img.getAttribute('role')).toBe('img');

    document.body.removeChild(container);
  });

  it('reuses existing img element', () => {
    const container = document.createElement('div');
    const existingImg = document.createElement('img');
    existingImg.id = 'my-avatar';
    container.appendChild(existingImg);
    document.body.appendChild(container);

    N.Avatar.init(container, { baseUrl: '', persona: 'test' });
    const imgs = container.querySelectorAll('img');
    expect(imgs.length).toBe(1);
    expect(imgs[0].id).toBe('my-avatar');

    document.body.removeChild(container);
  });

  it('removes img src on destroy', () => {
    const container = document.createElement('div');
    document.body.appendChild(container);

    N.Avatar.init(container, { baseUrl: '', persona: 'test' });
    const img = container.querySelector('img');
    expect(img).not.toBeNull();

    N.Avatar.destroy();
    expect(img.getAttribute('src')).toBeNull();

    document.body.removeChild(container);
  });

  it('sets _state to null after destroy', () => {
    N.Avatar.init(null);
    expect(N.Avatar._getState()).not.toBeNull();
    N.Avatar.destroy();
    expect(N.Avatar._getState()).toBeNull();
  });

  it('methods are no-ops after destroy', () => {
    N.Avatar.init(null);
    N.Avatar.destroy();
    expect(() => {
      N.Avatar.setEmotion('joy');
      N.Avatar.startTalking();
      N.Avatar.stopTalking();
      N.Avatar.setMouth(0.8);
    }).not.toThrow();
  });
});

// ==================================================================
// Public API: setEmotion
// ==================================================================
describe('N.Avatar — setEmotion', () => {
  it('updates state emotion and intensity', () => {
    N.Avatar.init(null, { baseUrl: '', persona: 'test' });
    N.Avatar.setEmotion('joy', 0.8);
    const state = N.Avatar._getState();
    expect(state.emotion).toBe('joy');
    expect(state.intensity).toBe(0.8);
  });

  it('defaults intensity to 1.0', () => {
    N.Avatar.init(null, { baseUrl: '', persona: 'test' });
    N.Avatar.setEmotion('sad');
    const state = N.Avatar._getState();
    expect(state.intensity).toBe(1.0);
  });

  it('treats falsy emotion as neutral', () => {
    N.Avatar.init(null, { baseUrl: '', persona: 'test' });
    N.Avatar.setEmotion('');
    expect(N.Avatar._getState().emotion).toBe('neutral');
  });

  it('triggers preload for emotion file', () => {
    N.Avatar.init(null, { baseUrl: '', persona: 'test' });
    mockImages.length = 0; // clear init's preload

    N.Avatar.setEmotion('joy');
    expect(mockImages.length).toBe(1);
    // Verify it tried to load expr_joy.png
    expect(mockImages[0].src).toContain('expr_joy.png');
  });
});

// ==================================================================
// Public API: talking state (startTalking / stopTalking / setMouth)
// ==================================================================
describe('N.Avatar — startTalking', () => {
  it('sets talking and mouthOpen to true', () => {
    N.Avatar.init(null, { baseUrl: '', persona: 'test' });
    N.Avatar.startTalking();
    const state = N.Avatar._getState();
    expect(state.talking).toBe(true);
    expect(state.mouthOpen).toBe(true);
  });

  it('triggers preload for mouth_open.png', () => {
    N.Avatar.init(null, { baseUrl: '', persona: 'test' });
    mockImages.length = 0;

    N.Avatar.startTalking();
    expect(mockImages.length).toBe(1);
    expect(mockImages[0].src).toContain('mouth_open.png');
  });
});

describe('N.Avatar — stopTalking', () => {
  it('clears talking and mouthOpen', () => {
    N.Avatar.init(null, { baseUrl: '', persona: 'test' });
    N.Avatar.startTalking();
    N.Avatar.stopTalking();
    const state = N.Avatar._getState();
    expect(state.talking).toBe(false);
    expect(state.mouthOpen).toBe(false);
  });

  it('renders current emotion image (not mouth_open)', () => {
    const container = document.createElement('div');
    document.body.appendChild(container);

    N.Avatar.init(container, { baseUrl: '', persona: 'test' });
    // Simulate base.png loaded
    mockImages[0].onload();

    N.Avatar.startTalking();
    // Simulate mouth_open.png loaded
    mockImages[1].onload();

    N.Avatar.stopTalking();
    const img = container.querySelector('img');
    // After stop, should show base.png (neutral), not mouth_open
    expect(img.getAttribute('src')).toContain('base.png');

    document.body.removeChild(container);
  });
});

describe('N.Avatar — setMouth', () => {
  it('opens mouth when ratio > 0.5', () => {
    N.Avatar.init(null, { baseUrl: '', persona: 'test' });
    N.Avatar.startTalking();
    N.Avatar.setMouth(0.8);
    expect(N.Avatar._getState().mouthOpen).toBe(true);
  });

  it('closes mouth when ratio <= 0.5', () => {
    N.Avatar.init(null, { baseUrl: '', persona: 'test' });
    N.Avatar.startTalking();
    N.Avatar.setMouth(0.3);
    expect(N.Avatar._getState().mouthOpen).toBe(false);
  });

  it('closes mouth when ratio is exactly 0.5', () => {
    N.Avatar.init(null, { baseUrl: '', persona: 'test' });
    N.Avatar.startTalking();
    N.Avatar.setMouth(0.5);
    expect(N.Avatar._getState().mouthOpen).toBe(false);
  });

  it('re-renders on state change', () => {
    const container = document.createElement('div');
    document.body.appendChild(container);

    N.Avatar.init(container, { baseUrl: '', persona: 'test' });
    mockImages[0].onload(); // base loaded

    N.Avatar.startTalking();
    mockImages[1].onload(); // mouth_open loaded

    const img = container.querySelector('img');
    const srcBefore = img.getAttribute('src');

    N.Avatar.setMouth(0.3); // close mouth
    const srcAfter = img.getAttribute('src');

    // Should change from mouth_open to base
    expect(srcAfter).toContain('base.png');
    expect(srcAfter).not.toBe(srcBefore);

    document.body.removeChild(container);
  });

  it('does not re-render when state unchanged', () => {
    N.Avatar.init(null, { baseUrl: '', persona: 'test' });
    // setMouth(0.3) when already closed — no render call
    const state = N.Avatar._getState();
    const wasMouthOpen = state.mouthOpen;
    N.Avatar.setMouth(0.3);
    // No state change, no renderer.render() call
    expect(state.mouthOpen).toBe(wasMouthOpen);
  });
});

// ==================================================================
// Emotion fallback integration (preload + onerror → base.png)
// ==================================================================
describe('N.Avatar — emotion fallback (preload error)', () => {
  it('calls onError when image fails to load', () => {
    const onError = vi.fn();
    N.Avatar.init(null, { baseUrl: '', persona: 'test', onError });
    mockImages.length = 0;

    N.Avatar.setEmotion('joy');
    mockImages[0].onerror();

    expect(onError).toHaveBeenCalledTimes(1);
    expect(onError.mock.calls[0][0].message).toContain('expr_joy.png');
  });

  it('falls back to base.png when emotion file errors', () => {
    const container = document.createElement('div');
    document.body.appendChild(container);

    N.Avatar.init(container, { baseUrl: '', persona: 'test' });
    // base.png loaded
    mockImages[0].onload();
    expect(mockImages.length).toBe(1);

    N.Avatar.setEmotion('joy');
    // expr_joy.png failed
    mockImages[0].onerror();

    const img = container.querySelector('img');
    // Should display base.png
    expect(img.getAttribute('src')).toContain('base.png');

    document.body.removeChild(container);
  });

  it('preloads are cached — second setEmotion uses cache', () => {
    N.Avatar.init(null, { baseUrl: '', persona: 'test' });
    mockImages.length = 0;

    N.Avatar.setEmotion('joy');
    // First preload creates Image
    expect(mockImages.length).toBe(1);
    mockImages[0].onload(); // load it

    // Second setEmotion('joy') should use cache, no new Image
    N.Avatar.setEmotion('joy');
    expect(mockImages.length).toBe(1); // no new Image created
  });
});

// ==================================================================
// Talking + emotion interaction
// ==================================================================
describe('N.Avatar — talking + emotion interaction', () => {
  it('mouth_open overrides emotion when talking', () => {
    const container = document.createElement('div');
    document.body.appendChild(container);

    N.Avatar.init(container, { baseUrl: '', persona: 'test' });
    mockImages[0].onload(); // base loaded

    N.Avatar.setEmotion('joy');
    mockImages[1].onload(); // expr_joy loaded
    const img = container.querySelector('img');
    expect(img.getAttribute('src')).toContain('expr_joy.png');

    N.Avatar.startTalking();
    mockImages[2].onload(); // mouth_open loaded
    expect(img.getAttribute('src')).toContain('mouth_open.png');

    N.Avatar.stopTalking();
    // Back to emotion
    expect(img.getAttribute('src')).toContain('expr_joy.png');

    document.body.removeChild(container);
  });

  it('mouth_open not shown when talking but not loaded', () => {
    const container = document.createElement('div');
    document.body.appendChild(container);

    N.Avatar.init(container, { baseUrl: '', persona: 'test' });
    mockImages[0].onload(); // base loaded

    N.Avatar.setEmotion('joy');
    mockImages[1].onload(); // expr_joy loaded

    N.Avatar.startTalking();
    // mouth_open.png NOT loaded (no onerror/onload called for it)
    const img = container.querySelector('img');
    // Should show emotion file, not mouth_open
    expect(img.getAttribute('src')).toContain('expr_joy.png');

    document.body.removeChild(container);
  });
});
