/* =================================================================
   ready.js — v4 lazy bootstrap: manifest parsing, serial script load,
   whenReady, tab-css injection.
   ================================================================= */
import { loadFile, loadCore } from './load-core.js';

const MANIFEST = {
  v: 4,
  css: '/static/styles/tabs-lazy.css',
  deps: { chart: 'https://cdn.test/chart.js' },
  base: ['chart'],
  shared: ['/static/core/time.js'],
  tabs: {
    wiki: { scripts: ['/static/features/wiki.js'] },
    graph: { scripts: ['/static/features/graph.js'], deps: ['chart'] },
    chat: { scripts: ['/static/chat/chat.chunk.js'], ready: 'Nous.Chat.chunk.load' },
  },
};

let C;
let loaded;

beforeAll(() => {
  document.head.innerHTML =
    '<script type="application/json" id="lazy-manifest">' + JSON.stringify(MANIFEST) + '</script>';
  loadCore();
  loadFile('ready.js');
  C = window.Nous.Core;
  loaded = [];
  C.loadScript = (src) => {
    loaded.push(src);
    return Promise.resolve();
  };
});

beforeEach(() => {
  loaded.length = 0;
});

describe('N.Core.whenReady', () => {
  it('runs immediately once the document is parsed', () => {
    let ran = false;
    C.whenReady(() => { ran = true; });
    expect(ran).toBe(true);
  });

  it('defers while the document is still loading', () => {
    const spy = vi.spyOn(document, 'readyState', 'get').mockReturnValue('loading');
    let ran = false;
    C.whenReady(() => { ran = true; });
    expect(ran).toBe(false);
    document.dispatchEvent(new Event('DOMContentLoaded'));
    expect(ran).toBe(true);
    spy.mockRestore();
  });
});

describe('C.loadDep', () => {
  it('loads the manifest URL for a dep name', async () => {
    await C.loadDep('chart');
    expect(loaded).toEqual(['https://cdn.test/chart.js']);
  });

  it('resolves silently for an unknown dep', async () => {
    await C.loadDep('nope');
    expect(loaded).toEqual([]);
  });
});

describe('C.loadTabScripts', () => {
  it('loads base deps, shared cores, then the tab sources — in order', async () => {
    await C.loadTabScripts('wiki');
    expect(loaded).toEqual([
      'https://cdn.test/chart.js',
      '/static/core/time.js',
      '/static/features/wiki.js',
    ]);
  });

  it('loads a tab once and reuses the promise', async () => {
    await C.loadTabScripts('graph');
    const first = loaded.slice();
    await C.loadTabScripts('graph');
    expect(first).toEqual([
      'https://cdn.test/chart.js',
      '/static/core/time.js',
      '/static/features/graph.js',
    ]);
    expect(loaded.length).toBe(first.length);
  });

  it('awaits the tab own loader hook when the manifest names one', async () => {
    let booted = false;
    window.Nous.Chat = { chunk: { load: () => { booted = true; return Promise.resolve(); } } };
    await C.loadTabScripts('chat');
    expect(booted).toBe(true);
  });

  it('resolves false for a tab the manifest does not know', async () => {
    await expect(C.loadTabScripts('nope')).resolves.toBe(false);
  });
});

describe('tab css', () => {
  it('attaches the lazy stylesheet once the shell is up', () => {
    const link = document.head.querySelector('link[href="/static/styles/tabs-lazy.css"]');
    expect(link).not.toBeNull();
    expect(link.rel).toBe('stylesheet');
  });
});
