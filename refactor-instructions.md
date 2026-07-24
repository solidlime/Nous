# Nous v3.5.0 — リファクタリング指示書

> 作成: 2026-07-25 | コードベース全探索 + 3並列探索タスクの結果に基づく総合分析
> 対象: `nous/` 全189 Pythonファイル、84テストファイル、6 persona設定

---

## 1. コードベース主要指標

| 指標 | 値 | 判断 |
|------|:--:|------|
| Pythonファイル数 | 189 | 適正規模 |
| 総行数 | ~29,352 | — |
| テスト数 | 1,337 pass / 7 skip | 高いテストカバレッジ |
| 500行超ファイル | 15 | **注意**: 分解推奨 |
| 800行超ファイル | 3 | **要対応**: session_store(809), memory_repo(776), prepare(748) |
| `# noqa:` 抑制 | 49箇所 | **高い**: 多くはSQLインジェクション抑制 |
| `# nosec` 抑制 | 13箇所 | **高い**: bandit警告の抑制 |
| 未管理 `asyncio.create_task` | 8箇所 | **注意**: タスクリークの可能性 |
| レポジトリ内 `node_modules` | 63MB | **問題**: Viteビルド成果物がGit管理下 |

---

## 2. 🔴 クリティカル（即時対応推奨）

### 2.1 `asyncio.create_task()` のタスクリーク

| ファイル:行 | 問題 |
|---|---|
| `nous/domain/memory/service.py:245` | `create_task(_evolve_related_memories(...))` — 戻り値未保持 |
| `nous/domain/memory/service.py:255` | `create_task(_invalidate_contradicted_memory(...))` — 戻り値未保持 |
| `nous/application/chat/pipeline/post.py:119` | `create_task(...)` — 戻り値未保持 |
| `nous/application/chat/pipeline/prepare.py:695,702` | 戻り値一部保持、一部未保持 |

**リスク**: 未捕捉の例外がタスク消滅。メモリ進化・矛盾検出がサイレント失敗する。
**対応**: 戻り値をリストで保持し、`done` コールバックで例外ログ。または `TaskGroup` に移行。

### 2.2 SQLインジェクション抑制の濫用

`nous/infrastructure/sqlite/memory_repo.py` 他で `f"SELECT * FROM memories WHERE {where_clause}"` + `# noqa: S608 # nosec B608` が多数。

| ファイル | 件数 | 行例 |
|---|---|---|
| `memory_repo.py` | 10+ | L348-349: `f"SELECT * FROM memories WHERE {where_clause}"` |
| `persona_repo.py` | — | 同様パターン |
| `equipment_repo.py` | — | 同様パターン |

**対応**: `WHERE {where_clause}` は文字列連結だが実際はプレースホルダで保護済み。ただし可読性と監査性のため、クエリビルダークラスに抽出し `# noqa` を削除。

### 2.3 `_get_session_memories` スタブ実装

**ファイル**: `nous/domain/memory/service.py:424-431`
```python
def _get_session_memories(self, _new_memory: Memory) -> list:
    """Return memories recently accessed in the current conversation turn.
    Stub implementation — always returns empty list.
    Will be wired to session_event table or in-memory turn context
    in a follow-up task."""
    return []
```
**影響**: Hebbianリンク機能が完全に無効化されている（`_create_hebbian_links` は呼ばれているが常に空リストでリンク生成されない）。
**対応**: `session_event` テーブルから直近ターンのアクセスメモリを問い合わせる実装を追加する。

### 2.4 `node_modules` がGit管理下

**問題**: `nous/api/http/static/node_modules/` が 63MB でコミットされている。
**対応**: `.gitignore` に `node_modules/` を追加、`git rm --cached` で追跡解除。CIビルドステップで `npm ci` を追加。

---

## 3. 🟡 アーキテクチャ債務

### 3.1 `Result[T, E]` 型のモナド連鎖不在

**ファイル**: `nous/domain/shared/result.py` (53行)

現在 `Success.map()` と `Failure.map()` のみ。以下のパターンがコードベース全体に氾濫:
```python
result = self._repo.find_by_key(key)
if not result.is_ok:
    return Failure(result.error)
if result.value is None:
    return Failure(MemoryNotFoundError(...))
return Success(result.value)
```

**提案**: `and_then` / `or_else` / `unwrap_or_raise` を追加し、ドメインサービス全体のネストを削減。
```python
# 追加すべきメソッド
def and_then(self, f: Callable[[T], Result[U, E]]) -> Result[U, E]: ...
def or_else(self, f: Callable[[E], Result[T, F]]) -> Result[T, F]: ...
```

### 3.2 `MemoryService` の責務過多

**ファイル**: `nous/domain/memory/service.py` (689行)

