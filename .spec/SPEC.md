# SPEC — Phase 2: 設計改善

## 出典
`refactor-instructions.md` 第3章「アーキテクチャ債務」

---

## SPEC-2.1: `Result[T, E]` にモナド連鎖メソッド追加

**現状**: `Success.map()` と `Failure.map()` のみ。全ドメインサービスで以下のボイラープレートが氾濫:
```python
result = self._repo.find_by_key(key)
if not result.is_ok:
    return Failure(result.error)
if result.value is None:
    return Failure(MemoryNotFoundError(...))
return Success(result.value)
```

**追加メソッド** (`nous/domain/shared/result.py`):
```python
# Success
def and_then(self, f: Callable[[T], Result[U, E]]) -> Result[U, E]:
    """Chain another Result-returning operation."""
    return f(self.value)

def or_else(self, f: Callable[[E], Result[T, F]]) -> Result[T, F]:
    return self  # Success なのでスキップ

# Failure
def and_then(self, f: Callable) -> Failure[E]:
    return self  # Failure なのでスキップ

def or_else(self, f: Callable[[E], Result[T, F]]) -> Result[T, F]:
    """Recover from error with fallback operation."""
    return f(self.error)
```

**影響範囲**: 既存の `map` 呼び出しのみで、破壊的変更なし。新メソッドは純粋な追加。

---

## SPEC-2.2: `SQLiteRepository` 基底クラス強化

**現状** (28行): `_db_method` と `_db` プロパティのみ。

**追加するテンプレートメソッド**:
```python
def _execute_query(self, sql: str, params: tuple = ()) -> list[sqlite3.Row]:
    """Execute SELECT and return all rows."""

def _execute_single(self, sql: str, params: tuple = ()) -> sqlite3.Row | None:
    """Execute SELECT and return first row or None."""

def _execute_write(self, sql: str, params: tuple = ()) -> None:
    """Execute INSERT/UPDATE/DELETE."""
```

**利用方法**: 各リポジトリの `self._db.execute(sql, params).fetchall()` → `self._execute_query(sql, params)` に置換。エラーハンドリングを基底クラスに一元化。

---

## SPEC-2.3: `MemoryService` 責務分割（最重要）【#081 レビュー済】

**現状** (`nous/domain/memory/service.py`, 716行): 単一クラスが10+責務を担当。

### 分割方針: **5-service Facade パターン**

`MemoryService` を公開APIのファサードとして維持し、内部で5つのサブサービスに委譲する。
**`create_memory` は Facade に残す** — 書込・エンリッチメント・リンク生成・進化の3関心をオーケストレーションするハブのため。
各サブサービスは互いを知らず、Facade だけが全サブサービスを知る一方向依存。

### サブサービス構成

| 新クラス | ファイル | 責務 | 元のメソッド |
|---------|---------|------|------------|
| `MemoryWriteService` | `write_service.py` | 重複検出, バリデーション, repo.save | `_check_duplicate`, `_validate_tags`, `_build_memory_entity` |
| `MemoryEnrichService` | `enrich_service.py` | エンリッチメント, Sudachi抽出 | `create_memory` L204-240 の抽出（`_enrich_memory` として新規メソッド化） |
| `MemoryLinkService` | `link_service.py` | Hebbianリンク生成 | `_create_hebbian_links`, `_classify_link_type`, `_get_session_memories` |
| `MemoryEvolutionService` | `evolution_service.py` | 進化, 矛盾検出, 背景実行 | `_evolve_related_memories`, `_invalidate_contradicted_memory`, `_run_background_evolution` |
| `MemoryQueryService` | `query_service.py` | 読取, 統計 | `get_memory`, `get_memory_stats`, `get_recent`, `boost_recall`, `get_by_tags`, `get_memory_index`, `get_version_history` |

### MemoryService ファサードの責務（分割後）
- **`create_memory`** — 全体オーケストレーション（WriteService → EnrichService → LinkService → EvolutionService(background)）
- `save_memory`（単純なリポジトリラッパー）
- `update_memory`, `tombstone_memory`（バージョニング一貫性のため Facade に残す）
- ブロック管理（`MemoryBlockService` は次のフェーズで）
- `set_search_engine`（注入ポイント、全サブサービスに伝播）

### ファイル構成（分割後）
```
nous/domain/memory/
├── service.py            # MemoryService（ファサード、〜300行に縮小）
├── write_service.py      # MemoryWriteService（〜80行）
├── enrich_service.py     # MemoryEnrichService（〜50行）
├── link_service.py       # MemoryLinkService（〜100行）
├── evolution_service.py  # MemoryEvolutionService（〜200行）
├── query_service.py      # MemoryQueryService（〜150行）
├── entities.py           # 既存
├── repository.py         # 既存
├── ...                   # 既存
```

### 非破壊的移行
1. `_enrich_memory` メソッドを新規作成（create_memory L204-240 の抽出）
2. 各サブサービスファイルを新規作成し、該当メソッドを移動
3. `MemoryService.__init__` でサブサービスをインスタンス化、依存注入
4. Facade は委譲を維持。`_repo` は Facade に残す（テスト互換性）
5. 全呼び出し元は変更不要

### #081 レビューで指摘されたリスクと対策
- **`_enrich_memory` が存在しない**: → 新規メソッド化してから EnrichService に移動
- **WriteService→EvolutionService 結合**: → Facade が両方を指揮することで回避
- **`_get_session_memories` は LinkService に**: → QueryService には移さない
- **`_repo` 直接アクセスするテスト**: → Facade に `_repo` を残し互換性維持

---

## 検証要件

| # | 検証項目 | 方法 |
|---|---------|------|
| V1 | Python単体テスト | `pytest tests/unit/ -q --timeout=60`（メモリ許容時） |
| V2 | importチェーン | `python3 -c "from nous.domain.memory.service import MemoryService"` |
| V3 | lint | `ruff check nous/domain/memory/` |
| V4 | 呼び出し元破壊なし | `grep -r "memory_service\." nous/ --include="*.py"` で既存API維持確認 |
