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
    const state = { talking: false, mouthLevel: 0, emotion: 'neutral', cache: {} };
    expect(N.Avatar._selectDisplayFile(state)).toBe('base.png');
  });

  it('returns emotion file when loaded and not errored', () => {
    const state = {
      talking: false, mouthLevel: 0, emotion: 'joy',
      cache: { 'expr_joy.png': { loaded: true, error: false } },
    };
    expect(N.Avatar._selectDisplayFile(state)).toBe('expr_joy.png');
  });

  it('returns base.png when emotion file has error (fallback)', () => {
    const state = {
      talking: false, mouthLevel: 0, emotion: 'joy',
      cache: { 'expr_joy.png': { loaded: false, error: true } },
    };
    expect(N.Avatar._selectDisplayFile(state)).toBe('base.png');
  });

  it('returns base.png when emotion file is not yet loaded', () => {
    const state = {
      talking: false, mouthLevel: 0, emotion: 'joy',
      cache: { 'expr_joy.png': { loaded: false, error: false } },
    };
    expect(N.Avatar._selectDisplayFile(state)).toBe('base.png');
  });

  it('returns mouth_3.png when talking, mouthLevel 3, and loaded', () => {
    const state = {
      talking: true, mouthLevel: 3, emotion: 'neutral',
      cache: {
        'base.png': { loaded: true, error: false },
        'mouth_3.png': { loaded: true, error: false },
      },
    };
    expect(N.Avatar._selectDisplayFile(state)).toBe('mouth_3.png');
  });

  it('falls back to emotion file when mouth level not loaded', () => {
    const state = {
      talking: true, mouthLevel: 3, emotion: 'joy',
      cache: {
        'expr_joy.png': { loaded: true, error: false },
        // mouth_3.png not in cache
      },
    };
    expect(N.Avatar._selectDisplayFile(state)).toBe('expr_joy.png');
  });

  it('returns emotion file (not mouth) when mouth_3 has error', () => {
    const state = {
      talking: true, mouthLevel: 3, emotion: 'joy',
      cache: {
        'expr_joy.png': { loaded: true, error: false },
        'mouth_3.png': { loaded: false, error: true },
      },
    };
    expect(N.Avatar._selectDisplayFile(state)).toBe('expr_joy.png');
  });

  it('returns base.png when talking but mouthLevel is 0', () => {
    const state = {
      talking: true, mouthLevel: 0, emotion: 'neutral',
      cache: {
        'base.png': { loaded: true, error: false },
        'mouth_3.png': { loaded: true, error: false },
      },
    };
    expect(N.Avatar._selectDisplayFile(state)).toBe('base.png');
  });

  it('returns base.png when not talking even if mouth_3 loaded', () => {
    const state = {
      talking: false, mouthLevel: 0, emotion: 'neutral',
      cache: {
        'base.png': { loaded: true, error: false },
        'mouth_3.png': { loaded: true, error: false },
      },
    };
    expect(N.Avatar._selectDisplayFile(state)).toBe('base.png');
  });

  it('mouth_3 takes priority over loaded emotion', () => {
    const state = {
      talking: true, mouthLevel: 3, emotion: 'joy',
      cache: {
        'expr_joy.png': { loaded: true, error: false },
        'mouth_3.png': { loaded: true, error: false },
      },
    };
    expect(N.Avatar._selectDisplayFile(state)).toBe('mouth_3.png');
  });

  // ── 5-level step-down fallback (mouth_<n>.png) ──
  it('steps down to mouth_2 when mouth_3 is missing/errored', () => {
    const state = {
      talking: true, mouthLevel: 3, emotion: 'joy',
      cache: {
        'expr_joy.png': { loaded: true, error: false },
        'mouth_3.png': { loaded: false, error: true },
        'mouth_2.png': { loaded: true, error: false },
      },
    };
    expect(N.Avatar._selectDisplayFile(state)).toBe('mouth_2.png');
  });

  it('steps down through all levels to mouth_1', () => {
    const state = {
      talking: true, mouthLevel: 4, emotion: 'joy',
      cache: {
        'expr_joy.png': { loaded: true, error: false },
        'mouth_4.png': { loaded: false, error: true },
        'mouth_3.png': { loaded: false, error: true },
        'mouth_2.png': { loaded: false, error: false },
        'mouth_1.png': { loaded: true, error: false },
      },
    };
    expect(N.Avatar._selectDisplayFile(state)).toBe('mouth_1.png');
  });

  it('falls back to emotion when all mouth levels fail', () => {
    const state = {
      talking: true, mouthLevel: 4, emotion: 'joy',
      cache: {
        'expr_joy.png': { loaded: true, error: false },
        'mouth_4.png': { loaded: false, error: true },
        'mouth_3.png': { loaded: false, error: true },
        'mouth_2.png': { loaded: false, error: true },
        'mouth_1.png': { loaded: false, error: true },
      },
    };
    expect(N.Avatar._selectDisplayFile(state)).toBe('expr_joy.png');
  });

  it('uses base.png when mouth_0.png exists but level is 0 (base is the closed mouth)', () => {
    const state = {
      talking: true, mouthLevel: 0, emotion: 'neutral',
      cache: {
        'base.png': { loaded: true, error: false },
        'mouth_0.png': { loaded: true, error: false },
      },
    };
    expect(N.Avatar._selectDisplayFile(state)).toBe('base.png');
  });
});

