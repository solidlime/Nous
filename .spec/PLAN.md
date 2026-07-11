# PLAN: WebUI デバッグ（sandbox 削除後のフロントエンド残骸処理）

## 目的
`feat/browser-sandbox-mcp` マージ後に残った WebUI の sandbox 参照 26 箇所と
デッドコード残存（`animateCount`）を解消し、OpenSandbox MCP 統合に合わせた UI にする。

## 背景
- 旧サンドボックスは Python 組み込み + 8 個の REST API として実装
- 旧 REST API はマージで完全削除済み（`nous/application/sandbox/` + `routers/chat.py` の8エンドポイント）
- 代わりに OpenSandbox MCP を外部統合（`opensandbox__execute_code` 等のツール名）
- しかしフロントエンド（`static/*.js`, `sections/*.py`）には旧 API への参照が大量に残存
- 結果として Coding Agent パネル、コードブロック Run ボタン、`/code` コマンドが 404 を吐く

## 設計判断の方針
1. **単一実行経路**: `nous/application/chat/tools/builtin.py:execute_tool()` に `__` ゲートを追加し、REST API `/api/chat/{persona}/tool` 経由で任意の MCP ツール（`opensandbox__execute_code` 含む）を直接呼び出す（LLM 介在なし）
2. **`/code` → `/exec`**: スラッシュコマンドは維持しつつラベル変更。ハンドラは `opensandbox__execute_code` を直接実行
3. **Coding Agent パネル**: 浮動 UI（coding_agent.js + coding_agent.py）は完全削除。コード実行は 1 つの経路に集約
4. **コードブロック Run ボタン**: 維持。内部的に `opensandbox__execute_code` を直接呼ぶ
5. **デッドコード**: 削除確定

## 想定タスク
- [ ] Task 1: `coding_agent.js` の sandbox API 8件を LLM ブリッジに置換
- [ ] Task 2: `chat.js` の sandbox 残骸 17件を整理（`/code`, `sandboxRunBlock`, ヘルプ, `sandboxLog` 等）
- [ ] Task 3: `settings.js` から 'sandbox' カテゴリ削除
- [ ] Task 4: `base.js:844-868` の `animateCount()` 削除
- [ ] Task 5: `chat.js:1209` の console.log 削除
- [ ] Task 6: 動作確認（E2E テスト追加 or 既存テストの更新）
- [ ] Task 7: ドキュメント更新（CLAUDE.md / docs/llm_usage_guide.md）

## 質問
- Coding Agent パネルの UX 詳細は oracle の判断待ち
- テスト追加の範囲（最小 or 包括的）
