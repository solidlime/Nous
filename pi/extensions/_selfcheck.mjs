// kanban #12 / #56 セルフチェック: nous-events.ts の純関数 (resolveProject / formatRecall / parseWikiPayload / buildRecallQuery) を検証。
// 実行: node D:/Code/Nous/pi/extensions/_selfcheck.mjs
// jiti と pi-coding-agent の解決には pi 本体 node_modules の alias を渡す。
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { pathToFileURL } from "node:url";

const piRoot = "C:/Users/Owner/AppData/Roaming/npm/node_modules/@earendil-works/pi-coding-agent";
const jitiLib = `${piRoot}/node_modules/jiti/lib/jiti.mjs`;
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
const { resolveProject, formatRecall, parseWikiPayload, buildRecallQuery } = mod;

const tmpBase = fs.mkdtempSync(path.join(os.tmpdir(), "nousproj-"));
const cases = [
  { proj: "nous", expect: "nous" },
  { proj: "editorial-journal", expect: "editorial-journal" },
  { proj: "nous/evil", expect: "" },
  { proj: "bad slug!", expect: "" },
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
console.log(fail === 0 ? "SELF-CHECK OK" : `SELF-CHECK FAILED ${fail}`);
