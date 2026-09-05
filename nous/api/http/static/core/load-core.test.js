/* =================================================================
   load-core / namespace harness tests — Task 8 (no window crash in tests)
   ================================================================= */
import { loadCore, loadStore } from './load-core.js';

describe('load-core harness', () => {
  it('loads core modules without throwing', () => {
    expect(() => loadCore()).not.toThrow();
    expect(typeof window.Nous).toBe('object');
    expect(typeof window.Nous.Core.esc).toBe('function');
    expect(typeof window.Nous.Core.api).toBe('function');
    expect(typeof window.Nous.Core.safeSetHTML).toBe('function');
  });

  it('namespace exposes all sub-namespaces', () => {
    loadCore();
    expect(typeof window.Nous.Core).toBe('object');
    expect(typeof window.Nous.Components).toBe('object');
    expect(typeof window.Nous.Chat).toBe('object');
    expect(typeof window.Nous.Features).toBe('object');
  });

  it('loadStore gives fresh isolated state', () => {
    loadCore();
    loadStore();
    expect(typeof window.Nous.Core.store).toBe('object');
  });
});
