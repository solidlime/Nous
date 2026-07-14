import { loadCore } from './load-core.js';

let N;

beforeAll(() => {
  loadCore();
  N = window.Nous.Core;
});

describe('EMOTION_COLORS', () => {
  it('has all expected emotion keys', () => {
    const keys = Object.keys(N.EMOTION_COLORS);
    expect(keys).toContain('joy');
    expect(keys).toContain('sadness');
    expect(keys).toContain('anger');
    expect(keys).toContain('fear');
    expect(keys).toContain('surprise');
    expect(keys).toContain('disgust');
    expect(keys).toContain('love');
    expect(keys).toContain('neutral');
  });

  it('values are valid 6-digit hex colors', () => {
    Object.values(N.EMOTION_COLORS).forEach(v => {
      expect(v).toMatch(/^#[0-9a-fA-F]{6}$/);
    });
  });

  it('has at least 20 emotions', () => {
    expect(Object.keys(N.EMOTION_COLORS).length).toBeGreaterThanOrEqual(20);
  });
});

describe('EMOTION_BAR_COLORS', () => {
  it('contains gradient strings for common emotions', () => {
    expect(N.EMOTION_BAR_COLORS.joy).toContain('linear-gradient');
    expect(N.EMOTION_BAR_COLORS.sadness).toContain('linear-gradient');
  });

  it('has the same keys as EMOTION_COLORS (subset)', () => {
    const barKeys = Object.keys(N.EMOTION_BAR_COLORS);
    const colorKeys = Object.keys(N.EMOTION_COLORS);
    barKeys.forEach(k => {
      expect(colorKeys).toContain(k);
    });
  });
});

describe('BODY_BAR_COLORS', () => {
  it('has 5 body metric keys', () => {
    const keys = Object.keys(N.BODY_BAR_COLORS);
    expect(keys).toEqual(['fatigue', 'warmth', 'arousal', 'heart_rate', 'pain']);
  });

  it('all values are linear-gradient strings', () => {
    Object.values(N.BODY_BAR_COLORS).forEach(v => {
      expect(v).toMatch(/^linear-gradient/);
    });
  });
});

describe('BODY_LABELS', () => {
  it('has 5 body metric keys', () => {
    const keys = Object.keys(N.BODY_LABELS);
    expect(keys).toEqual(['fatigue', 'warmth', 'arousal', 'heart_rate', 'pain']);
  });

  it('contains HTML with data-lucide icons', () => {
    Object.values(N.BODY_LABELS).forEach(v => {
      expect(v).toContain('<i data-lucide=');
    });
  });
});

describe('CHART_COLORS', () => {
  it('is an array of 10 hex colors', () => {
    expect(N.CHART_COLORS).toHaveLength(10);
    N.CHART_COLORS.forEach(c => {
      expect(c).toMatch(/^#[0-9a-fA-F]{6}$/);
    });
  });
});
