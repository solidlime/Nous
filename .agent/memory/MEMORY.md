# MEMORY

## ブラウザ・サンドボックス MCP 移行（2026-07-11）
前回ハンドオフの詳細は `2026-07-11.md` を参照。

### MCP外部統合パターン
- `{server_name}__{tool_name}` 命名規則（例: `playwright__browser_navigate`）
- `ToolRegistry.execute()` → `__` 含む → `MCPClientPool.call_tool()` へルーティング
- HTTP (streamable-http) と stdio 両対応。設定は `ChatConfig.mcp_servers: list[dict]` に保存
- WebUIの `#chat-mcp-json` で JSON 編集可能
- `builtin.py:execute_tool()` にも `__` ゲートを追加 (P0-1 修正)

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

### WebUIバグ（2026-07-11 セッションで修正）
- TTS再生: `resp.ok` → `audioBase64` 存在チェック
- 設定保存: `context_use_llm_summary`, `episode_consolidation_enabled`, `episode_search_enabled` field_name追加
- MCP削除後: `renderMcpServerList()` → `renderMcpJson()` 再呼び出し
- silent catch 5+6 箇所: `console.error` + `toast()` 追加
- SSE リスナーリーク: `es._sseHandlers` マップ + removeEventListener
- `__chatPersonaWatcher` 無限ポーリング: 上限20回設定
- `setAutoRefresh`: `visibilitychange` で hidden 時停止
- switchTab monkey-patch → MutationObserver + CustomEvent('tab:changed')

### デッドコードパターン
- 空オブジェクトのまま放置された設定（`DEPENDS_RULES = {}`）
- HTML要素不在で到達不能な関数（`toggleMobileNav`, `animateCount`）
- 空文字列を返すだけの互換関数（`render_chat_js()`）
- sandbox パネル関連（`coding_agent.{js,py}` 638行削除）

## バックエンド修正（2026-07-11）

### C1 修正: `memory_create` 重複チェック
旧: `WHERE persona = ? AND LOWER(content) = LOWER(?) AND deleted_at IS NULL`
新: `WHERE LOWER(content) = LOWER(?) AND lifecycle_status != 'tombstoned'`
理由: `memories` テーブルに `persona` / `deleted_at` カラムは存在しない。persona は DB ファイル単位で分離済み。

### H1 修正: `memory_update` changes 検出
旧: `[k for k in [...] if locals().get(k) is not None]`
新: `list(updates.keys())` + 空 updates 早期 return
理由: `locals()` は関数引数しか見ず、dict 引数 (`updates`) を反映しない。

### H4 修正: `plugin_api_key` 認証バイパス
新設計: `PluginConfig(enabled=False, api_key='')` を `settings.py` に追加。
3段階ゲート:
- `disabled` → 403
- `enabled + no key` → 500
- `invalid Bearer` → 401
破壊的変更: `NOUS_PLUGIN_API_KEY` → `NOUS_PLUGIN__ENABLED` + `NOUS_PLUGIN__API_KEY`

### H5 修正: `ChatConfigRepository.get()` ハードコード
旧: 51 行の `row[N]` ハードコード
新: `cursor.description` で動的カラムマッピング + `model_fields` フィルタ
耐性: ALTER TABLE カラム追加でも壊れない。

## 設計上の教訓

### パッケージレベルの eager import 禁止
`nous/domain/memory/__init__.py` が `from .sudachi_extractor import ...` すると、pytest collection 時に SudachiPy (~200MB) が常にロードされる。**`__getattr__` で遅延化する**。テストファイルも `import fitz` 等の重い C 拡張は関数内移動。

### `locals()` の使用禁止
関数引数 + dict 引数の混在では破綻する。dict を真実とする。

### 認証キー設定のデフォルト
空文字デフォルトは「認証バイパス」と等価。明示的 `enabled: bool` フラグで opt-in にする。

### 時刻 sentinel
`time.monotonic() - 0.0` は「起動からの経過秒」を意味し、CI runner 起動直後の値域を踏むリスク。sentinel は `None` + `is None` 判定。

### switchTab monkey-patch の禁止
複数 JS ファイルが同じパターンで上書きすると衝突。`MutationObserver` + `CustomEvent('tab:changed')` 方式に統一。

### `.env` 残骸のマージ後チェック
`.env` は gitignore 対象。pydantic-settings が起動時 ValidationError で気付く。マージ時は env 残骸チェックリストを持つ。

### result 型の `is_ok` / `.value` / `.error` アクセス
pyright が `Failure` / `Success` の型を絞り込めない。pydantic-style `Result[T, E]` の型ガード改善が望まれる (LSP エラーの主要因)。

## ツール評価知見
- アイテム系7ツール（全体の25%）が YAGNI 違反 → 3ツール（add/equip/search）に圧縮推奨
- `sandbox_context` は独立ツールとして価値薄 → `sandbox_execute` の返り値に統合すべき

## 計画→実装ワークフロー
- Oracle レビュー2回通過（v1: 7件指摘 → v2: 全解決確認 + 5件新規発見 → 最終修正後OK）
- 計画書は `docs/superpowers/plans/2026-07-11-browser-sandbox-migration.md`

## プロジェクト概要
Nous: 日本語特化の永続記憶 MCP サーバー。SQLite + Qdrant + Ebbinghaus 忘却曲線。WebUIダッシュボード付き。
3レイヤー構造（L1:MCP拡張, L2:EventBus基盤, L3:OpenCode Plugin）。

## 学習した知識・教訓

### sandbox_context JSON化責務（2026-06-29）
- core関数はdict/構造化データを返し、MCPラッパーでjson.dumpsする統一パターン

### テスト自動化ルール
- sandboxテスト: `registered_tools` fixtureでMCPラッパー関数を呼び、戻り値は `json.loads()` でパース
- 修正担当 fixer は自身の変更モジュールのテストのみ実行。全テストスイートはオーケストレーターの責務

### フロントエンド反映漏れ防止
- バックエンド変更時は `chat.js` + `sections/chat.py` + `routers/chat.py` の三者を必ず確認
- WebUI の状態: chat.js 2872行 / base.js 933行 / settings.js 934行

## プロジェクトの現在の状態
- ブランチ: main（feat/browser-sandbox-mcp マージ済み）
- 全ユニットテスト: 1605 passed / 7 skipped
- ruff check: 0 errors / format: clean
- CI: 5 ジョブ green (Lint & Format / Documentation Reminder / Integration Tests / Unit Tests / Docker Build & Push)
- MCPツール: 19個（browser + sandbox 5個削除）
- 外部MCP: Playwright MCP + OpenSandbox MCP をデフォルト登録
- 既知バグ（25件）: 全解消。バックエンド HIGH 3件 + WebUI 30件 = 0件
- LSP エラー: H5 修正の副作用 (`dict[str, Any]` 型推論) あり、ランタイム影響なし
