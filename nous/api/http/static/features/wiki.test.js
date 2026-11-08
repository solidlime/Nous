/* =================================================================
   wiki viewer tests — 一覧取得 → 本文描画 → [[link]] 遷移 / 失敗時
   Covers: list render, page fetch on click, wikilink rewrite,
   empty wiki, list fetch failure.
   ================================================================= */
import { readFileSync } from 'fs';
import { resolve, dirname } from 'path';
import { fileURLToPath } from 'url';
import { loadCore } from '../core/load-core.js';

const __dirname = dirname(fileURLToPath(import.meta.url));

let W;

function jsonResponse(payload) {
  return {
    ok: true,
    status: 200,
    headers: { get: () => 'application/json' },
    json: async () => payload,
  };
}

function setPersona(p) {
  window.S = window.S || {};
  window.S.persona = p;
  globalThis.S = window.S;
}

beforeAll(() => {
  loadCore();
  // 実ブラウザでは DOMPurify が居る。未定義だと safeSetHTML が textContent に
  // フォールバックし、data-* 要素や <a> を検証できないので素通しスタブを置く。
  globalThis.DOMPurify = { sanitize: (html) => html };
  // 実ブラウザでは marked が同梱されている。テストでは markdown リンクだけを
  // <a> に起こす最小スタブで [[slug]] 書き換えとクリック配線を検証する。
  globalThis.marked = {
    parse: (md) => md.replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2">$1</a>'),
  };
  document.body.innerHTML =
    '<div id="wiki-list"></div><div id="wiki-article-head"></div><div id="wiki-article-body"></div>';
  // base.js と同じ順序を再現する: 機能スクリプトは読み込み時点の window.S を保持する
  window.S = { persona: 'herta', tab: 'wiki' };
  globalThis.N = window.Nous;
  const code = readFileSync(resolve(__dirname, 'wiki.js'), 'utf-8');
  new Function(code)();
  W = window.Nous.Features.Wiki;
});

beforeEach(() => {
  W._state.pages = [];
  W._state.current = null;
  setPersona('herta');
  vi.restoreAllMocks();
});

test('list renders pages and auto-loads the first one', async () => {
  const fetchMock = vi.fn(async (url) => {
    if (url === '/api/wiki/herta') {
      return jsonResponse({
        persona: 'herta',
        pages: [
          { slug: 'project-nous', title: 'Nous', sources: ['a', 'b'], updated: '2026-11-08T10:00:00+09:00' },
          { slug: 'persona', title: 'Persona', sources: [], updated: '2026-11-07T10:00:00+09:00' },
        ],
      });
    }
    return jsonResponse({ slug: 'project-nous', title: 'Nous', body: '本文です', sources: ['a', 'b'] });
  });
  vi.stubGlobal('fetch', fetchMock);

  await W.loadWiki();

  const items = document.querySelectorAll('[data-wiki-slug]');
  expect(items).toHaveLength(2);
  expect(items[0].getAttribute('data-wiki-slug')).toBe('project-nous');
  expect(items[0].textContent).toContain('2 sources');
  expect(fetchMock).toHaveBeenCalledWith('/api/wiki/herta/project-nous', expect.anything());
  expect(document.getElementById('wiki-article-body').textContent).toContain('本文です');
  expect(document.querySelector('.wiki-item.active')).not.toBeNull();
});

test('clicking a list item loads that page', async () => {
  const fetchMock = vi.fn(async (url) => {
    if (url === '/api/wiki/herta') {
      return jsonResponse({ pages: [{ slug: 'a', title: 'A' }, { slug: 'b', title: 'B' }] });
    }
    if (url === '/api/wiki/herta/a') return jsonResponse({ slug: 'a', title: 'A', body: 'page A' });
    return jsonResponse({ slug: 'b', title: 'B', body: 'page B' });
  });
  vi.stubGlobal('fetch', fetchMock);
  await W.loadWiki();

  document.querySelector('[data-wiki-slug="b"]').click();
  await vi.waitFor(() => {
    expect(document.getElementById('wiki-article-body').textContent).toContain('page B');
  });
});

test('[[slug]] becomes an internal link that navigates', async () => {
  const fetchMock = vi.fn(async (url) => {
    if (url === '/api/wiki/herta') {
      return jsonResponse({ pages: [{ slug: 'a', title: 'A' }] });
    }
    if (url === '/api/wiki/herta/a') {
      return jsonResponse({ slug: 'a', title: 'A', body: 'see [[project-nous]] too' });
    }
    return jsonResponse({ slug: 'project-nous', title: 'Nous', body: 'target' });
  });
  vi.stubGlobal('fetch', fetchMock);
  await W.loadWiki();

  const link = document.querySelector('#wiki-article-body a[href^="#wiki:"]');
  expect(link).not.toBeNull();
  link.click();
  await vi.waitFor(() => {
    expect(document.getElementById('wiki-article-body').textContent).toContain('target');
  });
  expect(fetchMock).toHaveBeenCalledWith('/api/wiki/herta/project-nous', expect.anything());
});

test('empty wiki shows the placeholder and no article', async () => {
  vi.stubGlobal('fetch', vi.fn(async () => jsonResponse({ pages: [] })));
  await W.loadWiki();
  expect(document.getElementById('wiki-list').textContent).toContain('ページがまだない');
  expect(document.getElementById('wiki-article-head').textContent.trim()).toBe('');
});

test('list fetch failure degrades to a message (no throw)', async () => {
  vi.stubGlobal('fetch', vi.fn(async () => { throw new Error('boom'); }));
  await expect(W.loadWiki()).resolves.toBeUndefined();
  expect(document.getElementById('wiki-list').textContent).toContain('wiki を取得できない');
});

test('no persona → no fetch', async () => {
  setPersona('');
  const fetchMock = vi.fn();
  vi.stubGlobal('fetch', fetchMock);
  await W.loadWiki();
  expect(fetchMock).not.toHaveBeenCalled();
});
