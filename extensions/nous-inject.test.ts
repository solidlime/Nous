// @vitest-environment node
// nous-inject の設定ローダ（<agentDir>/nous.json → NousConfig）の単体テスト。
// ルートの vitest.config.js は jsdom なので、node:fs/internal を使うこのファイルだけ node 環境にする。
// 型注釈は付けない（リポジトリに tsconfig が無い。vitest の esbuild がそのまま剥がす）。
import { describe, expect, it } from "vitest";
import { DEFAULT_NOUS_CONFIG, loadNousConfig, mergeNousConfig } from "./nous-inject";

describe("mergeNousConfig", () => {
  it("ファイル無し（null）は全既定", () => {
    expect(mergeNousConfig(null)).toEqual(DEFAULT_NOUS_CONFIG);
    expect(mergeNousConfig(undefined)).toEqual(DEFAULT_NOUS_CONFIG);
  });

  it("部分指定は指定値のみ反映し、他は既定", () => {
    const cfg = mergeNousConfig({ nous: { url: "http://nas:9999/mcp" } });
    expect(cfg.nous.url).toBe("http://nas:9999/mcp");
    expect(cfg.nous.hostHeader).toBe("nous:26262");
    expect(cfg.nous.persona).toBe("herta");
    expect(cfg.classify).toEqual(DEFAULT_NOUS_CONFIG.classify);
  });

  it("両セクションの部分指定を独立にマージする", () => {
    const cfg = mergeNousConfig({
      nous: { persona: "other" },
      classify: { model: "Other" },
    });
    expect(cfg.nous.persona).toBe("other");
    expect(cfg.nous.url).toBe(DEFAULT_NOUS_CONFIG.nous.url);
    expect(cfg.classify.model).toBe("Other");
    expect(cfg.classify.timeoutMs).toBe(DEFAULT_NOUS_CONFIG.classify.timeoutMs);
  });

  it("型違いはそのフィールドのみ既定", () => {
    const cfg = mergeNousConfig({
      nous: { url: 42, hostHeader: null, persona: true },
      classify: { url: {}, model: [], timeoutMs: "x" },
    });
    expect(cfg).toEqual(DEFAULT_NOUS_CONFIG);
  });

  it("timeoutMs は正の有限数のみ受ける", () => {
    expect(mergeNousConfig({ classify: { timeoutMs: 5000 } }).classify.timeoutMs).toBe(5000);
    for (const bad of [0, -1, Number.NaN, Number.POSITIVE_INFINITY]) {
      expect(mergeNousConfig({ classify: { timeoutMs: bad } }).classify.timeoutMs).toBe(
        DEFAULT_NOUS_CONFIG.classify.timeoutMs,
      );
    }
  });

  it("空文字は既定", () => {
    const cfg = mergeNousConfig({
      nous: { url: "", hostHeader: "  ", persona: "" },
      classify: { url: "", model: "" },
    });
    expect(cfg).toEqual(DEFAULT_NOUS_CONFIG);
  });

  it("壊れた構造（配列・スカラー）でも全既定", () => {
    expect(mergeNousConfig([])).toEqual(DEFAULT_NOUS_CONFIG);
    expect(mergeNousConfig("x")).toEqual(DEFAULT_NOUS_CONFIG);
    expect(mergeNousConfig({ nous: "x", classify: 7 })).toEqual(DEFAULT_NOUS_CONFIG);
  });
});

describe("loadNousConfig", () => {
  it("nous.json が無いディレクトリは全既定", () => {
    expect(loadNousConfig("/nonexistent-agent-dir-xyz")).toEqual(DEFAULT_NOUS_CONFIG);
  });
});
