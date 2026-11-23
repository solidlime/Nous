// kanban #12 / #56 セルフチェック: nous-events.ts の純関数 (resolveProject / formatRecall / parseWikiPayload / buildRecallQuery) を検証。
// 実行: node D:/Code/Nous/pi/extensions/_selfcheck.mjs
// jiti と pi-coding-agent の解決には pi 本体 node_modules の alias を渡す。
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { pathToFileURL } from "node:url";

// pi 本体の解決: env → 既知パス候補（Linux/mac の npm-global, Windows の Roaming）。
const PI_ROOT_CANDIDATES = [
  process.env.PI_CODING_AGENT_ROOT,
  "/root/.npm-global/lib/node_modules/@agegr/pi-web/node_modules/@earendil-works/pi-coding-agent",
  "C:/Users/Owner/AppData/Roaming/npm/node_modules/@earendil-works/pi-coding-agent",
];
const piRoot = PI_ROOT_CANDIDATES.find((dir) => typeof dir === "string" && dir && fs.existsSync(dir));
if (!piRoot) {
  throw new Error(`pi-coding-agent が見つからない（PI_CODING_AGENT_ROOT を設定するか既知パスに配置）: ${PI_ROOT_CANDIDATES.filter(Boolean).join(", ")}`);
}
// jiti は pi 本体の node_modules 配下か、その兄弟（@agegr/pi-web/node_modules）に居る。
const jitiLib = [
  `${piRoot}/node_modules/jiti/lib/jiti.mjs`,
  path.resolve(piRoot, "../jiti/lib/jiti.mjs"),
  path.resolve(piRoot, "../../jiti/lib/jiti.mjs"),
].find((file) => fs.existsSync(file));
if (!jitiLib) throw new Error(`jiti が見つからない（piRoot=${piRoot}）`);
const nousEventsTs = path.resolve(import.meta.dirname, "nous-events.ts");

const jitiMod = await import(pathToFileURL(jitiLib).href);
const createJiti = jitiMod.createJiti ?? jitiMod.default?.createJiti;
if (!createJiti) throw new Error("createJiti not found");

const jiti = createJiti(pathToFileURL(nousEventsTs).href, {
  alias: {
    "@earendil-works/pi-coding-agent": pathToFileURL(`${piRoot}/dist/index.js`).href,
  },
});
const mod = await jiti.import(pathToFileURL(nousEventsTs).href);
const {
  resolveProject,
  formatRecall,
  parseWikiPayload,
  parseStatePayload,
  formatState,
  formatIdentity,
  buildRecallQuery,
  normalizeProjectSlug,
} = mod;

const tmpBase = fs.mkdtempSync(path.join(os.tmpdir(), "nousproj-"));
const cases = [
  { proj: "nous", expect: "nous" },
  { proj: "editorial-journal", expect: "editorial-journal" },
  { proj: "nous/evil", expect: "" },
  { proj: "bad slug!", expect: "" },
  // 緩い検証（[A-Za-z0-9._-]{1,24}）なら通ってしまうケース＝canonical の証拠
  { proj: "Nous", expect: "nous" },
  { proj: "nous.core", expect: "" },
  { proj: "my_project", expect: "my-project" },
];
let fail = 0;
for (const c of cases) {
  fs.writeFileSync(path.join(tmpBase, "AGENTS.md"), "# guide\n\n## プロジェクト識別\n- project: " + c.proj + "\n");
  const got = resolveProject(tmpBase);
  if (got !== c.expect) { console.error(`FAIL proj=${JSON.stringify(c.proj)} got=${JSON.stringify(got)}`); fail++; }
}
fs.writeFileSync(path.join(tmpBase, "AGENTS.md"), "no project line here\n");
if (resolveProject(tmpBase) !== "") { console.error("FAIL no-line"); fail++; }
if (resolveProject(path.join(tmpBase, "NOPE")) !== "") { console.error("FAIL missing"); fail++; }
const msg = formatRecall([{ content: "x", kind: "semantic", score: 1.5, created: "2026-11-07" }]);
if (!msg.includes("[nous recall]") || msg.includes("undefined")) { console.error("FAIL formatRecall"); fail++; }

