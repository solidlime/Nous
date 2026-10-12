/* =================================================================
   graph semantic-color tests — 「記憶の構成要素」4色マッピング
   緑=誰が(person) / 黄=なにを(thing) / 紫=どうする(動作 relation) /
   ピンク枠=きもち(emotion)。新規フィールドは足さず、API が既に返す
   entity_type / relation / emotion から表示時に導出する。
   発火フラッシュ（FLASH_COLORS）は一時上書きで、500ms 後に意味色へ
   復帰しなければならない（最大の実装リスク）。
   ================================================================= */
import { readFileSync } from 'fs';
import { resolve, dirname } from 'path';
import { fileURLToPath } from 'url';
import { loadCore, loadFile } from '../core/load-core.js';

const __dirname = dirname(fileURLToPath(import.meta.url));

let G;

beforeAll(() => {
  loadCore();
  loadFile('sse.js');
  window.S = { persona: 'p1', tab: 'graph' };
  globalThis.N = window.Nous;
  const code = readFileSync(resolve(__dirname, 'graph.js'), 'utf-8');
  new Function(code)();
  G = window.Nous.Features.Graph;
});

describe('entity fill (緑=person|agent / 黄=thing / 灰=その他)', () => {
  const build = (entity_type, typed_by) => G.buildVisData(
    [{ key: 'ent:1', kind: 'entity', label: 'E', entity_type, typed_by, mention_count: 3 }],
    [],
  ).visNodes[0];

  it('typed_by があり person なら緑', () => {
    expect(build('person', 'llm').color.background).toBe('#30d158');
  });

  it('agent も緑（写像表の受け口）', () => {
    expect(build('agent', 'llm').color.background).toBe('#30d158');
  });

  it('typed_by があり thing なら黄', () => {
    expect(build('thing', 'llm').color.background).toBe('#ffd60a');
  });

  it('typed_by があり place / concept / 不明 なら既定グレー', () => {
    expect(build('place', 'sudachi').color.background).toBe('#94a3b8');
    expect(build('concept', 'regex').color.background).toBe('#94a3b8');
    expect(build(undefined, 'llm').color.background).toBe('#94a3b8');
  });

  it('typed_by が無い / 未知なら person でも無色（嘘の緑を出さない）', () => {
    expect(build('person').color.background).toBe('#94a3b8');
    expect(build('person', 'unknown').color.background).toBe('#94a3b8');
    expect(build('person', '').color.background).toBe('#94a3b8');
  });

  it('サイズ表現（mention_count）は維持される', () => {
    expect(build('person', 'llm').size).toBe(8 + 3 * 2);
  });
});

describe('relation edge color (紫=created / manages)', () => {
  const colorOf = (relation) => G.buildVisData([], [
    { source: 'ent:1', target: 'ent:2', type: 'relation', relation },
  ]).visEdges[0].color;

  it('動作系 created / manages は紫', () => {
    expect(colorOf('created').color).toBe('rgba(167,139,250,0.85)');
    expect(colorOf('manages').color).toBe('rgba(167,139,250,0.85)');
  });

  it('状態系 knows / located_in は既定色（紫ではない）', () => {
    expect(colorOf('knows').color).toBe('rgba(148,163,184,0.65)');
    expect(colorOf('located_in').color).toBe('rgba(148,163,184,0.65)');
  });

  it('relation 以外の種別は従来どおり', () => {
    const related = G.buildVisData([], [{ source: 'a', target: 'b', type: 'related' }]).visEdges[0];
    expect(related.color.color).toBe('rgba(0,122,255,0.85)');
  });
});

describe('memory border (ピンク枠=emotion)', () => {
  const build = (emotion) => G.buildVisData(
    [{ key: 'm1', kind: 'memory', content: 'hello world', emotion, importance: 0.5 }],
    [],
  ).visNodes[0];

  it('neutral 以外の emotion は枠がピンク・塗りは neutral', () => {
    const n = build('joy');
    expect(n.color.border).toBe('#ff375f');
    // #011 Phase 15: 塗りは感情色を降りて neutral（entity 黄 #ffd60a との衝突回避）。
    expect(n.color.background).toBe('#64748b');
  });

  it('neutral / emotion 無しは枠は塗りと同色', () => {
    expect(build('neutral').color.border).toBe('#64748b');
    expect(build(undefined).color.border).toBe('#64748b');
  });

  it('枠ピンクでも重要度→サイズは不変', () => {
    expect(build('joy').size).toBe(10 + 0.5 * 30);
  });
});

describe('発火フラッシュは意味色へ復帰する', () => {
  it('entity 緑は発火後に緑へ戻る', () => {
    vi.useFakeTimers();
    const built = G.buildVisData(
      [{ key: 'ent:1', kind: 'entity', label: 'E', entity_type: 'person', typed_by: 'llm', mention_count: 1 }], [],
    ).visNodes[0];
    const store = { 'ent:1': built };
    const nodes = {
      get: (id) => store[id] || null,
      update: (patch) => { Object.assign(store[patch.id], patch); },
    };
    G.setGraphFlashDataSet({ nodes });
    expect(G.handleWiringEvent({ kind: 'link_fire', source: 'ent:1', target: '' })).toBe(true);
    expect(store['ent:1'].color.background).toBe(G.FLASH_COLORS.link_fire);
    vi.advanceTimersByTime(500);
    expect(store['ent:1'].color.background).toBe('#30d158');
    expect(store['ent:1'].color.border).toBe('#30d158');
    G.setGraphFlashDataSet(null);
    vi.useRealTimers();
  });

  it('memory のピンク枠は発火後にピンクへ戻る', () => {
    vi.useFakeTimers();
    const built = G.buildVisData(
      [{ key: 'm1', kind: 'memory', content: 'x', emotion: 'joy', importance: 0.5 }], [],
    ).visNodes[0];
    const store = { m1: built };
    const nodes = {
      get: (id) => store[id] || null,
      update: (patch) => { Object.assign(store[patch.id], patch); },
    };
    G.setGraphFlashDataSet({ nodes });
    G.flashNodeOn(nodes, 'm1', 'recall_boost');
    vi.advanceTimersByTime(500);
    expect(store.m1.color.border).toBe('#ff375f');
    expect(store.m1.color.background).toBe('#64748b');
    G.setGraphFlashDataSet(null);
    vi.useRealTimers();
  });
});