単一クラスが担当している責務:
- メモリ CRUD (create/read/update/delete)
- 重複検出 (セマンティック + テキスト)
- 自動タグ分類
- エンリッチメント (LLM呼出)
- Hebbianリンク生成
- メモリ進化 (A-MEM + HiMem矛盾分類)
- バイテンポラル無効化
- コアメモリブロック管理
- バージョン履歴
- 統計
- 検索ログ

**提案**: 
- `MemoryWriteService` — create/update/delete + 重複検出
- `MemoryEvolutionService` — 進化・矛盾検出・Hebbianリンク
- `MemoryBlockService` — コアメモリブロック
- `MemoryQueryService` — read/search/stats

### 3.3 `ChatConfig` の肥大化

**ファイル**: `nous/domain/chat_config.py` (602行)

50+フィールドのPydanticモデル。SQLシリアライズも内包。
**提案**: 設定をカテゴリ別に分割:
- `ProviderConfig` (LLM接続設定)
- `SessionConfig` (セッション管理設定)
- `CompressionConfig` (コンテキスト圧縮設定)
- `ToolConfig` (MCPツール設定)

### 3.4 `SQLiteRepository` 基底クラスの責務不足

**ファイル**: `nous/infrastructure/sqlite/base_repo.py` (28行)

現在は DB選択 (`_db_method`) のみ。しかし全リポジトリで繰り返されるパターン:
- `_row_to_entity()` 変換
- `_active_where()` フィルタ
- エラー→`RepositoryError` ラップ
- `_execute()` + `fetchall()` パターン

**提案**: 基底クラスに共通CRUDテンプレートメソッドパターンを抽出。
```python
class SQLiteRepository:
    def _execute_query(self, sql, params) -> list[sqlite3.Row]: ...
    def _execute_single(self, sql, params) -> sqlite3.Row | None: ...
    def _execute_write(self, sql, params) -> None: ...
```

### 3.5 プライベート属性の外部書き換え

`nous/application/use_cases.py:361-362`:
```python
memory_service._search_engine = ...  # 循環参照回避のための後付け注入
```
**提案**: `MemoryService` に `set_search_engine()` メソッドを追加し、公開API経由で注入。

---

## 4. 🟠 コード品質（大規模ファイル分解）

### 4.1 `session_store.py` (809行)

`SessionWindow` + `TreeNodeSessionWindow` + `SessionManager` が1ファイル。
**提案**: `session_window.py` + `tree_session.py` + `session_manager.py` に3分割。

### 4.2 `memory_repo.py` (776行)

CRUD + FTS全文検索 + キーワード検索 + バージョン管理 + ページネーション + ブロック + 強度 + 統計が1ファイル。
**提案**: 
- `memory_crud_repo.py` (find_by_key, save, update, tombstone, find_all, count)
- `memory_search_repo.py` (search_keyword, FTS)
- `memory_aux_repo.py` (versions, blocks, strength, pagination, stats, links)

### 4.3 `prepare.py` (748行)

パイプラインの準備ステップ。感情減衰、コンテキスト取得、記憶検索、チャンク作成が混在。
**提案**: ステップを分割:
- `emotion_decay.py` (感情減衰計算)
- `context_loader.py` (コンテキスト読み込み)
- `memory_retriever.py` (記憶検索・チャンク作成)

### 4.4 `compress.py` (425行)

LLMテキスト要約とメッセージ切り詰めの両方を担当。
**提案**: `summarizer.py` (LLM要約) + `trimmer.py` (メッセージ切り詰め) に分割。

### 4.5 `memory_llm.py` (487行)

プロンプト構築 + LLM呼出 + JSONパース + 結果適用が1ファイル。
**提案**: `memory_extractor.py` (抽出ロジック) + `memory_prompts.py` (プロンプト定義) に分割。

---

## 5. 🟡 CI/CD改善

### 5.1 現状

| チェック | CI (ci.yml) | 備考 |
|----------|:---:|------|
| ruff check | ✅ | |
| ruff format --check | ✅ | |
| pytest unit | ✅ | `tests/unit/` のみ |
| pytest integration | ❌ | 手動実行のみ |
| mypy type check | ❌ | 設定はあるがCI未実施 |
| coverage threshold | ❌ | 設定はあるがCI未実施 |
| bandit security | ❌ | dev依存にはあるがCI未実施 |
| docker build test | docker.yml | PRでは実行されない |

### 5.2 追加すべき項目

1. **`mypy nous/`** — 型チェックをCIに追加
2. **`pytest tests/integration/`** — 統合テストをCIに追加
3. **`pytest --cov=nous --cov-fail-under=70`** — カバレッジ下限強制
4. **`bandit -r nous/`** — セキュリティlint
5. **PRでのDocker buildテスト** — `docker build` のdry-run

### 5.3 Makefile不在

