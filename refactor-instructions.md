# Nous v3.5.0 — リファクタリング指示書 (2026-07-25 更新)

> **作成**: 2026-07-25 | コードベース全探索 + 4並列探索タスクの結果に基づく総合分析
> **対象**: `nous/` 全211 Pythonファイル、92テストファイル、6ペルソナ設定
> **前提**: Phase 1〜4 は完了済み。本指示書は現状の残存負債に焦点を当てる。

---

## Objective

既存仕様を壊さず、残存する技術的負債を安全に削減し、今後変更しやすい状態にすること。

**絶対にしないこと**: 見た目の綺麗さを目的とした全面書き換え、古いコードを全て悪と決めつけた削除、無関係な整形や「ついで」のリファクタリング。

---

## Project Understanding

### プロジェクト概要
- **Nous v3.5.0**: MCP対応の永続記憶サーバー。Claude Desktop / OpenCode用。
- **技術スタック**: Python 3.12+, FastMCP + FastAPI + Uvicorn, SQLite (WAL), Qdrant, ONNX Runtime
- **19 MCPツール**: `get_context`, `memory_create/read/update/delete/search/stats`, `update_context`, `goal_manage`, `item_*`, `invoke_skill`, `search`, `image_generate`, `read_pdf`, `irodori_tts`, `sandbox`, `sandbox_files`, `list_skills`
- **主要ワークフロー**: チャットパイプライン (Prepare → ContextLoader → PromptBuild → Compress → Inference → Post)
- **エントリポイント**: `nous/main.py` → `create_app()` → FastMCPサーバー (port 26262)
- **DB**: ペルソナごとに `memory.sqlite` (15テーブル+FTS5) + `inventory.sqlite` + `config.json`
- **フロントエンド**: Vanilla JS SPA, `N.*` 名前空間, `static/` 配下に50ファイル配置済み

### アーキテクチャ
```
config → domain ← application → infrastructure ← api
```
- **domain**: 純粋Python dataclass。`MemoryService` は5サブサービスのFacade（417行）
- **application**: パイプライン型。`AppContextRegistry` がDIコンテナ相当
- **infrastructure**: SQLite/Qdrant/LLM/埋め込みの実装詳細
- **api**: MCPツール (12個) + HTTPルーター (11個)

### 完了済みのリファクタリング（再実装禁止）
- Phase 1: asyncioタスクリーク修正、CI改善、Makefile導入
- Phase 2: `Result[T,E]` 拡張、`SQLiteRepository` 基底クラス、`MemoryService` 5-subservice分割
- Phase 3: 5大規模ファイル分解 (`session_store` 3分割, `memory_repo` Mixin 3分割, `prepare` 3分割, `compress` Mixin 2分割, `memory_llm` 2分割)
- Phase 4: `ChatConfig` 4-subconfig分割 (Provider/Session/Compression/Tool) + Pact契約テスト + CI coverage/bandit
- WebUIリファクタリング: 15フェーズ、38JSモジュール、N.*名前空間統合

---

## Behaviors To Preserve

### 絶対に壊してはいけない
1. **19 MCPツールの入出力形式**: 外部LLMクライアントが依存。契約テスト (Pact) があるので、ツール変更時は必ず `pytest tests/contracts/` を通過させること
2. **HTTP APIエンドポイント**: WebUIのSPAが依存。エンドポイントの削除・改名・レスポンス形式変更禁止
3. **DBスキーマ**: `memories` テーブル42カラム、バイテンポラル (`valid_from/valid_until`)、FTS5全文検索、memory_links構造。ALTER TABLE 以外の破壊的変更禁止
4. **ペルソナ分離**: 各ペルソナの `memory.sqlite` + `inventory.sqlite` + `config.json` は独立。他ペルソナのデータを読み書きしてはいけない
5. **config.json のシリアライズ形式**: `ChatConfig` のFacadeがフラットJSONを生成。キー名変更・削除は互換性破壊
6. **チャットパイプラインのステップ順序**: Prepare→ContextLoader→PromptBuild→Compress→Inference→Post の順序と各ステップの責務は維持

