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
  expect(html).toContain('skeleton');
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
