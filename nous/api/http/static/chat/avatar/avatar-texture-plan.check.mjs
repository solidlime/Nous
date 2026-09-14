/* =================================================================
   avatar-texture-plan.check.mjs — resolveBaseColorPlan / lookupPlan の自己チェック。

   既存の *.test.js は vitest 前提だが、このリポジトリには vitest の設定が無く
   スイート全体が赤（beforeAll is not defined / jsdom 不在）なので、
   ここはフレームワーク無しで node から直接走らせる。

   実行: node nous/api/http/static/chat/avatar/avatar-texture-plan.check.mjs
   ================================================================= */

import assert from "node:assert/strict";
import {
  lookupPlan,
  resolveBaseColorPlan,
  isIdentityTransform,
} from "./avatar-texture-plan.js";

let pass = 0;
const failures = [];
function check(name, fn) {
  try {
    fn();
    pass++;
  } catch (e) {
    failures.push(`${name}: ${e.message}`);
  }
}

/** 最小の glTF JSON。材質ひとつ＝"9.koromo1"（bufferView 画像）。 */
function base(overrides = {}) {
  return {
    materials: [
      {
        name: "9.koromo1",
        pbrMetallicRoughness: {
          baseColorTexture: { index: 0, ...overrides.info },
        },
      },
    ],
    textures: overrides.textures ?? [{ source: 0, sampler: 0 }],
    images: overrides.images ?? [{ bufferView: 7, mimeType: "image/png" }],
    samplers: overrides.samplers ?? [{ wrapS: 10497, wrapT: 33071 }],
  };
}

// --- 正常系 ---
check("bufferView 画像を解決し、画像添字と sampler を返す", () => {
  const { plan, issues } = resolveBaseColorPlan(base());
  assert.equal(issues.length, 0);
  assert.equal(plan.size, 1);
  assert.equal(plan.get("9.koromo1").imageIndex, 0);
  assert.equal(plan.get("9.koromo1").texCoord, 0);
  assert.deepEqual(plan.get("9.koromo1").sampler, {
    wrapS: 10497,
    wrapT: 33071,
  });
});

check("アウトライン材質は本編の設定を流用する", () => {
  const { plan } = resolveBaseColorPlan(base());
  assert.equal(lookupPlan(plan, "9.koromo1 (Outline)").imageIndex, 0);
  assert.equal(lookupPlan(plan, "9.koromo1").imageIndex, 0);
});

check("texCoord を保持する（UV1 利用のモデルで UV0 を張らない）", () => {
  const { plan } = resolveBaseColorPlan(base({ info: { texCoord: 1 } }));
  assert.equal(plan.get("9.koromo1").texCoord, 1);
});

check("uri 形式（外部/データ URI）の画像も取得対象にする", () => {
  const { plan, issues } = resolveBaseColorPlan(
    base({ images: [{ uri: "textures/body.png" }] }),
  );
  assert.equal(issues.length, 0);
  assert.equal(plan.get("9.koromo1").imageIndex, 0);
});

check("sampler 未指定でも落ちない", () => {
  const { plan } = resolveBaseColorPlan(base({ textures: [{ source: 0 }] }));
  assert.equal(plan.get("9.koromo1").sampler, null);
});

check("ベースカラー画像を持たない材質は黙って対象外", () => {
  const json = base();
  json.materials.push({ name: "10.teye", pbrMetallicRoughness: {} });
  const { plan, issues } = resolveBaseColorPlan(json);
  assert.equal(plan.has("10.teye"), false);
  assert.equal(issues.length, 0);
});

// --- 異常系（無言の白飛びを防ぐ＝必ず issues に残す） ---
check("画像実体が無い場合は issues に残し plan に入れない", () => {
  const { plan, issues } = resolveBaseColorPlan(base({ images: [{}] }));
  assert.equal(plan.size, 0);
  assert.equal(issues.length, 1);
  assert.match(issues[0], /bufferView も uri も無い/);
});

check("textures[].source 未設定は issues に残す", () => {
  const { plan, issues } = resolveBaseColorPlan(base({ textures: [{}] }));
  assert.equal(plan.size, 0);
  assert.match(issues[0], /source が未設定/);
});

check("恒等でない KHR_texture_transform は issues に残す（描画は継続）", () => {
  const { plan, issues } = resolveBaseColorPlan(
    base({ info: { extensions: { KHR_texture_transform: { scale: [2, 2] } } } }),
  );
  assert.equal(plan.get("9.koromo1").imageIndex, 0, "画像自体は張れる");
  assert.equal(issues.length, 1);
  assert.match(issues[0], /恒等でない/);
});

check("恒等な KHR_texture_transform は issues を出さない", () => {
  const { issues } = resolveBaseColorPlan(
    base({
      info: {
        extensions: {
          KHR_texture_transform: { offset: [0, 0], scale: [1, 1] },
        },
      },
    }),
  );
  assert.equal(issues.length, 0);
});

check("材質名が無い場合は issues に残す", () => {
  const json = base();
  delete json.materials[0].name;
  const { plan, issues } = resolveBaseColorPlan(json);
  assert.equal(plan.size, 0);
  assert.match(issues[0], /材質名が無い/);
});

check("壊れた JSON（配列なし・null）でも例外を投げない", () => {
  for (const junk of [null, undefined, {}, { materials: null }, { materials: [{}] }]) {
    const { plan, issues } = resolveBaseColorPlan(junk);
    assert.equal(plan.size, 0);
    assert.ok(Array.isArray(issues));
  }
});

check("未登録の材質名は null を返す（誤った画像を張らない）", () => {
  const { plan } = resolveBaseColorPlan(base());
  assert.equal(lookupPlan(plan, "存在しない材質"), null);
  assert.equal(lookupPlan(plan, ""), null);
});

check("isIdentityTransform の境界", () => {
  assert.equal(isIdentityTransform(null), true);
  assert.equal(isIdentityTransform({ offset: [0, 0] }), true);
  assert.equal(isIdentityTransform({ offset: [0.1, 0] }), false);
  assert.equal(isIdentityTransform({ rotation: 0.5 }), false);
  assert.equal(isIdentityTransform({ scale: [1, 0.5] }), false);
});

if (failures.length) {
  console.error(`✗ ${failures.length} 件失敗 / ${pass + failures.length} 件`);
  for (const f of failures) console.error(`  - ${f}`);
  process.exit(1);
}
console.log(`✓ avatar-texture-plan: ${pass} 件すべて通過`);
