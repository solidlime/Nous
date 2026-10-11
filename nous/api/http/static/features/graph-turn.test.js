/* =================================================================
   graph-turn tests — Phase 12: チャット由来の記憶発火を Graph タブへ
   turn_id グルーピング表示 / prompt_inject の「話に使った」バッジ /
   連鎖の turn 境界。request_id 単一フィルタ（手動 FIRE）との後方互換も
   ここで固定する。
   ================================================================= */
import { readFileSync } from 'fs';
import { resolve, dirname } from 'path';
import { fileURLToPath } from 'url';
import { loadCore, loadFile } from '../core/load-core.js';

const __dirname = dirname(fileURLToPath(import.meta.url));

const instances = [];
let G, F;

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

function emit(es, ev) {
  es.emit('wiring', JSON.stringify(ev));
}

beforeAll(() => {
  document.body.innerHTML =
    '<section id="tab-graph"><div id="graph-content"></div></section>';
  loadCore();
  loadFile('sse.js');
  window.S = { persona: 'p1', tab: 'graph' };
  globalThis.N = window.Nous;
  new Function(readFileSync(resolve(__dirname, 'graph.js'), 'utf-8'))();
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
    emit(ev, data) { (this._listeners[ev] || []).forEach((fn) => fn({ data })); }
  });
  F.setTurnMode(false);
  F.setMode(false);
  F.setFireDataSet(fakeDs());
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

function openTurnMode() {
  F.setMode(true);
  F.setTurnMode(true);
  return instances[instances.length - 1];
}

describe('prompt_inject kind registration', () => {
  it('registers a color distinct from the existing kind colors', () => {
    expect(typeof G.FLASH_COLORS.prompt_inject).toBe('string');
    // 既存 9 色を壊していない
    expect(G.FLASH_COLORS.ppr_hit).toBe('#007aff');
    expect(G.FLASH_COLORS.decision_pass).toBe('#30d158');
    expect(G.FLASH_COLORS.link_fire).toBe('#bf5af2');
  });
});

describe('turn_id grouping mode', () => {
  it('bundles events across multiple request_ids under one turn_id', () => {
    const es = openTurnMode();
    emit(es, { seq: 1, kind: 'hop_start', source: '', weight: 0, meta: { persona: 'p1', hop: 1, turn_id: 'T1', request_id: 'r1' } });
    emit(es, { seq: 2, kind: 'ppr_hit', source: 'm1', weight: 0.8, meta: { persona: 'p1', hop: 1, turn_id: 'T1', request_id: 'r1' } });
    // 同じ発話の 2 本目の検索クエリは別 request_id —— turn モードでは両方消費する
    emit(es, { seq: 3, kind: 'ppr_hit', source: 'm2', weight: 0.7, meta: { persona: 'p1', hop: 1, turn_id: 'T1', request_id: 'r2' } });
    const ds = F._state().dataSet;
    expect(F._state().session.turnId).toBe('T1');
    expect(ds.nodeStore.m1).toBeTruthy();
    expect(ds.nodeStore.m2).toBeTruthy();
  });

  it('starts a fresh chain when the turn_id changes (連結の境界)', () => {
    const es = openTurnMode();
    emit(es, { seq: 1, kind: 'ppr_hit', source: 'm1', weight: 0.8, meta: { turn_id: 'T1', request_id: 'r1' } });
    emit(es, { seq: 2, kind: 'ppr_hit', source: 'm2', weight: 0.7, meta: { turn_id: 'T2', request_id: 'r9' } });
    const ds = F._state().dataSet;
    expect(F._state().session.turnId).toBe('T2');
    expect(ds.nodeStore.m1).toBeUndefined(); // 前の発話の連鎖は消える
    expect(ds.nodeStore.m2).toBeTruthy();
  });

  it('ignores request_id-only manual FIRE events while in turn mode', () => {
    openTurnMode();
    expect(F.handleFireEvent({ seq: 1, kind: 'ppr_hit', source: 'zz', meta: { request_id: 'manual-run' } })).toBe(false);
  });

  it('keeps the request_id single-run filter when turn mode is off (backward compat)', () => {
    F.setMode(true);
    F.setTurnMode(false);
    // 手動 FIRE のセッションが無いので request_id イベントは消費しない
    expect(F.handleFireEvent({ seq: 1, kind: 'ppr_hit', source: 'zz', meta: { request_id: 'manual-run' } })).toBe(false);
    // turn_id イベントも turn モード OFF では消費しない（prompt_inject 含む）
    expect(F.handleFireEvent({ kind: 'prompt_inject', source: 'x', meta: { turn_id: 'T1' } })).toBe(false);
    expect(F._state().session).toBeNull();
  });
});

describe('prompt_inject badge (話に使った)', () => {
  it('marks the injected memory node and shows the badge in the results panel', () => {
    const es = openTurnMode();
    emit(es, { seq: 1, kind: 'ppr_hit', source: 'm1', weight: 0.8, meta: { turn_id: 'T1', request_id: 'r1' } });
    emit(es, { seq: 2, kind: 'prompt_inject', source: 'm1', weight: 0, meta: { persona: 'p1', turn_id: 'T1' } });
    const node = F._state().dataSet.nodeStore.m1;
    expect(node._used).toBe(true);
    expect(node.color.border).toBe(G.FLASH_COLORS.prompt_inject);
    // 結果パネルにも「話に使った」バッジ（挿入の確定であって使用の証明ではない）
    F.renderResults();
    const row = document.querySelector('#graph-fire-results-list li');
    expect(row.textContent).toContain('話に使った');
  });

  it('ignores prompt_inject without a turn_id', () => {
    openTurnMode();
    expect(F.handleFireEvent({ kind: 'prompt_inject', source: 'x', meta: {} })).toBe(false);
  });
});
