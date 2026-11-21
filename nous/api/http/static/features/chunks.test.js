/* =================================================================
   TAB CHUNKS — v4 第1段階の薄いローダ 3 本（overview / memories / misc）
   A の manifest（sections/base.py LAZY_MANIFEST）が SSOT なので、ここでは
   「chunk が宣言した配列 = manifest の並び」と「load() が宣言順に 1 回だけ
   <script> を積む」ことだけ固定する。順序が契約（N.Features.* の後勝ち
   定義）。パスの実在は node --check と CI の走査側で担保する。
   ================================================================= */
import overviewSrc from './overview.chunk.js?raw';
import memoriesSrc from './memories.chunk.js?raw';
import miscSrc from './misc.chunk.js?raw';

const CHUNK_SOURCES = {
  'overview.chunk.js': overviewSrc,
  'memories.chunk.js': memoriesSrc,
  'misc.chunk.js': miscSrc,
};

const CHUNKS = {
  'overview.chunk.js': {
    ns: ['Features', 'Overview'],
    scripts: [
      '/static/features/overview/overview-blocks.js',
      '/static/features/overview/overview-inventory.js',
      '/static/features/overview/overview-core.js',
      '/static/features/overview/overview-stats.js',
      '/static/features/overview/overview-charts.js',
      '/static/features/overview/overview-context.js',
    ],
  },
  'memories.chunk.js': {
    ns: ['Features', 'Memories'],
    scripts: [
      '/static/features/memories/memories-core.js',
      '/static/features/memories/memories-list.js',
      '/static/features/memories/memories-search.js',
      '/static/features/memories/memories-edit.js',
    ],
  },
  'misc.chunk.js': {
    ns: ['Features', 'Misc'],
    scripts: [
      '/static/features/wiki.js',
      '/static/features/projects.js',
      '/static/features/activity.js',
      '/static/features/timeline.js',
      '/static/features/settings/settings-validation.js',
      '/static/features/settings/settings-save.js',
      '/static/features/settings/settings-ui.js',
      '/static/features/settings/settings-form.js',
      '/static/features/settings/settings-core.js',
      '/static/features/graph.js',
    ],
  },
};

function chunkOf(file) {
  const node = CHUNKS[file].ns.reduce((o, k) => (o ? o[k] : undefined), window.Nous);
  return node && node.chunk;
}

beforeAll(() => {
  window.Nous = { Core: { refreshIcons: () => {} }, Features: {} };
  // chunk は素の IIFE（ブラウザと同じ経路）。jsdom 上でそのまま評価する。
  Object.keys(CHUNK_SOURCES).forEach((f) => { new Function(CHUNK_SOURCES[f])(); });
});

describe.each(Object.keys(CHUNKS))('%s', (file) => {
  it('N.Features.<tab>.chunk に scripts と load を公開する', () => {
    const chunk = chunkOf(file);
    expect(chunk).toBeTruthy();
    expect(chunk.scripts).toEqual(CHUNKS[file].scripts);
    expect(typeof chunk.load).toBe('function');
  });

  it('スクリプトパスは /static 配下の .js のみ', () => {
    CHUNKS[file].scripts.forEach((src) => {
      expect(src).toMatch(/^\/static\/[\w\/-]+\.js$/);
    });
  });

  it('load() は宣言順に 1 回だけ読み込み、2 回目は再取得しない', async () => {
    const chunk = chunkOf(file);
    const appended = [];
    const orig = document.head.appendChild.bind(document.head);
    document.head.appendChild = (el) => {
      appended.push(el.getAttribute('src'));
      if (el.onload) setTimeout(el.onload, 0);
      return el;
    };
    try {
      await chunk.load();
      const first = appended.slice();
      await chunk.load();
      expect(first).toEqual(CHUNKS[file].scripts);
      expect(appended).toEqual(first); // memoize: 2 回目は積まない
    } finally {
      document.head.appendChild = orig;
    }
  });
});
