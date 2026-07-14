/* Debug: test api.js specifically */
import { readFileSync } from 'fs';
import { resolve, dirname } from 'path';
import { fileURLToPath } from 'url';

const __dirname = dirname(fileURLToPath(import.meta.url));

// First load prerequisites
const prereqs = ['namespace.js', 'constants.js', 'dom.js', 'time.js'];
for (const file of prereqs) {
  const code = readFileSync(resolve(__dirname, file), 'utf-8');
  new Function(code)();
}
console.log('Prereqs loaded, N.Core keys:', Object.keys(window.Nous.Core));

// Now try api.js
const apiCode = readFileSync(resolve(__dirname, 'api.js'), 'utf-8');
console.log('api.js code:', apiCode);
try {
  const fn = new Function(apiCode);
  console.log('fn created');
  fn();
  console.log('fn executed');
} catch (e) {
  console.log('ERROR:', e.message);
  console.log('STACK:', e.stack?.split('\n').slice(0, 8).join('\n'));
}

// Also test: does Node have fetch?
console.log('typeof globalThis.fetch:', typeof globalThis.fetch);
console.log('typeof window.fetch:', typeof window?.fetch);

describe('debug api.js', () => {
  it('window.Nous.Core.api defined', () => {
    expect(window.Nous.Core.api).toBeDefined();
  });
});
