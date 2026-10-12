/* =================================================================
   firing mode tests — multi-hop 記憶探索のリアルタイム演出
   Covers: FLASH_COLORS 契約拡張、検索リクエスト契約 (decision/hops/
   request_id/limit)、meta.request_id によるイベントフィルタ、hop
   パイプライン (seed 順次点灯 / propagate / decision / hop_stop 締め)、
   枝刈りフェード、結果パネル top20 (textContent のみ・XSS 耐性)、
   パルスのジッタ、prefers-reduced-motion、モードトグルと SSE チャンネル。
   ================================================================= */
import { readFileSync } from 'fs';
import { resolve, dirname } from 'path';
import { fileURLToPath } from 'url';
import { loadCore, loadFile } from '../core/load-core.js';

const __dirname = dirname(fileURLToPath(import.meta.url));

const instances = [];
let G, F;

/* vis.DataSet 風のフェイク（get/update/clear/remove を備え、
   get() 引数なしで全件配列を返す） */
function fakeDs() {
  const nodeStore = {};
  const edgeStore = {};
  return {
    nodeStore, edgeStore,
    nodes: {
      get: (id) => (id == null ? Object.values(nodeStore) : (nodeStore[id] || null)),
      update: (patch) => {
        if (!nodeStore[patch.id]) nodeStore[patch.id] = { id: patch.id };
        Object.assign(nodeStore[patch.id], patch);
      },
      clear: () => { Object.keys(nodeStore).forEach((k) => delete nodeStore[k]); },
    },
    edges: {
      get: (id) => (id == null ? Object.values(edgeStore) : (edgeStore[id] || null)),
      update: (patch) => {
        if (!edgeStore[patch.id]) edgeStore[patch.id] = { id: patch.id };
        Object.assign(edgeStore[patch.id], patch);
      },
      remove: (ids) => {
        (Array.isArray(ids) ? ids : [ids]).forEach((id) => delete edgeStore[id]);
      },
      clear: () => { Object.keys(edgeStore).forEach((k) => delete edgeStore[k]); },
    },
  };
}

function stubFetch(payload, ok = true) {
  const fn = vi.fn(() => Promise.resolve({
    ok,
    status: ok ? 200 : 500,
    headers: { get: () => 'application/json' },
    json: () => Promise.resolve(payload),
  }));
  vi.stubGlobal('fetch', fn);
  return fn;
}

function emitWiring(es, ev) {
  es.emit('wiring', JSON.stringify(ev));
}

function flushAsync() {
  return vi.advanceTimersByTimeAsync(10); // マイクロタスク（fetch 後続）も流す
}

beforeAll(() => {
  document.body.innerHTML =
    '<section id="tab-graph"><div id="graph-content"></div></section>';
  loadCore();
  loadFile('sse.js'); // 発火モードも共有ストリームマネージャに乗る
  window.S = { persona: 'p1', tab: 'graph' };
  globalThis.N = window.Nous;
  const code = readFileSync(resolve(__dirname, 'graph.js'), 'utf-8');
  new Function(code)(); // graph.js 本体 + 末尾の発火モードモジュール
  G = window.Nous.Features.Graph;
  F = window.Nous.Features.GraphFire;
});

