/* =================================================================
   Tests for components/memory-card.js — sanitizer-safe bar markup
   ================================================================= */
import { loadCore, loadFile } from '../core/load-core.js';

let N;

beforeAll(() => {
  loadCore();
  loadFile('../components/memory-card.js');
  N = window.Nous;
});

describe('renderBodyStateBars / renderEmotionBars (data-fill, no style=)', () => {
  it('emits data-fill + data-color, never inline style', () => {
    const body = N.Components.memoryCard.renderBodyStateBars({ fatigue: 0.5 });
    expect(body).toContain('data-fill="50"');
    expect(body).toContain('data-color="linear-gradient(90deg,#f87171,#fca5a5)"');
    expect(body).not.toContain('style=');

    const emo = N.Components.memoryCard.renderEmotionBars('joy', 0.8);
    expect(emo).toContain('data-fill="80"');
    expect(emo).not.toContain('style=');
  });

  it('returns empty string for missing / zero-intensity emotion', () => {
    expect(N.Components.memoryCard.renderEmotionBars('joy', 0)).toBe('');
    expect(N.Components.memoryCard.renderEmotionBars(null, 1)).toBe('');
    expect(N.Components.memoryCard.renderBodyStateBars(null)).toBe('');
  });
});

describe('applyDataStyles — fills applied from data attributes', () => {
  it('applies width + background from data attributes', () => {
    // Direct innerHTML: in-browser the markup arrives via safeSetHTML with
    // style= stripped (markup contains none — asserted above); this checks
    // the post-render pass fills width/background from data-*.
    const host = document.createElement('div');
    host.innerHTML = N.Components.memoryCard.renderBodyStateBars({ fatigue: 0.5 });
    const fill = host.querySelector('.mem-bar-fill');
    expect(fill.getAttribute('style')).toBe(null);
    N.Components.memoryCard.applyDataStyles(host);
    expect(fill.style.width).toBe('50%');
    expect(fill.style.background).toContain('linear-gradient');
  });
});
