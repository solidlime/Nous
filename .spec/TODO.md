# TODO: WebUI デバッグ（sandbox 削除後のフロントエンド残骸処理）

（@oracle 設計判断反映 + @explorer 調査結果 + 実装完了済み）

## Phase 0: バックエンド中核修正
- [x] **P0-1**: `execute_tool()` に `__` MCP ルーティング追加
  - `nous/application/chat/tools/builtin.py:execute_tool()` を修正
  - `tests/unit/application/chat/tools/test_builtin.py` にテスト6件追加
  - **ブロッカー解消済み**

## Phase 1: フロントエンド書き換え・削除
- [x] **P0-2**: `sandboxRunBlock()` → `execCodeBlock()` リネーム + OpenSandbox MCP 呼び出し
  - `nous/api/http/static/chat.js:2429-2472`
- [x] **P0-3**: `/code` → `/exec` リネーム + ウェルカム画面更新
  - `nous/api/http/static/chat.js:921, 1813-1815, 2247-2250`
- [x] **P1-1**: Coding Agent パネル完全削除
  - 削除: `nous/api/http/static/coding_agent.js` (310行)
  - 削除: `nous/api/http/sections/coding_agent.py` (328行)
  - 修正: `nous/api/http/sections/chat.py` の `render_coding_agent_panel()` 呼び出し削除
- [x] **P1-2**: dead 関数削除
  - `nous/api/http/static/chat.js:2436-2477` (sandboxLog, onSandboxEnabledChange, sandboxAddArtifact)
- [x] **P1-3**: `/sandbox` ヘルプ・ウェルカム画面整理（P0-3 に統合）

## Phase 2: 整理
- [x] **P2-1**: `settings.js` 設定カテゴリ整理
  - `nous/api/http/static/settings.js:45, 734`
- [x] **P2-2**: `chat.js:1209` の `console.log` 削除
- [x] **P2-3**: `animateCount()` 削除
  - `nous/api/http/static/base.js:841-872` + `base.css:557`

## Phase 3: 検証・ドキュメント
- [x] WebUI 関連ユニットテスト全パス
- [x] ruff check / format check 通過
- [ ] **docker compose up による実機確認**（ユーザー指示・次ステップ）
- [ ] ドキュメント更新（CLAUDE.md / docs/llm_usage_guide.md）— WebUI 修正の PR description / docs/ 反映
- [ ] コミット + push + CI 確認
- [ ] HANDOFF.md 更新

## 進捗
2026-07-11 開始・実装完了
- P0-1 担当: fixer A（バックエンド）— 完了
- P0-2/P0-3/P1-2/P1-3/P2-2 担当: fixer B（chat.js）— 完了
- P1-1/P2-1/P2-3 担当: fixer C（パネル削除・整理）— 完了
- バックエンド MCP ゲート: `__` を含むツール名で `MCPClientPool.call_tool()` へルーティング
- フロントエンド: 浮動パネル削除、コードブロック Run ボタン → OpenSandbox 直接呼出
- テスト: `test_builtin.py` 6/6, `test_dashboard_e2e.py` 22/22, 関連 101/101 通過

## 次のアクション
1. WebUI 修正のコミット + push
2. CI 通過確認
3. フルテストスイート実行（OOM 修正後）
4. ハンドオフ更新