### 注意すべき境界
- **認証**: `PersonaMiddleware` が Bearerトークン/X-Persona/環境変数でペルソナ解決。このフローを変更する場合は全クライアントの設定変更が必要
- **非同期タスク管理**: `post.py` の `_background_tasks` リスト管理、`asyncio.create_task` の7箇所は現在適切に追跡済み。新規追加時は必ず追跡すること
- **外部MCP連携**: Playwright MCP (port 8931) + OpenSandbox MCP (port 8001-8003)。接続URL・プロトコル変更禁止

---

## Non-Negotiables

1. **最初に `git status` を確認する**: 既存の未コミット変更と自分の変更を混ぜない
2. **編集前にbaseline検証結果を記録する**: `make test` と `make lint` の結果を保存
3. **変更は小さく戻しやすい単位にする**: 1コミット = 1関心事
4. **無関係な整形や「ついで」のリファクタリングをしない**: スコープ厳守
5. **既存挙動を勝手に変えない**: テストが失敗したら、まず実装側が間違っていると疑う
6. **正しさが不明な場合は実装を止めて質問する**: 推測でDBやAPIを変更しない
7. **各フェーズごとに検証する**: `make test` が通ることを毎回確認
8. **最後に実行したコマンドと結果を報告する**

---

## Stop And Ask Conditions

以下の状況では実装を中断し、ユーザーに確認すること：

1. **DBスキーマ変更が必要になった場合**: ALTER TABLE は `migration_one_shot.py` パターンに従う。バージョン管理なしなので変更の冪等性に注意
2. **`ChatConfig` のフィールド名を変更する場合**: `config.json` の互換性が壊れる。`model_validator(mode="before")` で旧名を受け付ける必要あり
3. **MCPツールのパラメータやレスポンス形式を変更する場合**: Pact契約テストが失敗する。Consumer側（外部LLM）の更新も必要
4. **`static/` のJSファイルを削除する場合**: HTML sections (`sections/chat/chat_sidebar.py` 等) の `onclick` 参照がないか確認
5. **認証・課金・通知・外部APIに関わる変更**: 影響範囲が広いため要確認
6. **コードの意味が複数解釈できる場合**: テストと実装が矛盾している、削除候補のコードが本当に不要か判断できない場合
7. **複数の設計案があり、プロダクト判断が必要な場合**

---

## Baseline Commands

```bash
# 品質ゲート（全てパスすること）
make lint         # ruff check + ruff format --check
make test         # pytest tests/unit/ -q
make test-all     # pytest -q（全テスト）
make typecheck    # mypy nous/
make coverage-fail  # pytest --cov=nous --cov-fail-under=70
make bandit       # bandit -r nous/ -ll
make ci           # lint → typecheck → test-all → bandit → coverage-fail

# 個別確認
pytest tests/unit/test_chat_config.py -v  # ChatConfigのテスト
pytest tests/contracts/ -v                 # Pact契約テスト
pytest tests/integration/ -v               # 統合テスト
```

---

## Debt Map

### 🔴 Critical（残存なし）
Phase 1〜4 ですべて解消済み。

### 🟡 High Priority

| ID | 負債 | ファイル | 行数 | 根拠 |
|----|------|---------|:---:|------|
| D1 | **chat_sidebar.py の巨大f-string** | `nous/api/http/sections/chat/chat_sidebar.py` | 743 | 743行のPython f-string。HTML/CSS/JSが1つの文字列に埋め込まれ、テスト不可能・保守困難。全sections中最大 |
| D2 | **chat.py ルーターの全エンドポイントネスト** | `nous/api/http/routers/chat.py` | 643 | 1つの `register_chat_routes` 関数に全エンドポイントがネスト。独立テスト不可。広範な `except Exception` |
| D3 | **persona.py ルーターのエラーハンドリング** | `nous/api/http/routers/persona.py` | 593 | 同様のネストパターン + 多くの `except Exception` + `pass` で例外を握りつぶし |

### 🟠 Medium Priority

