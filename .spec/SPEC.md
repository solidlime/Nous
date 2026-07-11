# SPEC: WebUI デバッグ（sandbox 削除後のフロントエンド残骸処理）

## WEBUI-SANDBOX-CLEANUP: sandbox 残骸 26 箇所の整理

### 設計原則
- **単一実行経路**: コード実行 UI は MCP ルーティング（`__` ゲート）1本に統一
- **重複 UI の廃止**: 浮動パネル（coding_agent）は削除、コードブロック Run ボタンに集約
- **後方互換なし**: 旧 `/sandbox` パスは完全削除

### P0-1: `execute_tool()` に MCP ルーティング追加（バックエンド）
- 対象: `nous/application/chat/tools/builtin.py:execute_tool()`
- 旧: 組み込みツールのみ実行。`"Unknown tool: sandbox"` で死んでいた
- 新: `__` を含むツール名は `MCPClientPool.call_tool()` へルーティング
- セキュリティ: 許可リストは次スプリント。今は内部信頼前提
- テスト: `tests/unit/application/chat/tools/test_builtin.py` に `__` ルーティングテスト追加

### P0-2: コードブロック Run ボタン → OpenSandbox MCP 経由
- 対象: `nous/api/http/static/chat.js:2480-2542` `sandboxRunBlock()` → `execCodeBlock()` にリネーム
- 旧: `POST /api/chat/{persona}/sandbox/execute` → 404
- 新: `POST /api/chat/{persona}/tool` with `tool="opensandbox__execute_code"`
- 表示: 既存 UI（`hljs-run-result` クラス）を流用

### P0-3: `/code` → `/exec` リネーム
- 対象: `nous/api/http/static/chat.js:2248, 1813-1815, 921`
- 旧: `handleSlashCommand("sandbox", ...)`
- 新: `handleSlashCommand("opensandbox__execute_code", ...)`
- ウェルカム画面のヘルプも `/sandbox` → `/exec` に統一

### P1-1: Coding Agent パネル完全削除
- 削除対象:
  - `nous/api/http/static/coding_agent.js` (310行)
  - `nous/api/http/sections/coding_agent.py` (328行)
  - `nous/api/http/sections/chat.py` の `render_coding_agent_panel()` 呼び出し
- 確認: テンプレート / CSS / テストからの参照ゼロになってから削除

### P1-2: dead 関数削除
- 対象: `nous/api/http/static/chat.js:2436-2477`
  - `sandboxLog()` (呼び出し元が caAppendOutput 未定義で死亡)
  - `onSandboxEnabledChange()` (#chat-sandbox-enabled 要素不在)
  - `sandboxAddArtifact()` (#sandbox-artifacts-list 要素不在)

### P1-3: `/sandbox` ヘルプ・ウェルカム画面整理
- `SLASH_COMMANDS` 配列から削除
- ウェルカム画面の `/sandbox` バッジ → `/exec` に変更

### P2-1: `settings.js` 設定カテゴリ整理
- `CATEGORY_ORDER` から `'sandbox'` 削除
- `resetCategory()` の `cat !== 'sandbox'` 条件削除

### P2-2: デバッグログ削除
- `chat.js:1209` の `console.log("restoreChatHistory: API returned", data)` 削除

### P2-3: `animateCount()` 削除（HANDOFF 漏れ）
- 対象: `nous/api/http/static/base.js:844-868`
- 確認: `.count-up` CSS クラスが HTML に存在しないことを確認してから削除

## DOCS: ドキュメント更新
- `CLAUDE.md`: Coding Agent パネル削除の記載変更
- `docs/llm_usage_guide.md`: コード実行 UI の説明更新（`/exec` への変更、浮動パネル削除）

## VERIFY: 検証
- ruff check / format check 通過
- 関連ユニットテスト全パス
- `docker compose up` による実機確認（ヘルスチェック、MCP 接続、WebUI ロード）
