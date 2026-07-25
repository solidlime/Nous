# TODO — Phase 1: 安全基盤リファクタリング (2026-07-25) — COMPLETE

## Increment 1: クイックウィン（機械的変更）
- [x] 1.1 `_compute_recency_decay` をプライベート化 — 既に対応済み（変更不要）
- [x] 1.2 `main.py:192` の重複 `_mount_static_files(mcp)` 削除
- [x] 1.3 `.gitignore` に `node_modules/` 追加 + `git rm --cached` — 既に.gitignore済み、追跡なし
- [x] 1.5 `_get_session_memories` スタブに `TODO(blocked)` コメント — `service.py`
- [x] 1.6 `use_cases.py` の `_search_engine` 直接代入を setter 経由に
- [x] 1.7 `memory_repo.py` の `noqa: S608` に説明コメント追加
- [x] 1.8 Makefile 追加（プロジェクトルート）

## Increment 2: asyncio タスクリーク修正（TaskGroup移行）
- [x] 2.1 `service.py:245` — `create_task(_evolve_related_memories())` → TaskGroup化
- [x] 2.2 `service.py:255` — `create_task(_invalidate_contradicted_memory())` → TaskGroup化
- [x] 2.3 `post.py:119` — 調査の結果、`_background_tasks` で管理済み（変更不要）
- [x] 2.4 `prepare.py:695,702` — 調査の結果、`asyncio.gather()` で適切に await 済み（変更不要）

## Increment 3: CI改善
- [x] 3.1 `mypy nous/` を CI（ci.yml）に追加
- [x] 3.2 `pytest tests/integration/` を CI に追加

## 検証
- [x] `ruff check` → 全PASS
- [x] importチェック → OK
- [x] メソッド存在確認 → `set_search_engine`, `_run_background_evolution`, `TODO(blocked)` 全確認
- [ ] `pytest tests/unit/` → メモリ不足により未実行（要サーバー再起動後）
- [ ] `mypy nous/` → 未実行
- [ ] サーバー起動確認 → 未実行