// #56: wiki 節の二段フォーマット（wiki 優先）
const payload = {
  results: [{ memory: { content: "記憶その1", kind: "semantic", created_at: "2026-11-01T00:00:00Z" }, score: 1.4 }],
  wiki: [
    { slug: "project-nous-wiki", title: "Wiki 編纂", excerpt: "pages をどう書くか", score: 1.0, project: "nous" },
    { slug: "broken" },
  ],
};
const wikiHits = parseWikiPayload(payload, 2);
if (wikiHits.length !== 2) { console.error(`FAIL parseWikiPayload length=${wikiHits.length}`); fail++; }
if (wikiHits[0]?.slug !== "project-nous-wiki" || wikiHits[0]?.title !== "Wiki 編纂") { console.error("FAIL parseWikiPayload first"); fail++; }
if (wikiHits[1]?.title !== "broken") { console.error("FAIL parseWikiPayload fallback title"); fail++; }
if (parseWikiPayload(payload, 1).length !== 1) { console.error("FAIL parseWikiPayload topK"); fail++; }
if (parseWikiPayload({}, 2).length !== 0 || parseWikiPayload({ wiki: "nope" }, 2).length !== 0) { console.error("FAIL parseWikiPayload junk"); fail++; }
const twoTier = formatRecall([{ content: "記憶その1", kind: "semantic", score: 1.4, created: "2026-11-01" }], wikiHits);
if (!twoTier.includes("📚 Wiki:") || !twoTier.includes("💭 記憶:") || !twoTier.includes("project-nous-wiki")) { console.error("FAIL two-tier"); fail++; }
const wikiOnly = formatRecall([], wikiHits);
if (!wikiOnly.includes("📚 Wiki:") || wikiOnly.includes("💭 記憶:")) { console.error("FAIL wiki-only"); fail++; }
const memOnly = formatRecall([{ content: "x", kind: "semantic", score: 1.0, created: "2026-11-01" }], []);
if (memOnly.includes("📚 Wiki:")) { console.error("FAIL memories-only"); fail++; }

// #56: 短発話の projectSlug 補完
const shortCases = [
  { prompt: "進めて", proj: "nous", expect: "進めて nous" },
  { prompt: "進めて", proj: "", expect: "進めて" },
  { prompt: "この モジュールの 検索精度を 上げたい のだが", proj: "nous", expect: "この モジュールの 検索精度を 上げたい のだが" },
  { prompt: "   ", proj: "nous", expect: "" },
];
for (const c of shortCases) {
  const got = buildRecallQuery(c.prompt, c.proj);
  if (got !== c.expect) { console.error(`FAIL buildRecallQuery ${JSON.stringify(c.prompt)}/${c.proj} got=${JSON.stringify(got)}`); fail++; }
}
// resolveConfig の recall 既定と project slug 正規形の内接確認
const cfg = mod.resolveConfig ? mod.resolveConfig() : null;
if (cfg && typeof cfg.recall?.enabled !== "boolean") { console.error("FAIL config shape"); fail++; }
fs.rmSync(tmpBase, { recursive: true, force: true });

