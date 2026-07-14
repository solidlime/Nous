/* Debug: test file loading */
import { readFileSync } from 'fs';
import { resolve, dirname } from 'path';
import { fileURLToPath } from 'url';

const __dirname = dirname(fileURLToPath(import.meta.url));

console.log('__dirname:', __dirname);

// Try loading namespace.js
const nsPath = resolve(__dirname, 'namespace.js');
console.log('nsPath:', nsPath);
const nsCode = readFileSync(nsPath, 'utf-8');
console.log('nsCode length:', nsCode.length);

try {
  const fn = new Function(nsCode);
  fn();
  console.log('namespace loaded OK');
  console.log('window.Nous keys:', Object.keys(window.Nous));
} catch (e) {
  console.log('namespace ERROR:', e.message);
}

// Try loading dom.js
const domPath = resolve(__dirname, 'dom.js');
const domCode = readFileSync(domPath, 'utf-8');
console.log('\ndomCode length:', domCode.length);

try {
  const fn = new Function(domCode);
  fn();
  console.log('dom loaded OK');
  console.log('N.Core.esc defined:', typeof window.Nous.Core.esc);
} catch (e) {
  console.log('dom ERROR:', e.message);
}

describe('debug file loading', () => {
  it('can load core files via new Function', () => {
    expect(window.Nous.Core.esc).toBeDefined();
    expect(typeof window.Nous.Core.esc).toBe('function');
  });
});
