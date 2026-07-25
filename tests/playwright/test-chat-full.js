/**
 * Playwright: チャット完全テスト v2
 * - チャットタブをクリックしてアクティブ化
 * - ペルソナ "herta" を選択
 * - LLM 応答・ツールコール・記憶操作
 * - 連続メッセージ送信
 * - エラー時トースト通知
 * - バックエンド API 検証
 */
const { chromium } = require("playwright");
const BASE = "http://localhost:26262";

function sleep(ms) { return new Promise(r => setTimeout(r, ms)); }

async function waitForSSEComplete(page, timeoutMs = 45000) {
  const start = Date.now();
  while (Date.now() - start < timeoutMs) {
    const typing = await page.$("#chat-typing-indicator");
    if (!typing || !(await typing.isVisible())) {
      await sleep(500);
      const typing2 = await page.$("#chat-typing-indicator");
      if (!typing2 || !(await typing2.isVisible())) return true;
    }
    await sleep(1000);
  }
  return false;
}

async function waitForChatInput(page, timeoutMs = 15000) {
  const start = Date.now();
  while (Date.now() - start < timeoutMs) {
    const inp = await page.$("#chat-input");
    if (inp && await inp.isVisible()) return inp;
    await sleep(500);
  }
  return null;
}

async function checkToastError(page) {
  const toasts = await page.$$(".toast-error, .toast.error, [data-type='error']");
  const errors = [];
  for (const t of toasts) {
    const text = await t.textContent();
    if (text && text.trim()) errors.push(text.trim());
  }
  return errors;
}

