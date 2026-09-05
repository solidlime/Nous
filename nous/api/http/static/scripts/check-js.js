/* lint:js — syntax check every shipped JS file with node --check.
 * Modules here are IIFE (!function over window.Nous) or ESM (tests/config);
 * no bundler, no new Function in shipped code (CSP script-src 'self').
 * load-core.js uses new Function ONLY inside the vitest harness.
 */
import { execFileSync } from 'child_process';
import { readdirSync, statSync } from 'fs';
import { join, relative } from 'path';

const root = join(import.meta.dirname, '..');
const files = [];
(function walk(dir) {
  for (const e of readdirSync(dir)) {
    if (e === 'node_modules') continue;
    const p = join(dir, e);
    if (statSync(p).isDirectory()) { walk(p); continue; }
    if (e.endsWith('.js')) files.push(p);
  }
})(root);

let failed = 0;
for (const f of files) {
  try {
    execFileSync(process.execPath, ['--check', f], { stdio: 'pipe' });
  } catch (e) {
    failed += 1;
    console.error('SYNTAX FAIL: ' + relative(root, f));
    console.error(String(e.stderr || e.message).split('\n').slice(0, 5).join('\n'));
  }
}
console.log(failed ? failed + ' file(s) failed' : 'OK: ' + files.length + ' files syntax-clean');
process.exit(failed ? 1 : 0);
