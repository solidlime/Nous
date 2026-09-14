/* =================================================================
   avatar-texture-plan.js — 「どの材質にどのベースカラー画像を、どの UV で張るか」を
   glTF/VRM の JSON だけから決める純ロジック。

   ここにはブラウザ API も three.js も持ち込まない（node で直接テストするため）。
   実測（herta.vrm を実ブラウザで読み込んだ結果）では、読み込み後の材質が
   isMToonMaterial=true / color=#ffffff / map=null となり面が白飛びする一方、
   JSON 側の baseColorTexture → textures[i].source → images[i] は正しく繋がっていた。
   欠けていたのは画像実体の取得だけなので、その「取得すべき対象」の決定をここに集約する。

   検証: node nous/api/http/static/chat/avatar/avatar-texture-plan.check.mjs
   ================================================================= */

/** アウトライン材質の命名規約（three-vrm）: "<材質名> (Outline)" */
export const OUTLINE_SUFFIX = / \(Outline\)$/;

/**
 * 恒等でない KHR_texture_transform か。
 * 恒等なら UV をそのまま使ってよい（herta.vrm は全材質が恒等であることを実測済み）。
 * @param {{offset?: number[], scale?: number[], rotation?: number}} t
 */
export function isIdentityTransform(t) {
  if (!t) return true;
  const [ox = 0, oy = 0] = t.offset ?? [];
  const [sx = 1, sy = 1] = t.scale ?? [];
  const rot = t.rotation ?? 0;
  return ox === 0 && oy === 0 && sx === 1 && sy === 1 && rot === 0;
}

/**
 * 材質名 → ベースカラー画像の解決表を作る。
 *
 * @param {object} json GLTFLoader の parser.json（または同等の glTF 構造）
 * @returns {{plan: Map<string, {imageIndex: number, texCoord: number, transform: object|null, sampler: object|null}>, issues: string[]}}
 *   plan: 画像を取得できる材質のみ。キーは glTF 上の材質名。
 *   issues: 「取得できない/怪しい」理由。無言の白飛びを防ぐため必ずログに出す。
 */
export function resolveBaseColorPlan(json) {
  const plan = new Map();
  const issues = [];
  const materials = json?.materials ?? [];
  const textures = json?.textures ?? [];
  const images = json?.images ?? [];
  const samplers = json?.samplers ?? [];

  for (const gm of materials) {
    const info = gm?.pbrMetallicRoughness?.baseColorTexture;
    if (info?.index == null) continue; // ベースカラー画像を持たない材質は対象外
    const name = gm.name;
    if (!name) {
      issues.push(`材質名が無いため画像を紐付けられない (texture index ${info.index})`);
      continue;
    }
    const texIdx = info.index;
    const imageIndex = textures[texIdx]?.source;
    if (imageIndex == null) {
      issues.push(`${name}: textures[${texIdx}].source が未設定`);
      continue;
    }
    const img = images[imageIndex];
    // 画像実体は bufferView（GLB 埋め込み）か uri（data: / 相対 URL）のどちらか
    const hasSource = img?.bufferView != null || typeof img?.uri === "string";
    if (!hasSource) {
      issues.push(`${name}: images[${imageIndex}] に bufferView も uri も無い`);
      continue;
    }
    const transform = info.extensions?.KHR_texture_transform ?? null;
    if (!isIdentityTransform(transform)) {
      issues.push(`${name}: KHR_texture_transform が恒等でない（UV がずれる）`);
    }
    const samplerIdx = textures[texIdx]?.sampler;
    plan.set(name, {
      imageIndex,
      texCoord: info.texCoord ?? 0,
      transform,
      sampler: samplerIdx == null ? null : (samplers[samplerIdx] ?? null),
    });
  }
  return { plan, issues };
}

/**
 * 材質名から解決表を引く。アウトライン材質 "<名前> (Outline)" は本編の設定を流用する。
 * @param {Map<string, object>} plan
 * @param {string} materialName
 */
export function lookupPlan(plan, materialName) {
  const name = String(materialName || "");
  return plan.get(name) ?? plan.get(name.replace(OUTLINE_SUFFIX, "")) ?? null;
}