// 正規化はサーバの normalize_project_slug と同一規則（差があるとブーストが無言で消える）
for (const [raw, expect] of [["Nous", "nous"], ["my_project", "my-project"], ["nous.core", ""], ["  ", ""], ["NOUS--X", "nous--x"]]) {
  const got = normalizeProjectSlug(raw);
  if (got !== expect) { console.error(`FAIL normalizeProjectSlug ${JSON.stringify(raw)} got=${JSON.stringify(got)}`); fail++; }
}
// 状態注入: parseStatePayload / formatState / formatRecall(state) / formatIdentity
const statePayload = {
  state: {
    emotion: "joy",
    emotion_intensity: 0.8,
    physical_state: "疲れている",
    mental_state: "リラックスしている",
    environment: "自宅",
    relationship_status: "「知人」以上「友人」未満。",
    body: { fatigue: 0.086, warmth: 0.5, arousal: null, pain: "x" },
    user: { name: "らうらう", nickname: "らうらう", preferred_address: "らうらう" },
  },
};
const st = parseStatePayload(statePayload);
if (!st) { console.error("FAIL parseStatePayload null"); fail++; }
if (st && (st.emotion !== "joy" || st.intensity !== 0.8 || st.environment !== "自宅")) { console.error("FAIL parseStatePayload fields"); fail++; }
if (st && (Object.keys(st.body).join(",") !== "fatigue,warmth")) { console.error(`FAIL parseStatePayload body=${Object.keys(st?.body).join(",")}`); fail++; }
for (const broken of [null, {}, "", "state", { state: null }, { state: "nope" }, { state: [] }]) {
  if (parseStatePayload(broken) !== null) { console.error(`FAIL parseStatePayload broken ${JSON.stringify(broken)}`); fail++; }
}
const emptyState = { emotion: "", intensity: null, physical: "", mental: "", environment: "", relationship: "", body: {}, user: {} };
if (parseStatePayload({ state: emptyState }) !== null) { console.error("FAIL parseStatePayload all-empty"); fail++; }
if (formatState(null) !== "" || formatState(emptyState) !== "") { console.error("FAIL formatState empty"); fail++; }
const stText = formatState(st);
if (!stText.startsWith("--- 現在の状態 ---\n")) { console.error("FAIL formatState header"); fail++; }
if (!stText.includes("感情: joy（0.8） / 体の様子: 疲れている / 心の様子: リラックスしている")) { console.error(`FAIL formatState head: ${stText}`); fail++; }
if (!stText.includes("場所: 自宅 / 身体: 疲労 0.09 体温 0.5")) { console.error(`FAIL formatState tail: ${stText}`); fail++; }
const noIntensity = formatState({ ...emptyState, emotion: "calm" });
if (noIntensity !== "--- 現在の状態 ---\n感情: calm") { console.error(`FAIL formatState intensity: ${noIntensity}`); fail++; }
const stateRecall = formatRecall([{ content: "x", kind: "semantic", score: 1.0, created: "2026-11-01" }], [], st);
if (!stateRecall.includes("--- 現在の状態 ---") || stateRecall.indexOf("--- 現在の状態 ---") > stateRecall.indexOf("\n---\n")) {
  console.error("FAIL formatRecall state placement"); fail++;
}
const stateOnly = formatRecall([], [], st);
if (!stateOnly.startsWith("[nous recall]") || !stateOnly.includes("--- 現在の状態 ---")) { console.error("FAIL formatRecall state-only"); fail++; }
if (formatRecall([{ content: "x", kind: "", score: 1.0, created: "" }]).includes("現在の状態")) {
  console.error("FAIL formatRecall no-state"); fail++;
}
const id = formatIdentity(st);
if (!id.includes("ユーザー: らうらう") || !id.includes("関係性: 「知人」以上「友人」未満。")) { console.error(`FAIL formatIdentity: ${id}`); fail++; }
if (formatIdentity(null) !== "" || formatIdentity(emptyState) !== "") { console.error("FAIL formatIdentity empty"); fail++; }
if (formatIdentity({ ...emptyState, user: { name: "Taro", preferred_address: "Taro-san" } }) !== "ユーザー: Taro（呼称も「Taro-san」）") {
  console.error("FAIL formatIdentity address"); fail++;
}
if (formatIdentity({ ...emptyState, user: { nickname: "らう" }, relationship: "友人" }) !== "ユーザー: らう\n関係性: 友人") {
  console.error("FAIL formatIdentity nickname-only"); fail++;
}
if (formatIdentity({ ...emptyState, relationship: "友人" }) !== "関係性: 友人") { console.error("FAIL formatIdentity relationship-only"); fail++; }

console.log(fail === 0 ? "SELF-CHECK OK" : `SELF-CHECK FAILED ${fail}`);
if (fail > 0) process.exitCode = 1;
