/**
 * Loads core IIFE modules into jsdom's window context.
 * Uses new Function(code)() which runs in the global scope.
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
