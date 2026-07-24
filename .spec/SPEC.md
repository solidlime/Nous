# SPEC — Phase 1: 安全基盤リファクタリング

## 出典
`refactor-instructions.md` 第2章・第5章・第7章に基づく

---

## SPEC-1: クイックウィン（8項目・約1時間）

### 1.1 `_compute_recency_decay` の未使用警告抑制
**対象**: `nous/application/chat/pipeline/prepare.py:78-80`
**内容**: 関数名を `_compute_recency_decay` に変更（プライベート化）。呼び出し元も更新。

### 1.2 `main.py:192` の重複 `_mount_static_files(mcp)` 削除
**対象**: `nous/main.py`
**内容**: 2回目の `_mount_static_files(mcp)` 呼び出しが重複。削除する。

### 1.3 `.gitignore` に `node_modules/` 追加
**対象**: `.gitignore`
**内容**: `node_modules/` を追加し、`git rm --cached -r nous/api/http/static/node_modules/` で追跡解除。

### 1.4 `commit 5111bb6 "aa"` のrebase確認
**対象**: Git操作
**内容**: `git log --oneline` で確認。必要ならrebase。

### 1.5 `_get_session_memories` スタブに `TODO(blocked)` コメント追加
**対象**: `nous/domain/memory/service.py:424-431`
**内容**: ドキュメンテーション文字列に `TODO(blocked): session_eventテーブル実装待ち` を追記。

### 1.6 `use_cases.py` の `_search_engine` 直接代入をsetter経由に
**対象**: `nous/application/use_cases.py:361-362`
**内容**: `memory_service._search_engine = ...` → `memory_service.set_search_engine(...)` に変更。`MemoryService` に `set_search_engine()` メソッドを追加。

### 1.7 `memory_repo.py` の `noqa: S608` に説明コメント追加
**対象**: `nous/infrastructure/sqlite/memory_repo.py`
**内容**: 全 `# noqa: S608 # nosec B608` に「文字列連結だが全変数はプレースホルダ経由で保護済み」の説明を追加。

### 1.8 Makefile追加
**対象**: `Makefile` (プロジェクトルート)
**内容**:
```makefile
.PHONY: lint test test-all typecheck coverage ci

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

## SPEC-2: `asyncio.create_task()` タスクリーク修正（クリティカル）

**リスク**: 未捕捉例外がタスク消滅。メモリ進化・矛盾検出がサイレント失敗。

| # | ファイル:行 | 内容 |
|---|-----------|------|
| 2.1 | `nous/domain/memory/service.py:245` | `create_task(_evolve_related_memories(...))` |
| 2.2 | `nous/domain/memory/service.py:255` | `create_task(_invalidate_contradicted_memory(...))` |
| 2.3 | `nous/application/chat/pipeline/post.py:119` | `create_task(...)` |
| 2.4 | `nous/application/chat/pipeline/prepare.py:695,702` | 一部保持・一部未保持 |

**対応方針**: 戻り値をリストで保持し、`add_done_callback` で例外ログ。または `asyncio.TaskGroup`（Python 3.11+）に移行。

---

## SPEC-3: CI改善

| # | 内容 |
|---|------|
| 3.1 | `mypy nous/` を CI (ci.yml) に追加 |
| 3.2 | `pytest tests/integration/` を CI に追加 |
| 3.3 | カバレッジ下限強制 `--cov=nous --cov-fail-under=70` はフェーズ4に延期（現状のカバレッジ状況を先に確認）|
| 3.4 | `bandit -r nous/` は多数の既存 `# nosec` があるためフェーズ4に延期 |

---

## SPEC-4: `.gitignore` + `node_modules` 追跡解除

**内容**: SPEC-1.3 と重複。`node_modules/` を `.gitignore` に追加 + `git rm --cached` でGit追跡から外す。
**参考**: `refactor-instructions.md` 2.4節「node_modules がGit管理下 (63MB)」

---

## 検証要件

| # | 検証項目 | 方法 |
|---|---------|------|
| V1 | Python単体テスト | `pytest tests/unit/ -q --timeout=60` |
| V2 | lint | `ruff check nous/ tests/` |
| V3 | 型チェック | `mypy nous/`（初回は警告多数を許容） |
| V4 | サーバー起動 | `curl -f http://localhost:26262/health` |
| V5 | CI設定の構文 | `act` または GitHub Actions UI 確認 |
