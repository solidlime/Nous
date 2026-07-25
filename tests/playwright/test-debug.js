const { chromium } = require("playwright");
const BASE = "http://localhost:26262";

(async () => {
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 1280, height: 800 } });

  // コンソールエラー収集
  const errors = [];
  page.on("console", msg => { if (msg.type() === "error") errors.push(msg.text()); });
  page.on("pageerror", err => errors.push(err.message));

  // チャットページへ移動
  await page.goto(BASE + "/#chat", { waitUntil: "networkidle", timeout: 15000 });
  await new Promise(r => setTimeout(r, 3000));

  // スクリーンショット
  await page.screenshot({ path: "/tmp/chat-debug-1.png", fullPage: true });

  // 要素調査
  const info = await page.evaluate(() => {
    const els = {};
    const input = document.getElementById("chat-input");
    if (input) {
      const rect = input.getBoundingClientRect();
      els["#chat-input"] = { 
        tag: input.tagName, 
        visible: rect.width > 0 && rect.height > 0,
        display: getComputedStyle(input).display,
        rect: { x: rect.x, y: rect.y, w: rect.width, h: rect.height }
      };
    }
    const sidebar = document.getElementById("settings-panel");
    if (sidebar) els["#settings-panel"] = getComputedStyle(sidebar).display;
    const personaSel = document.getElementById("persona-select") || document.querySelector("[name='persona']");
    if (personaSel) els["persona-select"] = personaSel.tagName;

    // 全テキストボックス
    const textareas = document.querySelectorAll("textarea, input[type='text']");
    els.textareas = Array.from(textareas).map(t => ({
      id: t.id, name: t.name, placeholder: t.placeholder,
      visible: t.offsetParent !== null,
      display: getComputedStyle(t).display
    }));

    // body 構造
    els.bodyHTML = document.body.innerHTML.substring(0, 8000);
    return els;
  });
  console.log("ELEMENTS:", JSON.stringify(info, null, 2));

  // JS エラー
  console.log("\nJS ERRORS:", errors.length > 0 ? errors : "NONE");

  // API テスト
  const apiTests = await page.evaluate(async () => {
    const results = {};
    for (const url of ["/api/memories?kind=memory&limit=5", "/api/memories", "/api/dashboard/herta"]) {
      try {
        const r = await fetch(url);
        const text = await r.text();
        results[url] = { status: r.status, len: text.length, preview: text.substring(0, 200) };
      } catch (e) {
        results[url] = { error: e.message };
      }
    }
    return results;
  });
  console.log("\nAPI TESTS:", JSON.stringify(apiTests, null, 2));

  await browser.close();
})();
