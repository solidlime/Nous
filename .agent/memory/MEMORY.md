# MEMORY

## ブラウザ・サンドボックス MCP 移行（2026-07-11）

### MCP外部統合パターン
- `{server_name}__{tool_name}` 命名規則（例: `playwright__browser_navigate`）
- `ToolRegistry.execute()` → `__` 含む → `MCPClientPool.call_tool()` へルーティング
- HTTP (streamable-http) と stdio 両対応。設定は `ChatConfig.mcp_servers: list[dict]` に保存
- WebUIの `#chat-mcp-json` で JSON 編集可能

### 選定結果
- ブラウザ: Playwright MCP（MS公式 / 50+ツール / MCR公式イメージ / LLM不要）
- サンドボックス: OpenSandbox（Alibaba / Apache-2.0 / 53MB server / SQLite内蔵 / 公式MCP）

### sandbox_enabled 削除の波及範囲（最重要教訓）
単一フィールド削除が以下の全箇所に影響。見落とし多発地帯：
1. ChatConfig モデルフィールド（`chat_config.py` L79）
2. Repository SELECT カラムリスト（`connection.py` L266）
3. Repository 行マッピング（`connection.py` L310 — 後続カラムインデックスずれ注意）
4. Repository INSERT カラムリスト（`connection.py` L353）
5. Repository UPSERT カラムリスト（`connection.py` L392）
6. Repository save() values タプル（`connection.py` L446 — `int(config.sandbox_enabled)` 削除）
7. DBテーブル定義（`connection.py` L209 — `ALTER TABLE` または再作成必要）
8. `tools/__init__.py` の `SANDBOX_TOOLS` import
9. `routers/chat.py` sandbox REST API 8エンドポイント（L313-762）
10. `field_name` リスト（L72）

### WebUIバグ（本セッションで発見・修正）
- TTS再生: `resp.ok`（`api()` ヘルパーはJSONを返すので常にundefined）→ `audioBase64` 存在チェックに修正
- 設定保存: `context_use_llm_summary`, `episode_consolidation_enabled`, `episode_search_enabled` が field_name リスト不在
- MCP削除後: `renderMcpServerList()` 未定義 → `renderMcpJson()` の再呼び出しで代替

### デッドコードパターン
- 空オブジェクトのまま放置された設定（`DEPENDS_RULES = {}`）
- HTML要素不在で到達不能な関数（`toggleMobileNav`, `animateCount`）
- 空文字列を返すだけの互換関数（`render_chat_js()`）

### 未解決バグ（次セッション持越し）
- **C1**: `memory_create` 重複チェック — `memories` テーブルに `persona` カラム不在（常時失敗）
- **C3**: CORS ミドルウェア不在
- **H1**: `memory_update` の changes 検出ロジック破損
- **H4**: `plugin_api_key` 空文字デフォルト＝認証なし
- **H5**: `ChatConfigRepository.get()` カラムインデックスハードコード（メンテ不能）
- 残り20件の詳細は exp-6 レポート参照

### ツール評価知見
- アイテム系7ツール（全体の25%）が YAGNI 違反 → 3ツール（add/equip/search）に圧縮推奨
- `sandbox_context` は独立ツールとして価値薄 → `sandbox_execute` の返り値に統合すべき

### 計画→実装ワークフロー
- Oracle レビュー2回通過（v1: 7件指摘 → v2: 全解決確認 + 5件新規発見 → 最終修正後OK）
- 計画書は `docs/superpowers/plans/2026-07-11-browser-sandbox-migration.md`

### プロジェクト概要
Nous: 日本語特化の永続記憶 MCP サーバー。SQLite + Qdrant + Ebbinghaus 忘却曲線。WebUIダッシュボード付き。
3レイヤー構造（L1:MCP拡張, L2:EventBus基盤, L3:OpenCode Plugin）。

### 学習した知識・教訓

#### sandbox_context JSON化責務（2026-06-29）
- core関数はdict/構造化データを返し、MCPラッパーでjson.dumpsする統一パターン

#### テスト自動化ルール
- sandboxテスト: `registered_tools` fixtureでMCPラッパー関数を呼び、戻り値は `json.loads()` でパース

#### フロントエンド反映漏れ防止
- バックエンド変更時は `chat.js` + `sections/chat.py` + `routers/chat.py` の三者を必ず確認

### プロジェクトの現在の状態
- 最新ブランチ: `feat/browser-sandbox-mcp`（main より9 commits 先行、マージ待ち）
- 全ユニットテスト: 1419 passed / 7 skipped
- ruff check: 0 errors
- MCPツール: 19個（browser + sandbox 5個削除）
- Playwright MCP + OpenSandbox MCP を外部MCPサーバーとしてデフォルト登録済み