async function run() {
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({ viewport: { width: 1280, height: 800 } });
  const page = await context.newPage();

  const consoleErrors = [];
  page.on("console", msg => { if (msg.type() === "error") consoleErrors.push(msg.text()); });

  const results = { passed: [], failed: [] };

  // ============================================================
  // TEST 1: チャットページ読み込み
  // ============================================================
  console.log("\n[TEST 1] チャットページ読み込み...");
  try {
    await page.goto(BASE + "/#chat", { waitUntil: "networkidle", timeout: 15000 });
    await sleep(2000);

    // チャットタブをクリック
    const chatTab = await page.$("[data-tab='chat']");
    if (chatTab) {
      await chatTab.click();
      await sleep(1000);
    }

    // ペルソナ選択
    const personaSel = await page.$("#persona-select");
    if (personaSel) {
      await personaSel.selectOption("herta");
      await sleep(2000);
    }

    const jsErrors = consoleErrors.filter(e =>
      e.includes("ReferenceError") || e.includes("is not defined") || e.includes("SyntaxError") || e.includes("Cannot read properties of undefined")
    );
    if (jsErrors.length === 0) {
      results.passed.push("TEST 1: ページ読み込み JSエラーなし");
      console.log("  PASS");
    } else {
      results.failed.push("TEST 1: JSエラー: " + jsErrors.join("; "));
      console.log("  FAIL:", jsErrors);
    }
  } catch (e) {
    results.failed.push("TEST 1: 例外: " + e.message);
  }

  // ============================================================
  // TEST 2: LLM 応答
  // ============================================================
  console.log("\n[TEST 2] LLM 応答テスト...");
  try {
    const input = await waitForChatInput(page, 10000);
    if (!input) throw new Error("chat-input not found/visible");

    await input.fill("自己紹介して");
    await sleep(300);
    await input.press("Shift+Enter");
    console.log("  送信中...");

    const sseOk = await waitForSSEComplete(page, 60000);
    await sleep(2000);

    const errs = await checkToastError(page);
    if (sseOk && errs.length === 0) {
      results.passed.push("TEST 2: LLM 応答成功");
      console.log("  PASS");
    } else {
      results.failed.push("TEST 2: " + (!sseOk ? "SSE タイムアウト" : "エラー: " + errs.join("; ")));
      console.log("  FAIL");
    }
  } catch (e) {
    results.failed.push("TEST 2: 例外: " + e.message);
  }

  // ============================================================
  // TEST 3: 連続 3 ターン
  // ============================================================
  console.log("\n[TEST 3] 連続 3 ターン...");
  const questions = ["こんにちは", "1+1は?", "ありがとう"];
  let multiOk = true;
  for (let i = 0; i < questions.length; i++) {
    try {
      console.log(`  ターン ${i+1}: "${questions[i]}"`);
      const inp = await waitForChatInput(page, 10000);
      if (!inp) throw new Error("input missing");
      await inp.click();
      await inp.fill(questions[i]);
      await sleep(200);
      await inp.press("Shift+Enter");

      const ok = await waitForSSEComplete(page, 60000);
      await sleep(2000);

      const errs = await checkToastError(page);
      if (!ok || errs.length > 0) {
        console.log(`  ターン ${i+1}: ${!ok ? "タイムアウト" : "エラー: " + errs.join(", ")}`);
        multiOk = false;
      }
    } catch (e) {
      console.log(`  ターン ${i+1}: 例外: ${e.message}`);
      multiOk = false;
    }
  }
  if (multiOk) {
    results.passed.push("TEST 3: 連続 3 ターン成功");
    console.log("  PASS");
  } else {
    results.failed.push("TEST 3: 連続メッセージで問題発生");
    console.log("  FAIL");
  }

  // ============================================================
  // TEST 4: ツールコール /help
  // ============================================================
  console.log("\n[TEST 4] /help コマンド...");
  try {
    const inp = await waitForChatInput(page, 10000);
    await inp.fill("/help");
    await sleep(200);
    await inp.press("Shift+Enter");

    const ok = await waitForSSEComplete(page, 30000);
    await sleep(1500);
    const errs = await checkToastError(page);
    if (ok && errs.length === 0) {
      results.passed.push("TEST 4: /help 成功");
      console.log("  PASS");
    } else {
      results.failed.push("TEST 4: " + (errs.join(", ") || "timeout"));
      console.log("  FAIL");
    }
  } catch (e) {
    results.failed.push("TEST 4: 例外: " + e.message);
  }

  // ============================================================
  // TEST 5: 記憶操作
  // ============================================================
  console.log("\n[TEST 5] 記憶操作...");
  try {
    const inp = await waitForChatInput(page, 10000);
    await inp.fill("覚えていて：Playwrightでのテストは楽しい");
    await sleep(200);
    await inp.press("Shift+Enter");

    const ok = await waitForSSEComplete(page, 60000);
    await sleep(2000);
    const errs = await checkToastError(page);
    if (ok && errs.length === 0) {
      results.passed.push("TEST 5: 記憶操作成功");
      console.log("  PASS");
    } else {
      results.failed.push("TEST 5: " + (errs.join(", ") || "timeout"));
      console.log("  FAIL");
    }
  } catch (e) {
    results.failed.push("TEST 5: 例外: " + e.message);
  }

  // ============================================================
  // TEST 6: 目標操作
  // ============================================================
  console.log("\n[TEST 6] 目標操作...");
  try {
    const inp = await waitForChatInput(page, 10000);
    await inp.fill("新しい目標を追加して：すべてのテストを通す");
    await sleep(200);
    await inp.press("Shift+Enter");

    const ok = await waitForSSEComplete(page, 60000);
    await sleep(2000);
    const errs = await checkToastError(page);
    if (ok && errs.length === 0) {
      results.passed.push("TEST 6: 目標操作成功");
      console.log("  PASS");
    } else {
      results.failed.push("TEST 6: " + (errs.join(", ") || "timeout"));
      console.log("  FAIL");
    }
  } catch (e) {
    results.failed.push("TEST 6: 例外: " + e.message);
  }

  // ============================================================
  // TEST 7: バックエンド API - /api/chat/{persona}/commitments
  // ============================================================
  console.log("\n[TEST 7] /api/chat/herta/commitments...");
  try {
    const resp = await page.evaluate(async () => {
      const r = await fetch("/api/chat/herta/commitments");
      return { status: r.status, data: await r.json() };
    });
    if (resp.status === 200) {
      results.passed.push("TEST 7: commitments OK");
      console.log("  PASS");
    } else {
      results.failed.push("TEST 7: status=" + resp.status);
      console.log("  FAIL:", resp.status);
    }
  } catch (e) {
    results.failed.push("TEST 7: 例外: " + e.message);
  }

  // ============================================================
  // TEST 8: /api/memories/{persona}
  // ============================================================
  console.log("\n[TEST 8] /api/memories/herta...");
  try {
    const resp = await page.evaluate(async () => {
      const r = await fetch("/api/memories/herta");
      return { status: r.status, data: await r.json() };
    });
    if (resp.status === 200) {
      results.passed.push("TEST 8: memories OK (count=" + (resp.data.memories?.length || 0) + ")");
      console.log("  PASS");
    } else {
      results.failed.push("TEST 8: status=" + resp.status);
      console.log("  FAIL:", resp.status);
    }
  } catch (e) {
    results.failed.push("TEST 8: 例外: " + e.message);
  }

  // ============================================================
  // TEST 9: /api/dashboard/{persona}
  // ============================================================
  console.log("\n[TEST 9] /api/dashboard/herta...");
  try {
    const resp = await page.evaluate(async () => {
      const r = await fetch("/api/dashboard/herta");
      return { status: r.status, data: await r.json() };
    });
    if (resp.status === 200 && resp.data) {
      results.passed.push("TEST 9: dashboard OK (keys: " + Object.keys(resp.data).length + ")");
      console.log("  PASS");
    } else {
      results.failed.push("TEST 9: fail status=" + resp.status);
      console.log("  FAIL");
    }
  } catch (e) {
    results.failed.push("TEST 9: 例外: " + e.message);
  }

  // ============================================================
  // 集計
  // ============================================================
  console.log("\n===== 結果 =====");
  console.log("PASS:", results.passed.length);
  for (const p of results.passed) console.log("  ✅", p);
  console.log("FAIL:", results.failed.length);
  for (const f of results.failed) console.log("  ❌", f);

  await browser.close();
  return results;
}

run().then(r => process.exit(r.failed.length > 0 ? 1 : 0)).catch(e => { console.error("FATAL:", e); process.exit(2); });