頻出コマンドの再入力が開発者負担。以下を推奨:
```makefile
.PHONY: lint test typecheck coverage ci

lint:
	ruff check . && ruff format --check .

test:
	pytest tests/unit/ -q

test-all:
	pytest -q

typecheck:
	mypy nous/

coverage:
	pytest --cov=nous --cov-report=term

ci: lint typecheck test-all coverage
```

---

## 6. 🟡 テスト改善

### 6.1 空ディレクトリ

| パス | 状態 |
|------|------|
| `tests/unit/api/http/routers/` | 空 — 削除 or ルーターUT作成 |
| `tests/unit/api/mcp/` | 空 — 削除 or MCPツールUT作成 |

### 6.2 不足テスト

| 対象 | 現状 | 推奨 |
|------|------|------|
| HTTPルーター | 統合テストのみ | UT追加 (ルーター単位) |
| MCPツール | 統合テスト + 一部UT | ツール単位UT追加 |
| EventBus | テストなし | pub/subの単体テスト |
| `ChatConfig` シリアライズ | テストあり | 十分 |
| パイプライン各ステップ | 部分的 | Compress/AutoCaptureのUT追加 |

### 6.3 契約テスト不在

MCPツールは外部LLMエージェントが主な消費者。ツール間の互換性テスト (Pact等) が不在。
**提案**: MCPツールの入出力スキーマをPactファイル化し、CIで破壊的変更を検出。

---

## 7. 🟢 クイックウィン（1時間以内で対応可能）

| # | 内容 | ファイル | 工数 |
|:--|------|------|:--:|
| 1 | `_compute_recency_decay` の `_` 化 + 未使用警告の抑制 | `prepare.py:78-80` | 5分 |
| 2 | `main.py:192` の重複 `_mount_static_files(mcp)` 削除 | `main.py:192` | 5分 |
| 3 | `.gitignore` に `node_modules/` 追加 | `.gitignore` | 2分 |
| 4 | `commit 5111bb6 "aa"` のrebase確認 | Git操作 | 10分 |
| 5 | `_get_session_memories` スタブに `TODO(blocked)` コメント追加 | `service.py:424` | 2分 |
| 6 | `use_cases.py` の `_search_engine` 直接代入を setter経由に | `use_cases.py:361` | 15分 |
| 7 | `memory_repo.py` の `noqa: S608` に説明コメント追加 | `memory_repo.py` | 15分 |
| 8 | Makefile追加 (lint/test/typecheck/ci) | ルート | 15分 |

---

## 8. 📋 優先度マトリクス

```
影響度 高
  │
  │  2.3 スタブ (#3)    │  2.1 タスクリーク (#1)
  │  5.2 CI改善 (#6)    │  2.2 SQL抑制濫用 (#2)
  │  3.2 責務過多(#5)   │  2.4 node_modules (#4)
  │  3.1 Result連鎖(#3) │
  ├────────────────────┼──────────────────
  │  7.x クイックウィン│  3.3~3.5 設計改善
  │  6.1 空ディレクトリ│  4.x ファイル分解
  │                    │  6.2 不足テスト
  │                    │  6.3 契約テスト
  └────────────────────┴──────────────────→ 工数 大

#1 = タスクリーク, #2 = SQL抑制, #3 = スタブ+Result, #4 = node_modules,
#5 = 責務分割, #6 = CI改善
```

---

## 9. 推奨実施順序

### フェーズ1: 安全基盤 (1~2日)
1. `asyncio.create_task()` のタスクリーク修正
2. CIに `mypy` + 統合テスト追加
3. Makefile導入
4. `.gitignore` に `node_modules` 追加

### フェーズ2: 設計改善 (3~5日)
5. `MemoryService` 責務分割
6. `Result[T,E]` に `and_then`/`or_else` 追加
7. `SQLiteRepository` 基底クラス強化

### フェーズ3: コード清掃 (2~4日)
8. 大規模ファイルの分解 (session_store, memory_repo, prepare)
9. 空ディレクトリ削除 + 不足UT追加
10. `_get_session_memories` スタブ実装

### フェーズ4: 発展 (1~3日)
11. MCPツールの契約テスト導入
12. `ChatConfig` 分割
13. カバレッジ下限のCI強制

---

## 10. ドキュメント同期要件

本リファクタリングの各フェーズ完了時に以下を更新すること (`AGENTS.md` ルールより):

| 変更種別 | 更新対象 |
|----------|---------|
| API/MCP ツール変更 | `docs/llm_usage_guide.md` |
| アーキテクチャ変更 | `docs/architecture.md` (存在すれば) |
| 設定変更 | `README.md` の環境変数セクション |
| コードのみ (内部リファクタ) | コミットメッセージに `[skip-docs]` |

---

*本指示書はコードベースの静的解析と探索結果に基づきます。実際の作業開始前に `nous/infrastructure/sqlite/memory_repo.py` の全 `# noqa` / `# nosec` 箇所と、全 `asyncio.create_task()` 呼出箇所の詳細確認（コードリーディング）を推奨します。*
