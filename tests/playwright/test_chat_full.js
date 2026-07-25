/**
 * Playwright 包括的テスト: チャット全機能
 * - チャットタブ自動クリック + ペルソナ選択
 * - LLM 応答・ツールコール・記憶操作
 * - 連続 3 ターン会話
 * - エラートースト検出
 * - バックエンド API 検証
 */
const { chromium } = require("playwright");
const BASE = "http://localhost:26262";
const PERSONA = "herta";

function sleep(ms) { return new Promise(r => setTimeout(r, ms)); }

async function waitSSE(page, timeout = 60000) {
  const start = Date.now();
  while (Date.now() - start < timeout) {
    const el = await page.$("#chat-typing-indicator");
    if (!el || !(await el.isVisible())) {
      await sleep(600);
      const el2 = await page.$("#chat-typing-indicator");
      if (!el2 || !(await el2.isVisible())) return true;
    }
    await sleep(1000);
  }
  return false;
}

async function waitForInput(page, timeout = 15000) {
  const start = Date.now();
  while (Date.now() - start < timeout) {
    const inp = await page.$("#chat-input");
    if (inp && await inp.isVisible()) return inp;
    await sleep(500);
  }
  return null;
}

async function checkToastError(page) {
  const toasts = await page.$$(".toast-error, .toast.error, [class*='error']");
  const errors = [];
  for (const t of toasts) {
    const text = await t.textContent().catch(() => "");
    if (text && text.trim()) errors.push(text.trim());
  }
  return errors;
}

