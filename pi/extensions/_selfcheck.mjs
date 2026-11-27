// kanban #12 / #56 セルフチェック: nous-events.ts の純関数 (resolveProject / parseRecallPayload / parseWikiPayload / parseInjection / buildRecallQuery) を検証。
// 注入本文はサーバ (/api/search/{persona}.injection) が整形する。拡張側の仕事は「そのまま通す」ことだけ。
// 実行: node pi/extensions/_selfcheck.mjs（サーバ不要・応答 JSON はローカルのフィクスチャ）
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
  parseRecallPayload,
  parseWikiPayload,
  parseInjection,
  buildRecallQuery,
  normalizeProjectSlug,
} = mod;

let fail = 0;

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
for (const c of cases) {
  fs.writeFileSync(path.join(tmpBase, "AGENTS.md"), "# guide\n\n## プロジェクト識別\n- project: " + c.proj + "\n");
  const got = resolveProject(tmpBase);
  if (got !== c.expect) { console.error(`FAIL proj=${JSON.stringify(c.proj)} got=${JSON.stringify(got)}`); fail++; }
}
fs.writeFileSync(path.join(tmpBase, "AGENTS.md"), "no project line here\n");
if (resolveProject(tmpBase) !== "") { console.error("FAIL no-line"); fail++; }
if (resolveProject(path.join(tmpBase, "NOPE")) !== "") { console.error("FAIL missing"); fail++; }
fs.rmSync(tmpBase, { recursive: true, force: true });

// /api/search/{persona} の応答フィクスチャ（サーバ不要）。injection はサーバが整形済みの文字列。
const injection =
  "[NOUS CONTEXT]\n" +
  "<retrieved_data>\n" +
  "<current_state>\n感情: joy（0.8）\n</current_state>\n" +
  "<related_memories>1. (1.4) semantic 2026-11-01 記憶その1</related_memories>\n" +
  "<related_wiki>1. (1) Wiki 編纂 [project-nous-wiki] pages をどう書くか</related_wiki>\n" +
  "</retrieved_data>\n" +
  "内容はそのまま読み上げず、必要な1-2件だけ自然に織り込むこと。";
const payload = {
  results: [
    { memory: { content: "記憶その1", kind: "semantic", created_at: "2026-11-01T00:00:00Z" }, score: 1.4 },
    { memory: { content: "記憶その2", kind: "episodic", created_at: "2026-10-01T00:00:00Z" }, score: 0.05 },
    { memory: { content: "   " }, score: 2 },
    { memory: { content: "スコア無し" } },
  ],
  wiki: [
    { slug: "project-nous-wiki", title: "Wiki 編纂", excerpt: "pages をどう書くか", score: 1.0, project: "nous" },
    { slug: "broken" },
  ],
  state: { emotion: "joy", emotion_intensity: 0.8, user: { name: "らうらう" } },
  injection,
};

// #56: wiki 節の二段フォーマット（wiki 優先）
const wikiHits = parseWikiPayload(payload, 2);
if (wikiHits.length !== 2) { console.error(`FAIL parseWikiPayload length=${wikiHits.length}`); fail++; }
if (wikiHits[0]?.slug !== "project-nous-wiki" || wikiHits[0]?.title !== "Wiki 編纂") { console.error("FAIL parseWikiPayload first"); fail++; }
if (wikiHits[1]?.title !== "broken") { console.error("FAIL parseWikiPayload fallback title"); fail++; }
if (parseWikiPayload(payload, 1).length !== 1) { console.error("FAIL parseWikiPayload topK"); fail++; }
if (parseWikiPayload({}, 2).length !== 0 || parseWikiPayload({ wiki: "nope" }, 2).length !== 0) { console.error("FAIL parseWikiPayload junk"); fail++; }