| ID | 負債 | ファイル | 行数 | 根拠 |
|----|------|---------|:---:|------|
| D4 | **広範な `except Exception` パターン** | `routers/admin.py` 他、全体で204箇所 | - | `except Exception as exc: pass` や `except Exception: return JSONResponse(...)` がエラー情報を隠蔽。特に `admin.py` が顕著 |
| D5 | **`_get_session_memories` スタブ** | `nous/domain/memory/service.py:424-431` | 8 | Hebbianリンクが完全無効。MEMORY.md記載の配管は完了しているがデータ投入がない |
| D6 | **マイグレーションシステムのバージョン不在** | `nous/infrastructure/sqlite/migrations.py` | - | バージョン番号なし、全累積実行。現在のDB状態をプログラムから判断できない |
| D7 | **`hub.db` の用途不明ファイル** | `data/hub.db` | - | ファイルは存在するが読み取り不能。死にデータの可能性。削除して動作確認が必要 |
| D8 | **`memory_aux_repo.py` の責務過多** | `nous/infrastructure/sqlite/memory_aux_repo.py` | 345 | ページネーション・ブロック・強度・統計・バージョンが1ファイル。適度だがさらなる分割余地あり |
| D9 | **`legacy_importer.py` のエラーハンドリング** | `nous/migration/importers/legacy_importer.py` | 756 | 6箇所の `except Exception: pass` が移行エラーを完全に隠蔽 |

### 🟢 Low Priority / Suggestions

| ID | 負債 | ファイル | 根拠 |
|----|------|---------|------|
| D10 | `os.path` と `pathlib` の混在 | `nous/main.py:24` | `os.path.join` でパスを構築しつつ、`Path(__file__).resolve().parent` も併用 |
| D11 | 空のテストディレクトリ | `tests/unit/api/http/` | ルーター単位のUTがない（統合テストのみ） |
| D12 | フロントエンドJSの大型ファイル | `static/features/overview/overview-core.js` (45KB), `static/chat/chat-settings.js` (43KB) | モジュラー化済みだが各ファイルは依然大きい。機能単位でのさらなる分割が望ましい |
| D13 | ベンチマークテストのコピペミス | `tests/benchmark/test_search_perf.py:37` | `make_memories(100)` を3回呼んでいるが1000件テストでは使われていない |
| D14 | Screenshot baselines 未生成 | `tests/ui/screenshots/` | `.gitkeep` のみ。初回実行時に `--update-snapshots` が必要 |

---

## Implementation Phases

各フェーズは独立して実施可能。依存関係は明示する。

### Phase 1: 検証基盤の確認（必須・最初）

**目的**: 現状のテストが全て通ることを確認し、baselineを記録する。

```bash
make lint          # ruff check + format
make test          # ユニットテスト
make typecheck     # mypy
make bandit        # セキュリティスキャン
```

**成果物**: 各コマンドの実行結果（PASS/FAILの記録）

**注意**: `git status` で未コミット変更がないことを確認すること。既存の変更がある場合は先にコミットするか、stashすること。

---

### Phase 2: 安全な整理（独立実行可能）

#### 2.1: D7 — `hub.db` の確認と削除判定
- **ファイル**: `data/hub.db`
- **方法**: コードベース全体で `hub.db` を grep し、参照がないことを確認
- **検証**: 参照がない場合、削除してサーバー起動確認
- **リスク**: 低。参照がなければ安全に削除可能

#### 2.2: D11 — 空テストディレクトリの整理
- **ファイル**: `tests/unit/api/http/`
- **方法**: ディレクトリが空であることを確認。空なら削除するか、ルーターUTを作成する方針を決定
- **注意**: `tests/unit/api/http/` が空でも `tests/unit/api/` が存在する理由を確認（`test_cors.py` 等があるため）
- **リスク**: 最低。ディレクトリ削除のみ

#### 2.3: D13 — ベンチマークテストの修正
- **ファイル**: `tests/benchmark/test_search_perf.py:37`
- **方法**: `make_memories(100)` の3回呼び出しが不要なら1回に統合
- **検証**: `pytest tests/benchmark/ -v`
- **リスク**: 最低

