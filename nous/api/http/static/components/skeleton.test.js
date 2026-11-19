/* skeleton.test.js — #93: self-managed switching reads the nav button's
   data-self-managed (emitted by dashboard.py), not a static Set copy.
   Covers: self-managed early return, default skeleton swap, register(). */
import { loadCore, loadFile } from '../core/load-core.js';

let N;

beforeAll(() => {
  loadCore();
  loadFile('../components/skeleton.js');
  N = window.Nous;
});

beforeEach(() => {
  document.body.innerHTML =
    '<button class="tab-btn" data-tab="sm" data-self-managed="true"></button>' +
    '<button class="tab-btn" data-tab="plain"></button>' +
    '<div id="tab-sm"><div id="sm-content">KEEP</div></div>' +
    '<div id="tab-plain"><div id="plain-content">KEEP</div></div>';
});

it('leaves self-managed tab content untouched (data-self-managed)', () => {
  N.Components.skeleton.show('sm');
  expect(document.getElementById('sm-content').innerHTML).toBe('KEEP');
});

it('replaces non-self-managed content with the default skeleton', () => {
  N.Components.skeleton.show('plain');
  const html = document.getElementById('plain-content').innerHTML;
  expect(html).not.toBe('KEEP');
  expect(html).toContain('skeleton-card');
});

it('prefers a registered skeleton over the default', () => {
  N.Components.skeleton.register('plain', '<div class="skeleton CUSTOM"></div>');
  N.Components.skeleton.show('plain');
  expect(document.getElementById('plain-content').innerHTML).toContain('CUSTOM');
});

it('panelContentEl: -content child, or null — never the panel root', () => {
  document.body.innerHTML +=
    '<div id="tab-bare"><div id="act-feed"></div></div>';
  expect(N.Components.skeleton.panelContentEl('plain').id).toBe('plain-content');
  expect(N.Components.skeleton.panelContentEl('bare')).toBeNull();
  expect(N.Components.skeleton.panelContentEl('missing')).toBeNull();
});

it('panelContentEl: picks the direct child even when a nested -content id comes first (#93)', () => {
  // overview/memories panels embed ids like #block-modal-content / #edit-content —
  // a descendant query would return whichever appears first, so :scope > is load-bearing.
  document.body.innerHTML +=
    '<div id="tab-nested"><div class="wrap"><div id="nested-modal-content">NESTED</div></div>' +
    '<div id="nested-content">DIRECT</div></div>';
  expect(N.Components.skeleton.panelContentEl('nested').id).toBe('nested-content');
});

/* #111: elapsed-seconds badge — a slow fetch reads as "slow", not "frozen" */
describe('skeleton elapsed badge (#111)', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    document.body.innerHTML =
      '<button class="tab-btn" data-tab="plain"></button>' +
      '<div id="tab-plain"><div id="plain-content">KEEP</div></div>';
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it('ticks seconds while the skeleton is displayed', () => {
    N.Components.skeleton.show('plain');
    const badge = document.querySelector('[data-skeleton-elapsed]');
    expect(badge).not.toBeNull();
    expect(badge.textContent).toBe('Loading…');
    vi.advanceTimersByTime(1000);
    expect(badge.textContent).toBe('Loading… 1s');
    vi.advanceTimersByTime(2000);
    expect(badge.textContent).toBe('Loading… 3s');
  });

  it('stops the timer when the badge leaves the DOM (loader swapped the panel)', () => {
    N.Components.skeleton.show('plain');
    expect(vi.getTimerCount()).toBe(1);
    const badge = document.querySelector('[data-skeleton-elapsed]');
    document.getElementById('plain-content').innerHTML = '';
    vi.advanceTimersByTime(5000);
    expect(vi.getTimerCount()).toBe(0);
    // no throw; the self-stopped timer never touched the detached badge
    expect(badge.textContent).toBe('Loading…');
  });

  it('re-showing resets the elapsed counter (previous timer discarded)', () => {
    N.Components.skeleton.show('plain');
    vi.advanceTimersByTime(3000);
    N.Components.skeleton.show('plain');
    expect(vi.getTimerCount()).toBe(1); // old interval discarded, exactly one live timer
    const badge = document.querySelector('[data-skeleton-elapsed]');
    expect(badge.textContent).toBe('Loading…');
    vi.advanceTimersByTime(1000);
    expect(badge.textContent).toBe('Loading… 1s');
  });

  it('self-kills at 60s even if the panel is never re-swapped (orphan loader path)', () => {
    N.Components.skeleton.show('plain');
    expect(vi.getTimerCount()).toBe(1);
    vi.advanceTimersByTime(61000);
    expect(vi.getTimerCount()).toBe(0);
  });

  it('stops the previous timer when switching to a self-managed tab', () => {
    N.Components.skeleton.show('plain');
    expect(vi.getTimerCount()).toBe(1);
    document.body.innerHTML +=
      '<button class="tab-btn" data-tab="sm" data-self-managed="true"></button>' +
      '<div id="tab-sm"><div id="sm-content">KEEP</div></div>';
    N.Components.skeleton.show('sm');
    expect(vi.getTimerCount()).toBe(0);
    expect(document.getElementById('sm-content').innerHTML).toBe('KEEP');
  });

  it('attaches the badge to registered skeletons too', () => {
    N.Components.skeleton.register('plain', '<div class="skeleton CUSTOM"></div>');
    N.Components.skeleton.show('plain');
    const content = document.getElementById('plain-content');
    expect(content.innerHTML).toContain('CUSTOM');
    expect(content.querySelector('[data-skeleton-elapsed]')).not.toBeNull();
  });
});
