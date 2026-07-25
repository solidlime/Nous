/* =================================================================
   Tests for core/dom.js
   ================================================================= */
import { loadCore } from './load-core.js';

let N;

beforeAll(() => {
  loadCore();
  N = window.Nous.Core;
});

describe('N.Core.esc', () => {
  it('escapes HTML entities (ampersand)', () => {
    expect(N.esc('a & b')).toBe('a &amp; b');
  });

  it('escapes HTML entities (less-than, greater-than)', () => {
    expect(N.esc('<tag>')).toBe('&lt;tag&gt;');
  });

  it('escapes HTML entities (double quote)', () => {
    expect(N.esc('say "hello"')).toBe('say &quot;hello&quot;');
  });

  it('does not escape single quote (textContent→innerHTML behavior)', () => {
    expect(N.esc("it's fine")).toBe("it's fine");
  });

  it('handles null', () => {
    expect(N.esc(null)).toBe('');
  });

  it('handles undefined', () => {
    expect(N.esc(undefined)).toBe('');
  });

  it('handles empty string', () => {
    expect(N.esc('')).toBe('');
  });
});

describe('N.Core.truncate', () => {
  it('shortens long strings with ellipsis', () => {
    expect(N.truncate('Hello Beautiful World', 5)).toBe('Hello...');
  });

  it('returns full string when shorter than limit', () => {
    expect(N.truncate('Hi', 10)).toBe('Hi');
  });

  it('returns full string when exactly at limit', () => {
    expect(N.truncate('Hello', 5)).toBe('Hello');
  });

  it('handles null', () => {
    expect(N.truncate(null, 5)).toBe('');
  });

  it('handles undefined', () => {
    expect(N.truncate(undefined, 5)).toBe('');
  });

  it('handles empty string', () => {
    expect(N.truncate('', 5)).toBe('');
  });

  it('handles number 0 (falsy → empty string)', () => {
    expect(N.truncate(0, 5)).toBe('');
  });
});

describe('N.Core.safeSetHTML', () => {
  it('falls back to textContent when DOMPurify is unavailable', () => {
    const el = document.createElement('div');
    N.safeSetHTML(el, '<b>bold</b>');
    expect(el.innerHTML).toBe('&lt;b&gt;bold&lt;/b&gt;');
    expect(el.textContent).toBe('<b>bold</b>');
  });

  it('handles empty string', () => {
    const el = document.createElement('div');
    N.safeSetHTML(el, '');
    expect(el.textContent).toBe('');
  });

  it('handles plain text without tags', () => {
    const el = document.createElement('div');
    N.safeSetHTML(el, 'hello world');
    expect(el.textContent).toBe('hello world');
  });

  it('is accessible as N.Core.safeSetHTML', () => {
    expect(typeof N.safeSetHTML).toBe('function');
    expect(N.safeSetHTML).toBe(N.safeSetHTML);
  });
});