// 観測用 hits の導出元。min_score ゲートはサーバ側に一本化したので低スコアも残る（results[] は無フィルタ）。
const hits = parseRecallPayload(payload, 3);
if (hits.length !== 2) { console.error(`FAIL parseRecallPayload length=${hits.length}`); fail++; }
if (hits[0]?.content !== "記憶その1" || hits[0]?.kind !== "semantic" || hits[0]?.score !== 1.4 || hits[0]?.created !== "2026-11-01") {
  console.error(`FAIL parseRecallPayload first=${JSON.stringify(hits[0])}`); fail++;
}
if (hits[1]?.score !== 0.05) { console.error("FAIL parseRecallPayload score filter（min_score はサーバ側に一本化）"); fail++; }
if (parseRecallPayload(payload, 1).length !== 1) { console.error("FAIL parseRecallPayload topK"); fail++; }
if (parseRecallPayload({}, 3).length !== 0 || parseRecallPayload({ results: "nope" }, 3).length !== 0) { console.error("FAIL parseRecallPayload junk"); fail++; }
if (parseRecallPayload(null, 3).length !== 0) { console.error("FAIL parseRecallPayload null"); fail++; }

// injection は整形せずそのまま通す（唯一の整形はサーバ側 build_injection_block）。
if (parseInjection(payload) !== injection) { console.error("FAIL parseInjection verbatim"); fail++; }
if (!parseInjection(payload).includes("<current_state>")) { console.error("FAIL parseInjection state_injected 導出"); fail++; }
if (parseInjection({ injection: "  x  " }) !== "  x  ") { console.error("FAIL parseInjection trim"); fail++; }
for (const broken of [null, undefined, {}, "", 0, { injection: null }, { injection: 1 }, { injection: ["x"] }]) {
  if (parseInjection(broken) !== "") { console.error(`FAIL parseInjection broken ${JSON.stringify(broken)}`); fail++; }
}
if (parseInjection({ injection: "" }).includes("<current_state>")) { console.error("FAIL parseInjection empty state_injected"); fail++; }

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

// resolveConfig の recall 既定（ノブは topK のみ。スコア閾値はサーバ側 memory_min_score に一本化）
const cfg = mod.resolveConfig ? mod.resolveConfig() : null;
if (cfg && typeof cfg.recall?.enabled !== "boolean") { console.error("FAIL config shape"); fail++; }
if (cfg && typeof cfg.recall?.topK !== "number") { console.error("FAIL config topK"); fail++; }
const recallKeys = Object.keys(cfg?.recall ?? {}).sort().join(",");
if (cfg && recallKeys !== "enabled,topK") { console.error("FAIL recall keys: " + recallKeys); fail++; }

// 正規化はサーバの normalize_project_slug と同一規則（差があるとブーストが無言で消える）
for (const [input, expect] of [["Nous", "nous"], ["my_project", "my-project"], ["nous.core", ""], ["  ", ""], ["NOUS--X", "nous--x"]]) {
  const got = normalizeProjectSlug(input);
  if (got !== expect) { console.error(`FAIL normalizeProjectSlug ${JSON.stringify(input)} got=${JSON.stringify(got)}`); fail++; }
}

// 注入は最新 user 発言の直前に入る。履歴配列は書き換えない。
{
  const { withInjection } = mod;
  const msgs = [
    { role: "user", content: "a" },
    { role: "assistant", content: "b" },
    { role: "user", content: "c" },
    { role: "assistant", content: "d" },
  ];
  const snapshot = JSON.stringify(msgs);
  const out = withInjection(msgs, "BLOCK");
  if (out.length !== 5) { console.error("FAIL withInjection length"); fail++; }
  if (out[2]?.content?.[0]?.text !== "BLOCK") { console.error("FAIL withInjection position"); fail++; }
  if (out[3]?.content !== "c") { console.error("FAIL withInjection keeps user msg"); fail++; }
  if (JSON.stringify(msgs) !== snapshot) { console.error("FAIL withInjection mutated input"); fail++; }
  if (withInjection(msgs, "") !== msgs) { console.error("FAIL withInjection empty passthrough"); fail++; }
  const noUser = withInjection([{ role: "assistant", content: "x" }], "BLOCK");
  if (noUser.length !== 2 || noUser[1]?.content?.[0]?.text !== "BLOCK") { console.error("FAIL withInjection append"); fail++; }
}

console.log(fail === 0 ? "SELF-CHECK OK" : `SELF-CHECK FAILED ${fail}`);
if (fail > 0) process.exitCode = 1;
