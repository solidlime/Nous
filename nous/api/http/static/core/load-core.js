/**
 * Loads core IIFE modules into jsdom's window context.
 *
 * NOTE (CSP): new Function() is used ONLY here in the vitest harness —
 * it never ships to the browser (CSP script-src 'self' forbids it).
 * Browser entry is plain <script src> tags, no runtime code generation.
 *
 * Usage:
 *   import { loadCore, loadStore } from './load-core.js';
 *   beforeAll(() => loadCore());
 *   beforeEach(() => loadStore());  // fresh store state
 */
import { readFileSync } from 'fs';
import { resolve, dirname } from 'path';
import { fileURLToPath } from 'url';

const __dirname = dirname(fileURLToPath(import.meta.url));

function functionEval(file) {
  const code = readFileSync(resolve(__dirname, file), 'utf-8');
  const fn = new Function(code);
  fn();
}

/**
 * Load a single core file by name (e.g. loadFile('sse.js')).
 * Test-only helper — keeps raw new Function() out of individual test files.
 */
export function loadFile(file) {
  functionEval(file);
}

/**
 * Load all core modules except store (once).
 * Call in beforeAll.
 */
export function loadCore() {
  functionEval('namespace.js');
  functionEval('constants.js');
  functionEval('dom.js');
  functionEval('time.js');
  functionEval('api.js');
}

/**
 * Load only store module (creates fresh _state / _listeners closure).
 * Call in beforeEach for state isolation.
 */
export function loadStore() {
  functionEval('store.js');
}
