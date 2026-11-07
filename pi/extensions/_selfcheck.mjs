// kanban #12 セルフチェック: nous-events.ts の純関数 (resolveProject / formatRecall) を検証。
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
const { resolveProject, formatRecall } = mod;

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
// resolveConfig の recall 既定と project slug 正規形の内接確認
const cfg = mod.resolveConfig ? mod.resolveConfig() : null;
if (cfg && typeof cfg.recall?.enabled !== "boolean") { console.error("FAIL config shape"); fail++; }
fs.rmSync(tmpBase, { recursive: true, force: true });
console.log(fail === 0 ? "SELF-CHECK OK" : `SELF-CHECK FAILED ${fail}`);