beforeEach(() => {
  instances.length = 0;
  vi.useFakeTimers();
  vi.stubGlobal('EventSource', class {
    constructor(url) {
      this.url = url;
      this._listeners = {};
      this.close = vi.fn();
      instances.push(this);
    }
    addEventListener(ev, fn) {
      (this._listeners[ev] = this._listeners[ev] || []).push(fn);
    }
    emit(ev, data) {
      (this._listeners[ev] || []).forEach((fn) => fn({ data }));
    }
  });
  F.setMode(false);
  F.setFireDataSet(fakeDs());
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

/* fetch をスタブし、発火モードを ON にして実行 */
function startRun(payload) {
  const fetchMock = stubFetch(payload || { results: [] });
  F.setMode(true);
  document.getElementById('graph-fire-query').value = 'firing test';
  expect(F.run()).toBe(true);
  return fetchMock;
}

describe('FLASH_COLORS contract', () => {
  it('adds the 4 firing colors without touching the existing 5', () => {
    expect(G.FLASH_COLORS.novelty_gate).toBe('#ffd60a');
    expect(G.FLASH_COLORS.replay_fire).toBe('#7c7cf0');
    expect(G.FLASH_COLORS.recall_boost).toBe('#30d158');
    expect(G.FLASH_COLORS.link_fire).toBe('#bf5af2');
    expect(G.FLASH_COLORS.ppr_hit).toBe('#007aff');
    expect(G.FLASH_COLORS.decision_pass).toBe('#30d158');
    expect(G.FLASH_COLORS.decision_reject).toBe('#48484a');
    expect(G.FLASH_COLORS.hop_start).toBe('#ff9f0a');
    expect(G.FLASH_COLORS.hop_stop).toBe('#64d2ff');
  });
});

describe('request contract', () => {
  it('fires /api/search with decision/hops/request_id/limit and subscribes the SSE channel first', async () => {
    const fetchMock = startRun();
    const url = fetchMock.mock.calls[0][0];
    expect(url).toMatch(
      /^\/api\/search\/p1\?q=firing%20test&decision=1&hops=2&request_id=[0-9a-f-]{36}&limit=20$/
    );
    expect(url).toContain(F._state().session.requestId);
    // SSE が先に（同時に）繋がっている・一意チャンネル
    expect(instances.length).toBe(1);
    expect(instances[0].url).toBe('/api/memory/wiring/stream?persona=p1');
  });

  it('reflects decision=0 and clamps hops to 1..5', async () => {
    const fetchMock = startRun();
    document.getElementById('graph-fire-decision').checked = false;
    document.getElementById('graph-fire-hops').value = '9';
    document.getElementById('graph-fire-query').value = 'q2';
    F.run();
    const url = fetchMock.mock.calls[1][0];
    expect(url).toContain('decision=0');
    expect(url).toContain('hops=5');
  });

  it('shows search failure in the status without throwing', async () => {
    stubFetch({ error: 'boom' }, false);
    F.setMode(true);
    document.getElementById('graph-fire-query').value = 'q3';
    F.run();
    await flushAsync();
    expect(document.getElementById('graph-fire-status').textContent).toContain('boom');
  });
});

describe('hop event pipeline', () => {
  it('filters by meta.request_id, lights seeds, propagates along edges, decides, and stops', async () => {
    startRun({ results: [{ memory: { key: 'm1', content: 'memory one content', tags: ['tag-a'] }, score: 0.9 }] });
    await flushAsync(); // fetch レスポンス取り込み
    const rid = F._state().session.requestId;
    const ds = F._state().dataSet;
    const es = instances[0];

    // 自分の UUID 以外のイベントは消費しない
    emitWiring(es, { seq: 1, kind: 'ppr_hit', source: 'zz', weight: 1, meta: { request_id: 'other-run' } });
    expect(ds.nodeStore.zz).toBeUndefined();

    // hop_start
    emitWiring(es, { seq: 2, kind: 'hop_start', source: '', target: '', weight: 0, meta: { persona: 'p1', hop: 1, request_id: rid } });
    expect(F._state().session.hop).toBe(1);
    expect(document.getElementById('graph-fire-status').textContent).toContain('HOP 1/2');

    // seed 順次点灯（ppr_hit、ジッタ付きキュー）
    emitWiring(es, { seq: 3, kind: 'ppr_hit', source: 'm2', target: '', weight: 0.8, meta: { request_id: rid } });
    expect(ds.nodeStore.m2.color.background).toBe(G.FLASH_COLORS.ppr_hit);
    emitWiring(es, { seq: 4, kind: 'ppr_hit', source: 'm3', target: '', weight: 0.7, meta: { request_id: rid } });
    vi.advanceTimersByTime(1600); // キュー消化 + パルス復帰
    expect(Object.keys(F._state().pulses).length).toBe(0);

    // 未知 kind はエラー扱いしない
    expect(F.handleFireEvent({ kind: 'future_kind', source: 'm1', meta: { request_id: rid } })).toBe(false);
    expect(() => F.handleFireEvent({ kind: 'PROPAGATE', source: 'm3', target: 'm1', meta: { request_id: rid } })).not.toThrow();

    // PROPAGATE: tag/related エッジ沿いの連鎖点灯（グラフになければ仮設エッジ）
    emitWiring(es, { seq: 5, kind: 'propagate', source: 'm1', target: 'm2', weight: 0.4, meta: { request_id: rid } });
    const edge = ds.edgeStore['fe:m1|m2'];
    expect(edge).toBeTruthy();
    expect(edge.width).toBeGreaterThan(edge._fireBase.width); // グロー中

    // decision_pass: 緑で保持（weight=確率）
    emitWiring(es, { seq: 6, kind: 'decision_pass', source: 'm1', weight: 0.87, meta: { request_id: rid } });
    expect(ds.nodeStore.m1.color.background).toBe('#30d158');

    // decision_reject: dim + 枝フェード
    const sizeBefore = ds.nodeStore.m2.size;
    emitWiring(es, { seq: 7, kind: 'decision_reject', source: 'm2', meta: { request_id: rid } });
    expect(ds.nodeStore.m2.color.background).toBe('#48484a');
    expect(ds.nodeStore.m2.size).toBeLessThan(sizeBefore);

    // hop_stop: sufficiency → 収束の華 + 結果パネル
    emitWiring(es, { seq: 8, kind: 'hop_stop', source: '', target: '', weight: 0, meta: { request_id: rid, reason: 'sufficiency' } });
    expect(document.getElementById('graph-fire-status').textContent).toContain('sufficiency');
    vi.advanceTimersByTime(3000); // フェード・華・パルスをすべて着地させる
    expect(ds.edgeStore['fe:m1|m2']).toBeUndefined(); // reject 枝の刈り込み完了
    // pass ノードは華のパルス復帰後も緑を保持
    expect(ds.nodeStore.m1.color.background).toBe('#30d158');

    // 結果パネル: score 降順・バッジ
    const rows = document.querySelectorAll('#graph-fire-results-list li');
    expect(rows.length).toBe(3);
    expect(rows[0].textContent).toContain('m1');
    expect(rows[0].textContent).toContain('PASS 87%');
    expect(rows[0].textContent).toContain('memory one content');
    expect(rows[0].textContent).toContain('tag-a');
    expect(rows[1].textContent).toContain('REJECT');
    expect(rows[2].textContent).toContain('0.7000');
  });

  it('reuses tag/related edges from the whole-graph data as the cluster base', () => {
    const orig = G.getGraphData;
    G.getGraphData = () => ({ nodes: [], edges: [{ source: 'a1', target: 'a2', type: 'tag' }] });
    try {
      startRun();
      const rid = F._state().session.requestId;
      emitWiring(instances[0], { kind: 'propagate', source: 'a1', target: 'a2', weight: 0.3, meta: { request_id: rid } });
      const edge = F._state().dataSet.edgeStore['fe:a1|a2'];
      expect(edge).toBeTruthy();
      expect(edge.dashes).toBe(false); // tag エッジは実線
      expect(edge._fireBase.width).toBe(2);
      expect(edge._fireBase.color).toContain('167,139,250'); // 紫系
    } finally {
      G.getGraphData = orig;
    }
  });
});

describe('fail-open contract (decision_bypass)', () => {
  it('notes the reason in the status line, lights nothing, and lets hop_stop keep the terminal line', async () => {
    const ds = fakeDs();
    F.setFireDataSet(ds);
    startRun();
    const rid = F._state().session.requestId;
    const es = instances[0];
    const status = () => document.getElementById('graph-fire-status').textContent;
    const mk = (seq, kind, meta) => ({
      seq, kind, source: '', target: '', weight: 0,
      meta: Object.assign({ persona: 'p1', hop: 1, request_id: rid }, meta),
    });

    emitWiring(es, mk(1, 'hop_start', {}));
    emitWiring(es, mk(2, 'decision_bypass', { reason: 'judge_unavailable' }));
    // 黙らない（理由が読める）
    expect(status()).toContain('判定スキップ');
    // ノード演出はしない — 却下と同じ見え方にすると嘘になる
    expect(Object.keys(ds.nodeStore)).toEqual([]);

    // 終端表示は hop_stop が持ち、fail-open の事実は併記されて残る
    emitWiring(es, mk(3, 'hop_stop', { reason: 'max_hops' }));
    expect(status()).toContain('hop 上限');
    expect(status()).toContain('判定スキップ');

    // reason ごとに文言が変わる（1 文案の全 reason 流用は新たな誤報になる）
    startRun();
    const rid2 = F._state().session.requestId;
    const es2 = instances[instances.length - 1];
    emitWiring(es2, {
      seq: 1, kind: 'decision_bypass', source: '', target: '', weight: 0,
      meta: { persona: 'p1', hop: 1, request_id: rid2, reason: 'no_candidates' },
    });
    expect(status()).toContain('候補なし');
  });
});

describe('results panel', () => {
  it('prints raw values and attributes the sim token to the query encoder only', async () => {
    startRun();
    const rid = F._state().session.requestId;
    emitWiring(instances[0], {
      kind: 'decision_pass', source: 'm1', weight: 0.9,
      meta: { request_id: rid, hop: 1, jev: 0.74, cosine: 0.753, time_weight: 0.5, sim_model: 'ruri-v3-70m' },
    });
    // 結果パネルは hop_stop で描画される
    emitWiring(instances[0], {
      kind: 'hop_stop', source: '', target: '', weight: 0,
      meta: { request_id: rid, reason: 'sufficiency' },
    });
    const row = document.querySelectorAll('#graph-fire-results-list li')[0];
    expect(row.textContent).toContain('sim 0.753 (ruri-v3-70m)');
    expect(row.textContent).toContain('jev 0.74');
    // 表示の time は rank に実際に掛かった倍率（floor 適用後の実効値）
    expect(row.textContent).toContain('time x0.50');
    // 帰属はクエリ側 encoder 名に限定する（stored が旧 encoder なら真の作成モデルは混合）
    expect(row.querySelector('.nfire-vals').getAttribute('title')).toBe('クエリ埋め込み: ruri-v3-70m');
  });

  it('accumulates across hops into a top-20 panel built with textContent only (XSS-safe)', async () => {
    startRun({ results: [{ memory: { key: 'x1', content: '<img src=x onerror=alert(1)>', tags: ['t1'] }, score: 0.5 }] });
    await flushAsync();
    const rid = F._state().session.requestId;
    const es = instances[0];
    for (let i = 0; i < 25; i++) {
      emitWiring(es, { kind: 'ppr_hit', source: 'k' + i, weight: i / 30, meta: { request_id: rid } });
    }
    emitWiring(es, { kind: 'hop_stop', meta: { request_id: rid, reason: 'max_hops' } });
    expect(document.getElementById('graph-fire-status').textContent).toContain('max_hops');
    await vi.runAllTimersAsync(); // 点灯キュー消化 + 静かな締め
    const list = document.getElementById('graph-fire-results-list');
    const rows = list.querySelectorAll('li');
    expect(rows.length).toBe(20);
    expect(rows[0].textContent).toContain('k24'); // 最高スコアが先頭
    expect(list.querySelector('img')).toBeNull(); // innerHTML 経由の要素生成なし
    expect(list.textContent).toContain('<img src=x onerror=alert(1)>'); // リテラル表示
  });
});

describe('organic jitter', () => {
  it('varies pulse amplitude with randomness (no constant pulses)', () => {
    const ds = F._state().dataSet;
    ds.nodes.update({ id: 'j1', size: 10, color: { background: '#aaa', border: '#aaa' } });
    const rnd = vi.spyOn(Math, 'random').mockReturnValue(0);
    expect(F._pulseNode('j1', 'ppr_hit', {})).toBe(true);
    const low = ds.nodeStore.j1.size; // 10 × 1.4 × 0.9
    rnd.mockReturnValue(0.9999);
    F._pulseNode('j1', 'ppr_hit', {});
    const high = ds.nodeStore.j1.size; // 10 × 1.4 × 1.35
    expect(high).toBeGreaterThan(low);
    expect(low).toBeCloseTo(12.6, 5);
    rnd.mockRestore();
  });
});

describe('excerpt', () => {
  it('caps content at 120 chars with ellipsis', () => {
    expect(F._excerpt('あ'.repeat(120))).toHaveLength(120);
    expect(F._excerpt('あ'.repeat(200))).toHaveLength(120); // 119字 + …
    expect(F._excerpt('short')).toBe('short');
  });
});

describe('prefers-reduced-motion', () => {
  it('removes rejected branches instantly without fade animation', async () => {
    vi.stubGlobal('matchMedia', vi.fn((q) => ({ matches: String(q).indexOf('prefers-reduced-motion: reduce') !== -1 })));
    startRun();
    await flushAsync();
    const rid = F._state().session.requestId;
    const es = instances[0];
    emitWiring(es, { kind: 'ppr_hit', source: 'r1', weight: 0.5, meta: { request_id: rid } });
    emitWiring(es, { kind: 'ppr_hit', source: 'r2', weight: 0.4, meta: { request_id: rid } });
    emitWiring(es, { kind: 'propagate', source: 'r1', target: 'r2', weight: 0.2, meta: { request_id: rid } });
    const ds = F._state().dataSet;
    expect(ds.edgeStore['fe:r1|r2']).toBeTruthy();
    emitWiring(es, { kind: 'decision_reject', source: 'r2', meta: { request_id: rid } });
    expect(ds.edgeStore['fe:r1|r2']).toBeUndefined(); // 即時削除（フェードなし）
  });
});

describe('mode toggle', () => {
  it('switches between the whole-graph view and firing mode, disconnecting SSE on exit', () => {
    const content = document.getElementById('graph-content');
    F.setMode(true);
    expect(content.style.display).toBe('none');
    expect(document.getElementById('graph-fire-root').style.display).toBe('');
    expect(document.getElementById('graph-fire-toggle').checked).toBe(true);
    F.connectFireStream();
    expect(instances.length).toBe(1);
    F.setMode(false);
    expect(content.style.display).toBe('');
    expect(document.getElementById('graph-fire-root').style.display).toBe('none');
    expect(instances[0].close).toHaveBeenCalled();
  });

  it('ignores fire events while the mode is off', () => {
    expect(F.handleFireEvent({ kind: 'ppr_hit', source: 'm1', meta: { request_id: 'x' } })).toBe(false);
  });
});

describe('entity layer in firing scene (#011 Phase 15)', () => {
  it('ingests entity nodes + mentions edges from /api/search and paints by type/typed_by', async () => {
    startRun({
      results: [{ memory: { key: 'm1', content: 'memory one', tags: [] }, score: 0.9 }],
      nodes: [
        { key: 'ent:ヘルタ', kind: 'entity', label: 'ヘルタ', entity_type: 'person', typed_by: 'llm', mention_count: 3 },
        { key: 'ent:x', kind: 'entity', label: 'x', entity_type: 'person', typed_by: null, mention_count: 1 },
        { key: 'ent:y', kind: 'entity', label: 'y', entity_type: 'thing', typed_by: 'llm', mention_count: 1 },
      ],
      edges: [{ source: 'm1', target: 'ent:ヘルタ', type: 'mentions' }],
    });
    await flushAsync();
    const ds = F._state().dataSet;
    // person + llm → 緑 / thing + llm → 黄 / typed_by 未付与 → 灰（嘘の緑を出さない）
    expect(ds.nodeStore['ent:ヘルタ'].color.background).toBe('#30d158');
    expect(ds.nodeStore['ent:y'].color.background).toBe('#ffd60a');
    expect(ds.nodeStore['ent:x'].color.background).toBe('#94a3b8');
    // mentions エッジが実ノード間を結ぶ
    expect(ds.edgeStore['fe:ent:ヘルタ|m1']).toBeTruthy();
    // entity は結果パネル（記憶のみ）に出ない
    expect(F._state().session.results.has('ent:ヘルタ')).toBe(false);
  });

  it('absorbs mentions edges from the whole-graph data as a cluster base', () => {
    const orig = G.getGraphData;
    G.getGraphData = () => ({ nodes: [], edges: [{ source: 'a1', target: 'a2', type: 'mentions' }] });
    try {
      startRun();
      const rid = F._state().session.requestId;
      emitWiring(instances[0], { kind: 'ppr_hit', source: 'a1', weight: 0.5, meta: { request_id: rid } });
      emitWiring(instances[0], { kind: 'ppr_hit', source: 'a2', weight: 0.4, meta: { request_id: rid } });
      expect(F._state().dataSet.edgeStore['fe:a1|a2']).toBeTruthy();
    } finally {
      G.getGraphData = orig;
    }
  });
});