---

### Phase 3: エラーハンドリング改善（Phase 2完了後）

#### 3.1: D9 — `legacy_importer.py` の `except Exception: pass` 撲滅
- **ファイル**: `nous/migration/importers/legacy_importer.py`
- **場所**: 6箇所 (L88, 179, 213, 249, 283, 324)
- **方法**: 各 `except Exception: pass` を最低限 `logger.warning("Import skip: ...", exc_info=True)` に変更
- **リスク**: 低。ログ追加のみ、制御フロー変更なし
- **検証**: `pytest tests/unit/test_jsonl_importer.py -v`

#### 3.2: D4 — ルーターの `except Exception` 改善
- **ファイル**: `nous/api/http/routers/admin.py` (最も顕著), `chat.py`, `persona.py`
- **方法**: 
  1. 各 `except Exception` に `logger.exception()` を追加（デバッグ情報の確保）
  2. `pass` で握りつぶしている箇所は、具体的な例外型に絞る
- **注意**: エラーレスポンスの形式を変更しないこと（WebUIが依存）
- **リスク**: 中。エラーハンドリング変更はフロントエンドのエラー表示に影響する可能性あり
- **検証**: `pytest tests/integration/test_http_api.py -v` + `pytest tests/integration/test_error_handling.py -v`

---

### Phase 4: 構造改善（Phase 3完了後）

#### 4.1: D8 — `memory_aux_repo.py` の分割
- **ファイル**: `nous/infrastructure/sqlite/memory_aux_repo.py` (345行)
- **現在の責務**: ページネーション、メモリブロック、メモリ強度、統計、バージョン管理
- **提案**: 
  - `memory_aux_repo.py` → ページネーション + バルク操作のみに
  - `memory_block_repo.py` → メモリブロックCRUD
  - `memory_strength_repo.py` → 強度計算（既存 `strength_repo.py` と統合）
- **後方互換**: `memory_repo.py` 経由でアクセスできるよう再エクスポートを維持
- **リスク**: 中。複数ファイルにまたがる変更。全既存importパスの確認必須
- **検証**: `pytest tests/unit/test_sqlite_repos.py tests/unit/test_memory_strength.py -v`

#### 4.2: D5 — `_get_session_memories` スタブの実装
- **ファイル**: `nous/domain/memory/service.py:424-431`
- **現状**: 常に `[]` を返す。Hebbianリンク (`_create_hebbian_links`) が無効
- **前提**: `session_event_repo` は既に注入済み (MEMORY.md Phase 3.7)
- **方法**: `session_event_repo` から `session_id` に紐づく直近のイベントを問い合わせ、アクセスされたメモリキーを抽出
- **注意**: MEMORY.md記載の「データ投入がない」問題を解決するには、`post.py` でセッションイベント記録も実装する必要がある
- **リスク**: 中。未テストのコードパスを有効化する。段階的に有効化すること
- **検証**: `pytest tests/unit/test_memory_links.py -v`

---

### Phase 5: 大規模ファイル分割（Phase 4完了後、慎重に）

#### 5.1: D1 — chat_sidebar.py のテンプレート分離
- **ファイル**: `nous/api/http/sections/chat/chat_sidebar.py` (743行)
- **方法**:
  1. 各 `<details>` ブロックを個別のテンプレート関数に抽出（`_render_provider_section()`, `_render_mcp_section()` 等）
  2. `render_chat_sidebar()` は各セクションを呼び出すオーケストレーターに
  3. インラインCSSを `static/styles/` に移動（該当するスタイルのみ）
- **注意**: 
  - `onclick`, `onchange`, `onmouseenter` 等のJSハンドラ名を変更しない
  - `<i data-lucide="...">` のアイコン名を変更しない
  - `id` 属性値を変更しない（JSが `document.getElementById` で参照）
- **リスク**: 高。JSのDOM参照が壊れる可能性。変更後はWebUIの全タブ + チャット機能の手動確認必須
- **検証**: 
  1. `pytest tests/integration/test_dashboard_e2e.py -v`
  2. 手動: チャット設定パネルの全項目表示・操作確認
  3. 手動: プロバイダ切り替え、MCPツール設定、TTS設定、画像生成設定

