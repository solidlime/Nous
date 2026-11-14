/* =================================================================
   auth.js unit tests — Bearer 付与（fetch 包装）、?token= の拾い上げ、
   SSE 用 sign()。
   ================================================================= */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const ORIGINAL_FETCH = globalThis.fetch;

async function load() {
  // auth.js は IIFE で window.Nous.Core.auth を作る。namespace.js を読まずに
  // 済むよう最小の器を先に置く。二重評価を避けるためクエリでキャッシュを外す。
  window.Nous = window.Nous || {};
  window.Nous.Core = window.Nous.Core || {};
  const mod = `../core/auth.js?t=${Math.random()}`;
  await import(/* @vite-ignore */ mod);
  return window.Nous.Core.auth;
}

function setSearch(qs) {
  window.history.replaceState({}, '', '/' + qs);
}

describe('core/auth', () => {
  beforeEach(() => {
    window.localStorage.clear();
    setSearch('');
    window.Nous = window.Nous || {};
    window.Nous.Core = window.Nous.Core || {};
    delete window.Nous.Core.auth;
  });

  afterEach(() => {
    window.fetch = ORIGINAL_FETCH;
    vi.restoreAllMocks();
  });

  it('ローカルストレージのキーを Bearer にする', async () => {
    window.localStorage.setItem('nousApiKey', 'abc123');
    const auth = await load();
    expect(auth.headers({})).toEqual({ Authorization: 'Bearer abc123' });
  });

  it('URL の ?token= を拾って保存する', async () => {
    setSearch('?token=xyz789');
    const auth = await load();
    expect(auth.token()).toBe('xyz789');
    expect(window.localStorage.getItem('nousApiKey')).toBe('xyz789');
  });

  it('キーが無ければヘッダを足さない', async () => {
    const auth = await load();
    expect(auth.headers({ 'Content-Type': 'application/json' })).toEqual({
      'Content-Type': 'application/json',
    });
  });

  it('既存の Authorization は上書きしない', async () => {
    window.localStorage.setItem('nousApiKey', 'abc123');
    const auth = await load();
    expect(auth.headers({ Authorization: 'Bearer other' })).toEqual({
      Authorization: 'Bearer other',
    });
    expect(auth.headers(new Headers({ Authorization: 'Bearer other' })).get('authorization')).toBe(
      'Bearer other',
    );
    expect(auth.headers([['authorization', 'Bearer other']])).toEqual([
      ['authorization', 'Bearer other'],
    ]);
  });

  it('Headers と配列のヘッダにも足す', async () => {
    window.localStorage.setItem('nousApiKey', 'abc123');
    const auth = await load();
    expect(auth.headers(new Headers()).get('authorization')).toBe('Bearer abc123');
    expect(auth.headers([['X-A', 'b']])).toEqual([
      ['X-A', 'b'],
      ['Authorization', 'Bearer abc123'],
    ]);
  });

  it('sign() は ?token= を足し、二重には足さない', async () => {
    window.localStorage.setItem('nousApiKey', 'a b');
    const auth = await load();
    expect(auth.sign('/api/chat/stream')).toBe('/api/chat/stream?token=a%20b');
    expect(auth.sign('/api/chat/stream?persona=herta')).toBe(
      '/api/chat/stream?persona=herta&token=a%20b',
    );
    expect(auth.sign('/api/chat/stream?token=keep')).toBe('/api/chat/stream?token=keep');
  });

  it('sign() はキーが無ければ URL をそのまま返す', async () => {
    const auth = await load();
    expect(auth.sign('/api/x')).toBe('/api/x');
  });

  it('読み込み時に fetch を包み、同一 origin にだけ Authorization を付ける', async () => {
    window.localStorage.setItem('nousApiKey', 'abc123');
    const seen = [];
    const receivers = [];
    window.fetch = vi.fn(function (name, init) {
      receivers.push(this);
      seen.push([name, init && init.headers]);
      return Promise.resolve({});
    });
    await load();
    await window.fetch('/api/x');
    await window.fetch('http://other.example/api/x');
    expect(seen[0][1]).toEqual({ Authorization: 'Bearer abc123' });
    // 別 origin にはヘッダ自体を足さない（init.headers は触られない）
    expect(seen[1][1]).toBeUndefined();
    // 包んだ後も receiver は window（detached 呼び出しに化けない）
    expect(receivers[0]).toBe(window);
    // 二重包装しない
    expect(window.fetch._nousAuthWrapped).toBe(true);
  });

  it('Request を渡されたらそのヘッダを土台にする', async () => {
    window.localStorage.setItem('nousApiKey', 'abc123');
    const seen = [];
    window.fetch = vi.fn(function (_name, init) {
      seen.push(init && init.headers);
      return Promise.resolve({});
    });
    await load();
    const req = new Request(`${window.location.origin}/api/model.glb`, {
      headers: { 'X-Test-Header': 'keep-me' },
    });
    await window.fetch(req);
    const got = seen[0];
    // realm を跨ぐと instanceof Headers が落ちるので形で読む
    const read = (o, name) => (o && typeof o.get === 'function' ? o.get(name) : o[name] || o[name.toLowerCase()]);
    expect(read(got, 'Authorization')).toBe('Bearer abc123');
    expect(read(got, 'X-Test-Header')).toBe('keep-me');
  });

  it('?token= を拾ったら URL からは消す', async () => {
    setSearch('?token=xyz789&persona=herta');
    const auth = await load();
    expect(auth.token()).toBe('xyz789');
    expect(window.location.search).toBe('?persona=herta');
  });

  it('sign() は別 origin にキーを付けない', async () => {
    window.localStorage.setItem('nousApiKey', 'abc123');
    const auth = await load();
    expect(auth.sign('http://other.example/stream')).toBe('http://other.example/stream');
  });

  it('401 が返ったら保存済みの鍵を捨てる（ローテート後の自壊を防ぐ）', async () => {
    window.localStorage.setItem('nousApiKey', 'stale');
    window.fetch = vi.fn(() => Promise.resolve({ status: 401 }));
    await load();
    const res = await window.fetch('/api/x');
    expect(res.status).toBe(401);
    expect(window.localStorage.getItem('nousApiKey')).toBeNull();
  });

  it('200 では鍵を捨てない', async () => {
    window.localStorage.setItem('nousApiKey', 'good');
    window.fetch = vi.fn(() => Promise.resolve({ status: 200 }));
    await load();
    await window.fetch('/api/x');
    expect(window.localStorage.getItem('nousApiKey')).toBe('good');
  });
});
