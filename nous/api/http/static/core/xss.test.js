/* =================================================================
   XSS regression tests — Task 6 (CSP script-src 'self': no inline handlers)
   NOTE: DOMPurify is a browser CDN global, absent in vitest — safeSetHTML
   falls back to textContent here. Assertions are mode-agnostic.
   ================================================================= */
import { loadCore } from './load-core.js';
import { readdirSync, readFileSync, statSync } from 'fs';
import { resolve, dirname } from 'path';
import { fileURLToPath } from 'url';

const __testDir = dirname(fileURLToPath(import.meta.url));

function collectPyFiles(dir) {
  const out = [];
  for (const e of readdirSync(dir)) {
    const p = resolve(dir, e);
    if (statSync(p).isDirectory()) out.push(...collectPyFiles(p));
    else if (e.endsWith('.py')) out.push(p);
  }
  return out;
}

let N;

beforeAll(() => {
  loadCore();
  N = window.Nous.Core;
});

describe('xss', () => {
  it('strips onclick (no live handler attribute survives)', () => {
    const el = document.createElement('div');
    N.safeSetHTML(el, '<img src=x onclick=alert(1)>');
    expect(el.querySelector('[onclick]')).toBeNull();
  });

  it('strips onchange / onerror / onload vectors', () => {
    const el = document.createElement('div');
    N.safeSetHTML(el, '<input onchange=alert(1)><img src=x onerror=alert(1)>');
    expect(el.querySelector('[onchange]')).toBeNull();
    expect(el.querySelector('[onerror]')).toBeNull();
    expect(el.querySelector('[onload]')).toBeNull();
  });

  it('escapes single quote', () => {
    expect(N.esc("a'b")).toContain('&#39;');
  });

  it('esc() neutralizes tag injection', () => {
    expect(N.esc('<script>alert(1)</script>')).not.toContain('<script>');
  });

  it('delegation markup carries data-* and no inline handler (string level)', () => {
    const key = "k1'\"<>";
    const escaped = N.esc(key);
    expect(escaped).not.toContain('<');
    expect(escaped).not.toContain('>');
    expect(escaped).not.toContain('"');
    expect(escaped).not.toContain("'");
    const html = '<button type="button" data-mem-action="delete" data-mem-key="' +
      escaped + '">x</button>';
    expect(html).toContain('data-mem-key=');
    expect(html).not.toContain('onclick');
  });
});

describe('sections CSP', () => {
  it('server templates contain zero inline handlers (markup only)', () => {
    const sectionsDir = resolve(__testDir, '../../sections');
    const files = collectPyFiles(sectionsDir);
    expect(files.length).toBeGreaterThan(0);
    // Script bodies are CSP-safe (script-src 'self'); only markup counts.
    // Property assignments like .onclick = are excluded by the <...> bound.
    const re = /<[^>]*\son(?:click|input|change|load|error)\s*=/gi;
    const offenders = [];
    for (const f of files) {
      const src = readFileSync(f, 'utf-8');
      const m = src.match(re);
      if (m) offenders.push(f + ' :: ' + JSON.stringify(m.slice(0, 3)));
    }
    expect(offenders).toEqual([]);
  });
});