async function main() {
  const browser = await chromium.launch({ headless: true });
  const ctx = await browser.newContext({ viewport: { width: 1280, height: 800 } });
  const page = await ctx.newPage();

  const jsErrors = [];
  page.on("console", msg => { if (msg.type() === "error") jsErrors.push(msg.text()); });

  const R = { pass: [], fail: [] };

  // ============================================================
  // TEST 1: ページ読み込み + JSエラー
  // ============================================================
  console.log("\n[1] ページ読み込み");
  await page.goto(BASE + "/#chat", { waitUntil: "networkidle", timeout: 15000 });
  await sleep(2000);

  // チャットタブを確実にアクティブ化
  const chatTab = await page.$("[data-tab='chat']");
  if (chatTab) { await chatTab.click(); await sleep(1500); }

  // ペルソナ選択
  const personaSel = await page.$("#persona-select");
  if (personaSel) { await personaSel.selectOption(PERSONA); await sleep(2000); }

  const errFilter = (e) => /ReferenceError|not defined|Cannot read|SyntaxError/.test(e);
  const errs = jsErrors.filter(errFilter);
  if (errs.length) {
    R.fail.push("JSエラー: " + errs.join("; "));
    console.log("  FAIL:", errs.slice(0, 3));
  } else {
    R.pass.push("JSエラーなし");
    console.log("  PASS");
  }

  // ============================================================
  // TEST 2: LLM 応答
  // ============================================================
  console.log("\n[2] LLM 応答");
  try {
    const input = await waitForInput(page);
    if (!input) throw new Error("chat-input not found");
    await input.click();
    await input.fill("自己紹介して");
    await sleep(300);
    await input.press("Shift+Enter");
    console.log("  送信中...");

    if (!(await waitSSE(page, 90000))) throw new Error("SSE timeout");
    await sleep(2000);
    const toastErrs = await checkToastError(page);
    if (toastErrs.length) throw new Error(toastErrs.join("; "));
    R.pass.push("LLM 応答成功");
    console.log("  PASS");
  } catch (e) {
    R.fail.push("LLM 応答失敗: " + e.message);
    console.log("  FAIL:", e.message);
  }

  // ============================================================
  // TEST 3: 連続 3 ターン会話
  // ============================================================
  console.log("\n[3] 連続 3 ターン");
  const msgs = ["こんにちは", "1+1は?", "ありがとう"];
  let multiPass = true;
  for (let i = 0; i < msgs.length; i++) {
    try {
      const inp = await waitForInput(page);
      if (!inp) throw new Error("input missing");
      await inp.click();
      await inp.fill(msgs[i]);
      await sleep(200);
      await inp.press("Shift+Enter");
      console.log(`  ターン${i+1}: "${msgs[i]}" → 待機中...`);
      if (!(await waitSSE(page, 90000))) throw new Error("SSE timeout");
      await sleep(2000);
      const errs = await checkToastError(page);
      if (errs.length) throw new Error("toast:" + errs.join(", "));
    } catch (e) {
      console.log(`  ターン${i+1} FAIL:`, e.message);
      multiPass = false;
    }
  }
  (multiPass ? R.pass : R.fail).push("連続3ターン" + (multiPass ? "成功" : "失敗"));
  console.log(multiPass ? "  PASS" : "  FAIL");

  // ============================================================
  // TEST 4: ツールコール /help
  // ============================================================
  console.log("\n[4] ツールコール /help");
  try {
    const inp = await waitForInput(page);
    await inp.fill("/help"); await sleep(200);
    await inp.press("Shift+Enter");
    if (!(await waitSSE(page, 30000))) throw new Error("timeout");
    await sleep(1500);
    const errs = await checkToastError(page);
    if (errs.length) throw new Error(errs.join(", "));
    R.pass.push("/help 成功");
    console.log("  PASS");
  } catch (e) {
    R.fail.push("/help 失敗: " + e.message);
    console.log("  FAIL:", e.message);
  }

  // ============================================================
  // TEST 5: 記憶操作
  // ============================================================
  console.log("\n[5] 記憶操作");
  try {
    const inp = await waitForInput(page);
    await inp.fill("覚えていて：Playwrightのテストは順調");
    await sleep(200);
    await inp.press("Shift+Enter");
    if (!(await waitSSE(page, 90000))) throw new Error("timeout");
    await sleep(2000);
    const errs = await checkToastError(page);
    if (errs.length) throw new Error(errs.join(", "));
    R.pass.push("記憶操作成功");
    console.log("  PASS");
  } catch (e) {
    R.fail.push("記憶操作失敗: " + e.message);
    console.log("  FAIL:", e.message);
  }

  // ============================================================
  // TEST 6: 目標操作
  // ============================================================
  console.log("\n[6] 目標操作");
  try {
    const inp = await waitForInput(page);
    await inp.fill("新しい目標を追加して：全テストを通すこと");
    await sleep(200);
    await inp.press("Shift+Enter");
    if (!(await waitSSE(page, 90000))) throw new Error("timeout");
    await sleep(2000);
    const errs = await checkToastError(page);
    if (errs.length) throw new Error(errs.join(", "));
    R.pass.push("目標操作成功");
    console.log("  PASS");
  } catch (e) {
    R.fail.push("目標操作失敗: " + e.message);
    console.log("  FAIL:", e.message);
  }

  // ============================================================
  // API 検証
  // ============================================================
  const apis = [
    ["7", "/api/chat/herta/commitments", null],
    ["8", "/api/memories/herta", null],
    ["9", "/api/dashboard/herta", null],
  ];
  for (const [num, url] of apis) {
    console.log(`\n[${num}] ${url}`);
    try {
      const r = await page.evaluate(async (u) => { const res = await fetch(u); return { status: res.status, json: await res.json() }; }, url);
      if (r.status !== 200) throw new Error("status=" + r.status);
      R.pass.push(url + " OK");
      console.log("  PASS");
    } catch (e) {
      R.fail.push(url + " FAIL: " + e.message);
      console.log("  FAIL:", e.message);
    }
  }

  // ============================================================
  // レポート
  // ============================================================
  console.log("\n========== 結果 ==========");
  console.log(`PASS: ${R.pass.length} / FAIL: ${R.fail.length}`);
  R.pass.forEach(p => console.log("  ✅", p));
  R.fail.forEach(f => console.log("  ❌", f));

  await browser.close();
  return R.fail.length === 0;
}

main().then(ok => process.exit(ok ? 0 : 1)).catch(e => { console.error("FATAL:", e); process.exit(2); });