#### 5.2: D2 — chat.py ルーターのエンドポイント分離
- **ファイル**: `nous/api/http/routers/chat.py` (643行)
- **方法**:
  1. `register_chat_routes` 内の各 `async def` エンドポイントをモジュールレベル関数に抽出
  2. `register_chat_routes` は各関数を `mcp.custom_route` で登録するだけの薄い層に
  3. 共通のヘルパー（`_resolve_persona`, `_safe_get_context`）は `deps.py` から再利用
- **注意**: エンドポイントURL、HTTPメソッド、レスポンス形式を一切変更しない
- **リスク**: 中。関数のスコープ変更によるクロージャ変数の参照切れに注意
- **検証**: `pytest tests/integration/test_http_routers.py tests/integration/test_http_api.py -v`

---

### Phase 6: 提案フェーズ（自動実装禁止、要レビュー）

以下の項目は実装前にユーザー確認が必要。提案のみ行い、勝手に実装しないこと。

#### 6.1: D6 — マイグレーションバージョニングの導入
- **提案**: `_migration_version` テーブルを追加し、マイグレーション番号を管理
- **影響**: DBスキーマ追加。既存ペルソナ全員のDBに新テーブル作成
- **要確認**: データ整合性リスクと引き換えに導入する価値があるか

#### 6.2: D3 — persona.py ルーターの分割
- **提案**: `register_persona_routes` をエンドポイント単位の小関数に分解
- **影響**: 中。ルーターの内部構造変更のみ、API互換性は維持

#### 6.3: D12 — フロントエンドJSのさらなる分割
- **提案**: `overview-core.js` (45KB), `chat-settings.js` (43KB), `settings-form.js` (33KB) の分割
- **影響**: HTML sections の `<script>` タグ変更が必要。ロード順序の管理が複雑化
- **要確認**: 現在の構造で運用上の問題があるか

---

## Verification Requirements

各フェーズ完了時に以下を実行し、結果を報告すること：

| フェーズ | 必須検証 | 追加検証 |
|---------|---------|---------|
| Phase 1 | `make lint && make test && make typecheck && make bandit` | — |
| Phase 2 | `make test` | フェーズ内容に応じた個別テスト |
| Phase 3 | `make test && make test-all` | `pytest tests/integration/ -v` |
| Phase 4 | `make test && make test-all && make typecheck` | `pytest tests/unit/test_* -v` (該当ファイル) |
| Phase 5 | `make ci` (全品質ゲート) | WebUI手動確認 + `pytest tests/integration/ -v` |

---

## Reporting Format

各フェーズ完了時に以下の形式で報告すること：

```
### Phase X 完了報告

**実行コマンドと結果**:
- `make lint` → PASS/FAIL
- `make test` → X passed, Y failed
- （その他実行したコマンド）

**変更ファイル**:
- path/to/file1.py: 変更内容（1行要約）
- path/to/file2.py: 変更内容（1行要約）

**発生した問題**:
- （あれば）

**未確認の懸念**:
- （あれば）
```

---

## Out-of-scope Items

以下の項目は本指示書のスコープ外：

1. **新機能の追加**: リファクタリングのみ。機能追加は別タスク
2. **フレームワークの変更**: FastMCP → 他フレームワークへの移行は禁止
3. **DBエンジンの変更**: SQLite → PostgreSQL 等の移行は禁止
4. **フロントエンドフレームワークの導入**: React/Vue 等への移行は禁止。Vanilla JSのまま改善
5. **テストフレームワークの変更**: pytest → 他への移行は禁止
6. **Pythonバージョンの変更**: 3.12 固定
7. **ペルソナデータの修正**: `data/persona/*/` の内容は一切触らない
8. **ドキュメントの大規模書き換え**: 変更に伴う最小限の更新のみ
9. **Node.jsビルドシステムの導入**: 現在のViteベースのビルドを維持
