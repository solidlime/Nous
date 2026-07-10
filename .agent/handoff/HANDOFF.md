# HANDOFF — 2026-07-11 07:45

## セッション概要
ブラウザ（agent-browser）とサンドボックス（カスタムDockerコンテナ）を削除し、Playwright MCP + OpenSandbox に外部MCP移行。並行してWebUIのバグ修正とデッドコード削除。

## 作業ブランチ
```
feat/browser-sandbox-mcp  （main より 9 commits 先行）
```

## 完了したこと
- **Docker**: docker-compose.yml に Playwright MCP + OpenSandbox Server + OpenSandbox MCP の3サービス追加。Dockerfile.sandbox / setup_agent_browser.sh 削除。Dockerfile から Chrome/Node.js/agent-browser 依存削除
- **ブラウザ削除**: `_handle_browser()` / `_find_agent_browser()` / MCPツール登録 / 定義 / 設定 / フロントエンド参照（11ファイル）全て削除
- **サンドボックス削除**: `nous/application/sandbox/` / `_tools_sandbox.py` / sandbox REST API 8エンドポイント / ChatConfigRepository sandbox_enabled（SQL 7箇所 + DBテーブル定義）/ tools/__init__.py 全て削除。attachment_upload パス `sandbox` → `uploads` 修正
- **MCP統合**: `ChatConfigRepository.get_or_create()` で新規ペルソナ時に `DEFAULT_MCP_SERVERS`（playwright + opensandbox）自動登録
- **WebUI修正**: sandbox_enabled 参照9箇所削除、TTS再生バグ修正（resp.ok→audioBase64）、設定保存不可修正（field_nameに3フィールド追加）、MCP削除後再描画修正、デッドコード削除（DEPENDS_RULES / toggleMobileNav / render_chat_js / animateCount）
- **テスト**: 1419 passed / 7 skipped
- **CI**: GitHub Actions から sandbox ビルドジョブ削除
- **ドキュメント**: CLAUDE.md / sandbox.md / llm_usage_guide.md / .env.example 更新

## 成果
```
36 files changed, +385 / -4,334 lines
8 files deleted
ruff: 0 errors, pytest: all pass, docker compose config: OK
```

## このセッションで発見された未解決バグ（次セッションで対応）

### 🔴 CRITICAL（即修正推奨）
| ID | 内容 | 場所 |
|----|------|------|
| C1 | `memory_create` 重複チェック常時失敗 — `memories` テーブルに `persona` カラムが存在しないのに WHERE persona=? で検索 | `_tools_memory.py:65-81` |
| C3 | CORS ミドルウェア完全不在 — WebUIが別ホストからアクセス時エラー | `main.py` |

### 🟠 HIGH（優先度高）
| ID | 内容 | 場所 |
|----|------|------|
| H1 | `memory_update` の changes 検出ロジック壊れ（`locals()` を見ているが実際は `updates` dict） | `_tools_memory.py:290` |
| H4 | `plugin_api_key` 空文字デフォルト = 認証なし（任意Bearerトークンで任意personaとしてアクセス可能） | `settings.py:169` |
| H5 | `ChatConfigRepository.get()` のカラム位置ハードコード（カラム追加時にインデックスずれ） | `chat_config.py:258-338` |

残り20件（H2/H3/H6/H7, M1-M9, L1-L6）の詳細は `docs/superpowers/plans/` 下の計画書または oracle の exp-6 レポートを参照。

## ツール評価（ora-3）サマリー
- **A級 12個**: メモリ6 + ペルソナ2 + list_skills + invoke_skill + goal_manage — Nous のコア資産
- **D級 7個**: アイテム系全ツール（item_add/remove/equip/unequip/update/search/history）— YAGNI違反、3ツールに圧縮推奨
- **C級 4個**: browser（削除済み）/ sandbox_reset + sandbox_context（削除済み）/ irodori_tts（存続判断要）

## 後続タスク
1. OpenSandbox MCP のペルソナ分離の実機構成（sandbox作成時の persona tag メタデータ付与）
2. `/code` スラッシュコマンドの OpenSandbox MCP 再接続
3. 発見バグ（25件）の優先順位付けと修正
4. アイテムツール7→3圧縮の検討
5. Playwright MCP のブラウザプロファイル永続化の実機確認

## .spec/ 最新状態
- `PLAN.md`: 選定結果と統合方式の概要
- `SPEC.md`: REPLACE-BROWSER / REPLACE-SANDBOX / DOCKER-INTEGRATION / PERSONA-ISOLATION / WEBUI-INTEGRATION / CODE-CLEANUP / DOCS の7要件
- `TODO.md`: 全 Chunk 完了（v2、oracle レビュー反映済み）

## 詳細計画書
`docs/superpowers/plans/2026-07-11-browser-sandbox-migration.md` — 7 Chunk 完全実装計画（oracle 2回レビュー済み）
