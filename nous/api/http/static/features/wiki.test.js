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

test('list groups pages by category with counts', async () => {
  vi.stubGlobal('fetch', vi.fn(async (url) => {
    if (url === '/api/wiki/herta') {
      return jsonResponse({ pages: [
        { slug: 'journal-2026-11-09', title: '日記', category: 'journal', sources: [] },
        { slug: 'project-nous', title: 'Nous', category: 'project', project: 'nous', sources: ['m1'] },
        { slug: 'herta', title: 'ヘルタ', category: 'persona', sources: [] },
      ]});
    }
    return jsonResponse({ slug: 'x', title: 'x', body: '' });
  }));
  await W.loadWiki();
  const list = document.getElementById('wiki-list');
  const summaries = [...list.querySelectorAll('details > summary')].map((s) => s.textContent);
  expect(summaries.length).toBe(3);
  expect(summaries[0]).toContain('日記');
  expect(summaries[1]).toContain('プロジェクト');
  const projectGroup = list.querySelectorAll('details')[1];
  expect(projectGroup.textContent).toContain('nous');   // project 名は項目のメタに出す
  expect(summaries[2]).toContain('人柄');
});

test('search box debounces into ?q= requests', async () => {
  vi.useFakeTimers();
  const fetchMock = vi.fn(async () => jsonResponse({ pages: [] }));
  vi.stubGlobal('fetch', fetchMock);
  document.body.insertAdjacentHTML('beforeend', '<input id="wiki-search" />');
  W._state.q = '';
  // 配線は DOMContentLoaded で走るので、同じ入力要素に直接バインドし直す
  const { loadWiki } = W;
  const input = document.getElementById('wiki-search');
  input.addEventListener('input', () => {
    if (W._state.timer) clearTimeout(W._state.timer);
    W._state.timer = setTimeout(() => loadWiki(input.value.trim()), 250);
  });
  input.value = '索引';
  input.dispatchEvent(new Event('input'));
  expect(fetchMock).not.toHaveBeenCalled();
  vi.advanceTimersByTime(300);
  await Promise.resolve();
  expect(fetchMock).toHaveBeenCalled();
  expect(fetchMock.mock.calls[0][0]).toBe('/api/wiki/herta?q=' + encodeURIComponent('索引'));
  vi.useRealTimers();
  document.getElementById('wiki-search').remove();
});

test('empty search result says no match instead of the empty-wiki placeholder', async () => {
  vi.stubGlobal('fetch', vi.fn(async () => jsonResponse({ pages: [] })));
  await W.loadWiki('存在しない語');
  const text = document.getElementById('wiki-list').textContent;
  expect(text).toContain('一致するページは無い');
  expect(text).not.toContain('ページがまだない');
});