// ==================================================================
// Pure Logic: _mouthRatioToLevel — quantization + hysteresis
// ==================================================================
describe('N.Avatar._mouthRatioToLevel()', () => {
  // ── Basic quantization from level 0 ──
  it('maps low ratio to level 0', () => {
    expect(N.Avatar._mouthRatioToLevel(0.0, 0)).toBe(0);
    expect(N.Avatar._mouthRatioToLevel(0.19, 0)).toBe(0);
  });

  it('rises to level 1 when ratio >= 0.2', () => {
    expect(N.Avatar._mouthRatioToLevel(0.2, 0)).toBe(1);
    expect(N.Avatar._mouthRatioToLevel(0.39, 0)).toBe(1);
  });

  it('rises stepwise: thresholds [0.2, 0.4, 0.6, 0.8]', () => {
    expect(N.Avatar._mouthRatioToLevel(0.2, 0)).toBe(1);
    expect(N.Avatar._mouthRatioToLevel(0.4, 1)).toBe(2);
    expect(N.Avatar._mouthRatioToLevel(0.6, 2)).toBe(3);
    expect(N.Avatar._mouthRatioToLevel(0.8, 3)).toBe(4);
  });

  // ── Hysteresis: falling thresholds differ from rising ──
  it('falls only below lower thresholds [0.15, 0.35, 0.55, 0.75]', () => {
    expect(N.Avatar._mouthRatioToLevel(0.14, 1)).toBe(0);
    expect(N.Avatar._mouthRatioToLevel(0.34, 2)).toBe(1);
    expect(N.Avatar._mouthRatioToLevel(0.54, 3)).toBe(2);
    expect(N.Avatar._mouthRatioToLevel(0.74, 4)).toBe(3);
  });

  it('keeps level in hysteresis band between falling and rising thresholds', () => {
    // At level 1: 0.15 <= ratio < 0.4 stays at 1
    expect(N.Avatar._mouthRatioToLevel(0.2, 1)).toBe(1);
    expect(N.Avatar._mouthRatioToLevel(0.3, 1)).toBe(1);
    expect(N.Avatar._mouthRatioToLevel(0.39, 1)).toBe(1);
    // At level 2: 0.35 <= ratio < 0.6 stays at 2
    expect(N.Avatar._mouthRatioToLevel(0.5, 2)).toBe(2);
  });

  it('same ratio can rise from lower level but hold at higher level', () => {
    // ratio 0.3: from 0 rises to 1, but from 1 holds (band 0.15-0.4)
    expect(N.Avatar._mouthRatioToLevel(0.3, 0)).toBe(1);
    expect(N.Avatar._mouthRatioToLevel(0.3, 1)).toBe(1);
    // ratio 0.5: from 1 rises to 2, from 2 holds (band 0.35-0.6)
    expect(N.Avatar._mouthRatioToLevel(0.5, 1)).toBe(2);
    expect(N.Avatar._mouthRatioToLevel(0.5, 2)).toBe(2);
  });

  // ── Clamping ──
  it('clamps to 4 at the top', () => {
    expect(N.Avatar._mouthRatioToLevel(1.0, 4)).toBe(4);
    expect(N.Avatar._mouthRatioToLevel(0.9, 4)).toBe(4);
    expect(N.Avatar._mouthRatioToLevel(2.0, 4)).toBe(4);
  });

  it('clamps to 0 at the bottom', () => {
    expect(N.Avatar._mouthRatioToLevel(0.0, 0)).toBe(0);
    expect(N.Avatar._mouthRatioToLevel(-0.5, 0)).toBe(0);
  });

  it('treats invalid prevLevel as 0', () => {
    expect(N.Avatar._mouthRatioToLevel(0.5, undefined)).toBe(1);
    expect(N.Avatar._mouthRatioToLevel(0.5, NaN)).toBe(1);
    expect(N.Avatar._mouthRatioToLevel(0.1, null)).toBe(0);
  });

  it('treats invalid ratio as closed (0)', () => {
    expect(N.Avatar._mouthRatioToLevel(undefined, 3)).toBe(2);
    expect(N.Avatar._mouthRatioToLevel(NaN, 3)).toBe(2);
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
  it('sets talking to true and defaults mouthLevel to 2', () => {
    N.Avatar.init(null, { baseUrl: '', persona: 'test' });
    N.Avatar.startTalking();
    const state = N.Avatar._getState();
    expect(state.talking).toBe(true);
    expect(state.mouthLevel).toBe(2);
  });

  it('preloads mouth_1..mouth_4 (not legacy mouth_open)', () => {
    N.Avatar.init(null, { baseUrl: '', persona: 'test' });
    mockImages.length = 0;

    N.Avatar.startTalking();
    // 4 preloads: mouth_1 .. mouth_4
    expect(mockImages.length).toBe(4);
    expect(mockImages.map(i => i.src)).toEqual([
      expect.stringContaining('mouth_1.png'),
      expect.stringContaining('mouth_2.png'),
      expect.stringContaining('mouth_3.png'),
      expect.stringContaining('mouth_4.png'),
    ]);
  });

  it('keeps existing mouthLevel when already set', () => {
    N.Avatar.init(null, { baseUrl: '', persona: 'test' });
    N.Avatar.setMouth(0.9); // level 0 -> 1 (ratio >= 0.2)
    expect(N.Avatar._getState().mouthLevel).toBe(1);
    N.Avatar.startTalking();
    expect(N.Avatar._getState().mouthLevel).toBe(1);
  });
});

describe('N.Avatar — stopTalking', () => {
  it('clears talking and resets mouthLevel to 0', () => {
    N.Avatar.init(null, { baseUrl: '', persona: 'test' });
    N.Avatar.startTalking();
    N.Avatar.stopTalking();
    const state = N.Avatar._getState();
    expect(state.talking).toBe(false);
    expect(state.mouthLevel).toBe(0);
  });

  it('renders current emotion image (not mouth)', () => {
    const container = document.createElement('div');
    document.body.appendChild(container);

    N.Avatar.init(container, { baseUrl: '', persona: 'test' });
    // Simulate base.png loaded
    mockImages[0].onload();

    N.Avatar.startTalking();
    // Simulate mouth_2.png loaded
    mockImages[1].onload(); // mouth_1
    mockImages[2].onload(); // mouth_2

    N.Avatar.stopTalking();
    const img = container.querySelector('img');
    // After stop, should show base.png (neutral), not mouth
    expect(img.getAttribute('src')).toContain('base.png');

    document.body.removeChild(container);
  });
});

describe('N.Avatar — setMouth', () => {
  it('raises mouth level when ratio >= 0.2 (from 0)', () => {
    N.Avatar.init(null, { baseUrl: '', persona: 'test' });
    N.Avatar.setMouth(0.8);
    expect(N.Avatar._getState().mouthLevel).toBe(1);
  });

  it('quantizes stepwise: 0.8 from level 1 -> level 2', () => {
    N.Avatar.init(null, { baseUrl: '', persona: 'test' });
    N.Avatar.setMouth(0.8); // level 1
    N.Avatar.setMouth(0.8); // level 2 (>= 0.4)
    expect(N.Avatar._getState().mouthLevel).toBe(2);
  });

  it('holds level in hysteresis band (0.3 at level 1 stays 1)', () => {
    N.Avatar.init(null, { baseUrl: '', persona: 'test' });
    N.Avatar.setMouth(0.8); // level 1
    N.Avatar.setMouth(0.3); // band 0.15-0.4 -> stays 1
    expect(N.Avatar._getState().mouthLevel).toBe(1);
  });

  it('closes mouth when ratio drops below 0.15 at level 1', () => {
    N.Avatar.init(null, { baseUrl: '', persona: 'test' });
    N.Avatar.setMouth(0.8); // level 1
    N.Avatar.setMouth(0.1); // < 0.15 -> level 0
    expect(N.Avatar._getState().mouthLevel).toBe(0);
  });

  it('clamps to 4 at the top', () => {
    N.Avatar.init(null, { baseUrl: '', persona: 'test' });
    N.Avatar.setMouth(0.9); // 1
    N.Avatar.setMouth(0.9); // 2
    N.Avatar.setMouth(0.9); // 3
    N.Avatar.setMouth(0.9); // 4
    N.Avatar.setMouth(0.9); // clamped 4
    expect(N.Avatar._getState().mouthLevel).toBe(4);
  });

  it('re-renders on mouth level change', () => {
    const container = document.createElement('div');
    document.body.appendChild(container);

    N.Avatar.init(container, { baseUrl: '', persona: 'test' });
    mockImages[0].onload(); // base loaded

    N.Avatar.startTalking();
    mockImages[1].onload(); // mouth_1 loaded
    mockImages[2].onload(); // mouth_2 loaded

    const img = container.querySelector('img');
    const srcBefore = img.getAttribute('src');

    N.Avatar.setMouth(0.0); // mouthLevel 2 -> 1 (below 0.35)
    const srcAfter = img.getAttribute('src');

    // Should change from mouth_2 to mouth_1
    expect(srcAfter).toContain('mouth_1.png');
    expect(srcAfter).not.toBe(srcBefore);

    document.body.removeChild(container);
  });

  it('does not re-render when level unchanged', () => {
    N.Avatar.init(null, { baseUrl: '', persona: 'test' });
    // setMouth(0.8) twice: first moves 0 -> 1, second stays at 1 (0.8 < 0.4? no, >= 0.4 -> 2)
    N.Avatar.setMouth(0.3); // 0 -> 1 (>= 0.2)
    const levelAfterFirst = N.Avatar._getState().mouthLevel;
    expect(levelAfterFirst).toBe(1);
    N.Avatar.setMouth(0.3); // 1 -> stays 1 (band)
    expect(N.Avatar._getState().mouthLevel).toBe(1);
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
  it('mouth_2 overrides emotion when talking', () => {
    const container = document.createElement('div');
    document.body.appendChild(container);

    N.Avatar.init(container, { baseUrl: '', persona: 'test' });
    mockImages[0].onload(); // base loaded

    N.Avatar.setEmotion('joy');
    mockImages[1].onload(); // expr_joy loaded
    const img = container.querySelector('img');
    expect(img.getAttribute('src')).toContain('expr_joy.png');

    N.Avatar.startTalking();
    // startTalking preloads mouth_1..4 -> mockImages[2..5]
    mockImages[2].onload(); // mouth_1
    mockImages[3].onload(); // mouth_2
    expect(img.getAttribute('src')).toContain('mouth_2.png');

    N.Avatar.stopTalking();
    // Back to emotion
    expect(img.getAttribute('src')).toContain('expr_joy.png');

    document.body.removeChild(container);
  });

  it('mouth not shown when talking but not loaded', () => {
    const container = document.createElement('div');
    document.body.appendChild(container);

    N.Avatar.init(container, { baseUrl: '', persona: 'test' });
    mockImages[0].onload(); // base loaded

    N.Avatar.setEmotion('joy');
    mockImages[1].onload(); // expr_joy loaded

    N.Avatar.startTalking();
    // mouth_1..4 NOT loaded (no onerror/onload called for them)
    const img = container.querySelector('img');
    // Should show emotion file, not mouth
    expect(img.getAttribute('src')).toContain('expr_joy.png');

    document.body.removeChild(container);
  });
});

// ==================================================================
// Pure Logic: _lookFrameAt — time → look state
// Sequence (ms): front 1200, left 900, front 1200, right 900 (cycle 4200)
// ==================================================================
describe('N.Avatar._lookFrameAt()', () => {
  it('starts at front', () => {
    expect(N.Avatar._lookFrameAt(1000, 1000)).toBe('front');
  });

  it('turns left after front duration (elapsed 1200-2100ms)', () => {
    expect(N.Avatar._lookFrameAt(1300, 1000)).toBe('front');  // elapsed 300 → front
    expect(N.Avatar._lookFrameAt(2300, 1000)).toBe('left');   // elapsed 1300 → left
    expect(N.Avatar._lookFrameAt(3000, 1000)).toBe('left');   // elapsed 2000 → left
  });

  it('returns front between left and right (elapsed 2100-3300ms)', () => {
    expect(N.Avatar._lookFrameAt(3100, 1000)).toBe('front');  // elapsed 2100
    expect(N.Avatar._lookFrameAt(4200, 1000)).toBe('front');  // elapsed 3200
  });

  it('turns right after second front (elapsed 3300-4200ms)', () => {
    expect(N.Avatar._lookFrameAt(4300, 1000)).toBe('right');  // elapsed 3300
    expect(N.Avatar._lookFrameAt(5000, 1000)).toBe('right');  // elapsed 4000
  });

  it('loops back to front after cycle (4200ms)', () => {
    expect(N.Avatar._lookFrameAt(5200, 1000)).toBe('front');  // elapsed 4200 → 0
    expect(N.Avatar._lookFrameAt(6500, 1000)).toBe('left');   // elapsed 5500 → 1300
  });

  it('treats negative elapsed as front', () => {
    expect(N.Avatar._lookFrameAt(0, 1000)).toBe('front');
  });

  it('treats invalid inputs as front', () => {
    expect(N.Avatar._lookFrameAt(undefined, 1000)).toBe('front');
    expect(N.Avatar._lookFrameAt(NaN, 1000)).toBe('front');
    expect(N.Avatar._lookFrameAt(5000, undefined)).toBe('front');
    expect(N.Avatar._lookFrameAt(5000, NaN)).toBe('front');
  });
});

// ==================================================================
// Pure Logic: _hairFrameAt — time → hair frame (0|1|2|3|4, 200ms each)
// ==================================================================
describe('N.Avatar._hairFrameAt()', () => {
  it('returns frame 0 at start', () => {
    expect(N.Avatar._hairFrameAt(1000, 1000)).toBe(0);
  });

  it('advances every 200ms', () => {
    expect(N.Avatar._hairFrameAt(1199, 1000)).toBe(0);
    expect(N.Avatar._hairFrameAt(1200, 1000)).toBe(1);
    expect(N.Avatar._hairFrameAt(1399, 1000)).toBe(1);
    expect(N.Avatar._hairFrameAt(1400, 1000)).toBe(2);
    expect(N.Avatar._hairFrameAt(1599, 1000)).toBe(2);
    expect(N.Avatar._hairFrameAt(1600, 1000)).toBe(3);
    expect(N.Avatar._hairFrameAt(1799, 1000)).toBe(3);
    expect(N.Avatar._hairFrameAt(1800, 1000)).toBe(4);
    expect(N.Avatar._hairFrameAt(1999, 1000)).toBe(4);
  });

  it('loops 0-1-2-3-4-0', () => {
    expect(N.Avatar._hairFrameAt(2000, 1000)).toBe(0); // 1000ms → 5 % 5
    expect(N.Avatar._hairFrameAt(2200, 1000)).toBe(1); // 1200ms → 6 % 5
    expect(N.Avatar._hairFrameAt(2400, 1000)).toBe(2); // 1400ms → 7 % 5
    expect(N.Avatar._hairFrameAt(2600, 1000)).toBe(3); // 1600ms → 8 % 5
    expect(N.Avatar._hairFrameAt(2800, 1000)).toBe(4); // 1800ms → 9 % 5
  });

  it('treats negative elapsed as frame 0', () => {
    expect(N.Avatar._hairFrameAt(0, 1000)).toBe(0);
  });

  it('treats invalid inputs as frame 0', () => {
    expect(N.Avatar._hairFrameAt(undefined, 1000)).toBe(0);
    expect(N.Avatar._hairFrameAt(NaN, 1000)).toBe(0);
    expect(N.Avatar._hairFrameAt(5000, undefined)).toBe(0);
    expect(N.Avatar._hairFrameAt(5000, NaN)).toBe(0);
  });
});

// ==================================================================
// Pure Logic: _selectDisplayFile — look/bob priority
// mouth > look > hair > emotion > base
// ==================================================================
describe('N.Avatar._selectDisplayFile() — look/bob priority', () => {
  it('look state does not change file selection (look is transform-based)', () => {
    const state = {
      talking: false, mouthLevel: 0, emotion: 'joy',
      lookEnabled: true, look: 'left', hairFrame: 0,
      cache: {
        'expr_joy.png': { loaded: true, error: false },
        'look_left.png': { loaded: true, error: false },
      },
    };
    expect(N.Avatar._selectDisplayFile(state)).toBe('expr_joy.png');
  });

  it('ignores look assets even when loaded (transform-based)', () => {
    const state = {
      talking: false, mouthLevel: 0, emotion: 'neutral',
      lookEnabled: true, look: 'right', hairFrame: 0,
      cache: { 'look_right.png': { loaded: true, error: false } },
    };
    expect(N.Avatar._selectDisplayFile(state)).toBe('base.png');
  });

  it('hair wins over loaded look assets (look is transform-only)', () => {
    const state = {
      talking: false, mouthLevel: 0, emotion: 'neutral',
      lookEnabled: true, look: 'left', hairFrame: 1,
      cache: {
        'look_left.png': { loaded: true, error: false },
        'hair_1.png': { loaded: true, error: false },
      },
    };
    expect(N.Avatar._selectDisplayFile(state)).toBe('hair_1.png');
  });

  it('hair frame takes priority over emotion when front', () => {
    const state = {
      talking: false, mouthLevel: 0, emotion: 'joy',
      lookEnabled: true, look: 'front', hairFrame: 1,
      cache: {
        'expr_joy.png': { loaded: true, error: false },
        'hair_1.png': { loaded: true, error: false },
      },
    };
    expect(N.Avatar._selectDisplayFile(state)).toBe('hair_1.png');
  });

  it('mouth beats look when talking', () => {
    const state = {
      talking: true, mouthLevel: 2, emotion: 'neutral',
      lookEnabled: true, look: 'left', hairFrame: 1,
      cache: {
        'mouth_2.png': { loaded: true, error: false },
        'look_left.png': { loaded: true, error: false },
      },
    };
    expect(N.Avatar._selectDisplayFile(state)).toBe('mouth_2.png');
  });

  it('falls back to hair when look file not loaded', () => {
    const state = {
      talking: false, mouthLevel: 0, emotion: 'neutral',
      lookEnabled: true, look: 'left', hairFrame: 2,
      cache: { 'hair_2.png': { loaded: true, error: false } },
    };
    expect(N.Avatar._selectDisplayFile(state)).toBe('hair_2.png');
  });

  it('falls back to emotion when look and hair not loaded', () => {
    const state = {
      talking: false, mouthLevel: 0, emotion: 'joy',
      lookEnabled: true, look: 'left', hairFrame: 2,
      cache: {
        'expr_joy.png': { loaded: true, error: false },
        'look_left.png': { loaded: false, error: false },
        'hair_2.png': { loaded: false, error: false },
      },
    };
    expect(N.Avatar._selectDisplayFile(state)).toBe('expr_joy.png');
  });

  it('lookEnabled:false skips look layer', () => {
    const state = {
      talking: false, mouthLevel: 0, emotion: 'joy',
      lookEnabled: false, look: 'left', hairFrame: 0,
      cache: {
        'expr_joy.png': { loaded: true, error: false },
        'look_left.png': { loaded: true, error: false },
      },
    };
    expect(N.Avatar._selectDisplayFile(state)).toBe('expr_joy.png');
  });

  it('bobEnabled:false skips hair layer', () => {
    const state = {
      talking: false, mouthLevel: 0, emotion: 'joy',
      lookEnabled: true, look: 'front', bobEnabled: false, hairFrame: 1,
      cache: {
        'expr_joy.png': { loaded: true, error: false },
        'hair_1.png': { loaded: true, error: false },
      },
    };
    expect(N.Avatar._selectDisplayFile(state)).toBe('expr_joy.png');
  });

  it('falls back to base when look file errored and no emotion', () => {
    const state = {
      talking: false, mouthLevel: 0, emotion: 'neutral',
      lookEnabled: true, look: 'right', hairFrame: 0,
      cache: { 'look_right.png': { loaded: false, error: true } },
    };
    expect(N.Avatar._selectDisplayFile(state)).toBe('base.png');
  });

  it('invalid hairFrame is skipped', () => {
    const state = {
      talking: false, mouthLevel: 0, emotion: 'neutral',
      lookEnabled: true, look: 'front', hairFrame: 7,
      cache: { 'hair_7.png': { loaded: true, error: false } },
    };
    expect(N.Avatar._selectDisplayFile(state)).toBe('base.png');
  });
});

// ==================================================================
// Idle animation driver (fake timers)
// ==================================================================
describe('N.Avatar — look/bob animation driver', () => {
  beforeEach(() => {
    vi.useFakeTimers({ toFake: ['setInterval', 'clearInterval', 'Date'] });
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('advances look state through the sequence when idle', () => {
    N.Avatar.init(null, { baseUrl: '', persona: 'test', bobEnabled: false });
    vi.advanceTimersByTime(100); // first tick: lookStartTime set, look=front
    expect(N.Avatar._getState().look).toBe('front');
    vi.advanceTimersByTime(1300); // t=1400 → elapsed 1300 → left
    expect(N.Avatar._getState().look).toBe('left');
    vi.advanceTimersByTime(900);  // t=2300 → elapsed 2200 → front
    expect(N.Avatar._getState().look).toBe('front');
    vi.advanceTimersByTime(1200); // t=3500 → elapsed 3400 → right
    expect(N.Avatar._getState().look).toBe('right');
    vi.advanceTimersByTime(900);  // t=4400 → elapsed 4300 → 100 % 4200 → front
    expect(N.Avatar._getState().look).toBe('front');
  });

  it('advances hair frames 0→1→2→3→4→0 when idle', () => {
    N.Avatar.init(null, { baseUrl: '', persona: 'test', lookEnabled: false });
    vi.advanceTimersByTime(100); // first tick: hairStartTime set, frame 0
    expect(N.Avatar._getState().hairFrame).toBe(0);
    vi.advanceTimersByTime(200); // t=300 → elapsed 200 → frame 1
    expect(N.Avatar._getState().hairFrame).toBe(1);
    vi.advanceTimersByTime(200); // t=500 → elapsed 400 → frame 2
    expect(N.Avatar._getState().hairFrame).toBe(2);
    vi.advanceTimersByTime(200); // t=700 → elapsed 600 → frame 3
    expect(N.Avatar._getState().hairFrame).toBe(3);
    vi.advanceTimersByTime(200); // t=900 → elapsed 800 → frame 4
    expect(N.Avatar._getState().hairFrame).toBe(4);
    vi.advanceTimersByTime(200); // t=1100 → elapsed 1000 → frame 0 (loop)
    expect(N.Avatar._getState().hairFrame).toBe(0);
  });

  it('pins look to front while talking and resumes after stop', () => {
    N.Avatar.init(null, { baseUrl: '', persona: 'test', bobEnabled: false });
    vi.advanceTimersByTime(1400); // look → left
    expect(N.Avatar._getState().look).toBe('left');

    N.Avatar.startTalking();
    vi.advanceTimersByTime(5000);
    expect(N.Avatar._getState().look).toBe('front');
    expect(N.Avatar._getState().talking).toBe(true);

    N.Avatar.stopTalking();
    vi.advanceTimersByTime(1300);
    // animation resumes — should be a turned state, not stuck at front
    expect(['left', 'right']).toContain(N.Avatar._getState().look);
  });

  it('keeps look front when lookEnabled is false', () => {
    N.Avatar.init(null, { baseUrl: '', persona: 'test', lookEnabled: false, bobEnabled: false });
    expect(vi.getTimerCount()).toBe(0); // both disabled → no timer
    vi.advanceTimersByTime(5000);
    expect(N.Avatar._getState().look).toBe('front');
  });

  it('preloads hair assets on the first idle tick (look needs no assets)', () => {
    N.Avatar.init(null, { baseUrl: '', persona: 'test' });
    mockImages.length = 0; // drop base.png preload
    vi.advanceTimersByTime(100);
    const urls = mockImages.map(i => i.src);
    ['hair_0.png', 'hair_1.png', 'hair_2.png', 'hair_3.png', 'hair_4.png']
      .forEach(f => expect(urls.some(u => u.includes(f))).toBe(true));
    // look is transform-based — engine must not fetch look assets
    expect(urls.some(u => u.includes('look_'))).toBe(false);
  });

  it('applies rotateY tilt via transform when look turns (no image swap)', () => {
    const container = document.createElement('div');
    document.body.appendChild(container);

    N.Avatar.init(container, { baseUrl: '', persona: 'test', bobEnabled: false });
    const img = container.querySelector('img');
    vi.advanceTimersByTime(1400); // t=1400, elapsed 1300 → left
    expect(img.style.transform).toContain('rotateY(-10deg)');

    N.Avatar.startTalking();
    vi.advanceTimersByTime(100); // talking pins rotation to 0
    expect(img.style.transform).toContain('rotateY(0deg)');

    N.Avatar.stopTalking();
    vi.advanceTimersByTime(2000); // t=3500, elapsed 3400 → right
    expect(img.style.transform).toContain('rotateY(10deg)');

    document.body.removeChild(container);
  });

  it('applies breathing translateY when idle and resets while talking', () => {
    const container = document.createElement('div');
    document.body.appendChild(container);

    N.Avatar.init(container, { baseUrl: '', persona: 'test', lookEnabled: false }); // bob on → timer runs
    const img = container.querySelector('img');
    vi.advanceTimersByTime(100); // tick1: bobStartTime set, translateY(0px)
    vi.advanceTimersByTime(750); // t=850, elapsed 750 → sin(π/2)=1 → +2
    expect(img.style.transform).toContain('translateY(2px)');

    N.Avatar.startTalking();
    vi.advanceTimersByTime(100);
    expect(img.style.transform).toContain('translateY(0px)');

    document.body.removeChild(container);
  });

  it('renders hair frame when idle and asset loaded', () => {
    const container = document.createElement('div');
    document.body.appendChild(container);

    N.Avatar.init(container, { baseUrl: '', persona: 'test', lookEnabled: false });
    mockImages[0].onload(); // base.png
    vi.advanceTimersByTime(100); // first tick: hair_0 preloaded, frame 0
    const hair0 = mockImages.find(i => i.src.includes('hair_0.png'));
    expect(hair0).toBeTruthy();
    hair0.onload();
    vi.advanceTimersByTime(100); // next tick renders
    expect(container.querySelector('img').getAttribute('src')).toContain('hair_0.png');

    document.body.removeChild(container);
  });

  it('quietly falls back when hair assets fail to load', () => {
    const onError = vi.fn();
    N.Avatar.init(null, { baseUrl: '', persona: 'test', onError });
    mockImages.length = 0;
    vi.advanceTimersByTime(100);
    const urls = mockImages.map(i => i.src);
    expect(urls.some(u => u.includes('hair_0.png'))).toBe(true);
    mockImages.forEach(i => i.onerror());
    // quiet preloads must not report errors
    expect(onError).not.toHaveBeenCalled();
    vi.advanceTimersByTime(2000);
    expect(N.Avatar._getState()).not.toBeNull();
  });

  it('stops the animation timer on destroy', () => {
    N.Avatar.init(null, { baseUrl: '', persona: 'test' });
    expect(vi.getTimerCount()).toBeGreaterThan(0);
    N.Avatar.destroy();
    expect(vi.getTimerCount()).toBe(0);
    vi.advanceTimersByTime(1000); // no crash after destroy
  });
});

// ==================================================================
// Pure Logic: _lookTiltDeg — look state → rotateY degrees
// ==================================================================
describe('N.Avatar._lookTiltDeg()', () => {
  it('returns 0 for front', () => {
    expect(N.Avatar._lookTiltDeg('front')).toBe(0);
  });

  it('returns -10 for left', () => {
    expect(N.Avatar._lookTiltDeg('left')).toBe(-10);
  });

  it('returns 10 for right', () => {
    expect(N.Avatar._lookTiltDeg('right')).toBe(10);
  });

  it('returns 0 for invalid states', () => {
    expect(N.Avatar._lookTiltDeg(undefined)).toBe(0);
    expect(N.Avatar._lookTiltDeg(null)).toBe(0);
    expect(N.Avatar._lookTiltDeg('')).toBe(0);
    expect(N.Avatar._lookTiltDeg('up')).toBe(0);
  });
});

// ==================================================================
// Pure Logic: _bobOffset — breathing sine wave (period 3000ms, ±2px)
// ==================================================================
describe('N.Avatar._bobOffset()', () => {
  it('returns 0 at start', () => {
    expect(N.Avatar._bobOffset(1000, 1000)).toBe(0);
  });

  it('peaks at +2 at quarter period (750ms)', () => {
    expect(N.Avatar._bobOffset(1750, 1000)).toBe(2); // sin(π/2)
  });

  it('returns 0 at half period (1500ms)', () => {
    expect(N.Avatar._bobOffset(2500, 1000)).toBe(0); // sin(π)
  });

  it('peaks at -2 at three-quarter period (2250ms)', () => {
    expect(N.Avatar._bobOffset(3250, 1000)).toBe(-2); // sin(3π/2)
  });

  it('loops after a full period (3000ms)', () => {
    expect(N.Avatar._bobOffset(4000, 1000)).toBe(0); // sin(2π)
    expect(N.Avatar._bobOffset(4750, 1000)).toBe(2); // 750ms into 2nd cycle
  });

  it('always returns integers', () => {
    for (let dt = 0; dt <= 3000; dt += 50) {
      expect(Number.isInteger(N.Avatar._bobOffset(1000 + dt, 1000))).toBe(true);
    }
  });

  it('treats invalid inputs as 0', () => {
    expect(N.Avatar._bobOffset(undefined, 1000)).toBe(0);
    expect(N.Avatar._bobOffset(NaN, 1000)).toBe(0);
    expect(N.Avatar._bobOffset(5000, undefined)).toBe(0);
    expect(N.Avatar._bobOffset(-100, 1000)).toBe(0);
  });
});

// ==================================================================
// Pure Logic: _composeTransform — transform string composition
// ==================================================================
describe('N.Avatar._composeTransform()', () => {
  it('composes perspective + rotateY + translateY in order', () => {
    expect(N.Avatar._composeTransform(-10, 2))
      .toBe('perspective(600px) rotateY(-10deg) translateY(2px)');
    expect(N.Avatar._composeTransform(10, -2))
      .toBe('perspective(600px) rotateY(10deg) translateY(-2px)');
    expect(N.Avatar._composeTransform(0, 0))
      .toBe('perspective(600px) rotateY(0deg) translateY(0px)');
  });
});

// ==================================================================
// Crossfade on src change (fake rAF/timers)
// ==================================================================
describe('N.Avatar — src crossfade', () => {
  beforeEach(() => {
    vi.useFakeTimers({
      toFake: ['setTimeout', 'clearTimeout', 'requestAnimationFrame',
               'cancelAnimationFrame', 'setInterval', 'clearInterval', 'Date'],
    });
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('fades opacity 0 → 1 when src changes, untouched on same-src render', () => {
    const container = document.createElement('div');
    document.body.appendChild(container);

    N.Avatar.init(container, { baseUrl: '', persona: 'test' });
    const img = container.querySelector('img');

    // src change: expr_joy loaded → fade out, swap, fade in next frame
    N.Avatar.setEmotion('joy');
    mockImages[1].onload(); // expr_joy (index 1: base at 0, no ticks advanced yet)
    expect(img.style.opacity).toBe('0');
    expect(img.getAttribute('src')).toContain('expr_joy.png');

    vi.advanceTimersByTime(50); // next frame → fade in
    expect(img.style.opacity).toBe('1');

    // same-src render (cached) must not touch opacity
    N.Avatar.setEmotion('joy'); // cached → immediate render, same src
    expect(img.style.opacity).toBe('1');

    document.body.removeChild(container);
  });
});
