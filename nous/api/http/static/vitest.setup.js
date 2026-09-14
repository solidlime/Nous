/* vitest setup — Node 25 の実験的 Web Storage 対策。

   Node 25 はグローバルに `localStorage` を持つが、`--localstorage-file` が無いと
   機能せず `clear()` すら undefined になる。vitest の jsdom 環境ではこのグローバルが
   jsdom 自身の Storage を覆い隠すため、localStorage.clear() を使うテストが軒並み
   落ちる（chat-mode.test.js など）。動いている環境では何もしない。 */
class MemoryStorage {
  #map = new Map();
  get length() {
    return this.#map.size;
  }
  key(i) {
    return Array.from(this.#map.keys())[i] ?? null;
  }
  getItem(k) {
    const key = String(k);
    return this.#map.has(key) ? this.#map.get(key) : null;
  }
  setItem(k, v) {
    this.#map.set(String(k), String(v));
  }
  removeItem(k) {
    this.#map.delete(String(k));
  }
  clear() {
    this.#map.clear();
  }
}

if (typeof globalThis.localStorage?.clear !== 'function') {
  for (const name of ['localStorage', 'sessionStorage']) {
    Object.defineProperty(globalThis, name, {
      value: new MemoryStorage(),
      configurable: true,
      writable: true,
    });
  }
}
