# kanban #54 仕様: 記憶ライフサイクル一本化（Zero Inbox化）

方針（ユーザー決定）: 生記憶は「未整理の受信トレイ」。**Wiki に編纂されたら元の記憶はその場で物理削除**。Wiki ページが正本。

前提: `nous/` のコードを直接編集する。下の 7 ファイル以外は触らない。

---

## 1. `nous/infrastructure/sqlite/memory_crud_repo.py`

`delete()` の下に追加:

```python
_KEY_BATCH = 500  # SQLite の変数上限に収まるチャンク幅

def delete_many(self, keys: list[str]) -> Result[int, RepositoryError]:
    """物理削除（不可逆）。memories と、それを参照する行を全部消す。

    memories_fts は memories_ad トリガが消すので明示削除しない。
    途中で失敗したら rollback して 0 件として返す（半端な削除を残さない）。
    """
```
- 1 チャンク = 1 トランザクション（`BEGIN IMMEDIATE` / `commit` / 失敗時 `rollback`）。
- 各チャンクで `DELETE FROM memory_strength WHERE memory_key IN (...)`,
  `memory_entities`（`memory_key`）, `memory_versions`（`memory_key`）,
  `memory_links`（`source_key IN (...) OR target_key IN (...)`）, `memories`（`key`）の順に削除。
  IN 句は `?` プレースホルダ。
- 戻り値は削除した `memories` 行数（`Success(n)`）。

同じ場所に追加:

```python
def find_obsolete_keys(self) -> Result[list[str], RepositoryError]:
    """Wiki が吸収済み / decay が退けた記憶のキー。

    archived と tombstoned と consolidated（旧 gist）が対象。Zero Inbox では
    これらは物理削除して良い（Wiki と日記が本文を保持している前提）。
    """
```

## 2. `nous/application/wiki/vector_index.py`

`drop_page` の下に追加: `async_drop_memories(settings, persona, keys: list[str]) -> None` と同期ラッパ
`drop_memories(settings, persona, keys)`。
- collection prefix は `""`（記憶のベクトル）、`store = use_cases.QdrantVectorStore(mgr, _embedding(settings), "")`。
- `store.delete(persona, key)` をキーごとに呼ぶ。例外は warning に落とす（索引はミラー）。

## 3. `nous/application/workers/wiki_worker.py`

### 3.1 `_archive_sources` → `_delete_sources`
シグネチャ: `_delete_sources(self, ctx, persona: str, sources: Iterable[str], seen: set[str]) -> int`
- `seen` にあるキーは飛ばす（cycle 内の二重計上防止）。
- `ctx.memory_repo.delete_many(keys)`。`Success` なら `seen.update(keys)` して件数を返す。
- `self.vector_enabled` なら `vector_index.drop_memories(self._settings, persona, keys)`。
- 失敗は `logger.warning` で握り、そのキーは `seen` に入れない（次サイクルで再挑戦）。

### 3.2 `_apply_page`
- `write_page` 成功後に `_delete_sources` を呼ぶ（ページ本文がディスクに載ってから消す）。
- 監査 detail のキー `archived` → `deleted`。
- 既存ページの sources は**生きている候補に限らず**引き継ぐ:
  `sources = list(dict.fromkeys([*sources, *existing.value.sources]))`, 超過分は
  `max_sources_per_page` で切る（消えた記憶のキーは「そのページを支えた履歴」）。

### 3.3 `_select_topics`
- `_stale_topics` の呼び出しと `stale` 変数を削除。並び順:
  `topics.sort(key=lambda item: (last_compiled.get(item[0], ""), -len(item[1])))`。
- `_stale_topics` メソッドは削除。

### 3.4 `_compile_persona`
- 冒頭で `purged = self._purge_obsolete(ctx, persona)` を実行し、`purged` 件を
  `wiki.compiled` の detail `{"purged": n}` として記録（0 件ならイベントを出さない）。
- `find_all()` は purge の**後**に実行する。
- 日記 → トピックの順は現状維持。最後に日記の sources を `_delete_sources` で消す。

### 3.5 新規 `_purge_obsolete(self, ctx, persona: str) -> int`
- `ctx.memory_repo.find_obsolete_keys()` → `delete_many(keys)` → `vector_index.drop_memories(...)`。
- 失败時は `logger.warning` して 0 を返す。

### 3.6 `_compile_journal`
- 戻り値を `list[str]`（このサイクルで日記に取り込んだ sources）に変更。対象外なら `[]`。
- **既存ページがあり、その日の記憶が 0 件なら書かない**: `if existed and not memories: return []`
  （2 回目のサイクルで痩せた日記に上書きしないため）。
- 書き込み後の `_apply_journal_state` はそのまま。

### 3.7 `_topic_memories` の単純化
- body を `return _by_recency(memories)[: self._cfg.max_memories_per_topic]` の 1 行に。
- 引数 `pages` と `all_by_key` は呼び出し元ごと削除（`_compile_topic` の引数 `all_by_key` も不要に）。
- 未使用になる `_recall_by_text`, `_order_by_page_text`, `_page_is_behind`, `_STALE_SLACK` を削除。

### 3.8 `_build_prompt`
- 編纂対象 topic のページは**本文を切らずに**渡す: `{"body": p.body}`（`page_body_chars` 廃止）。
  記憶を物理削除するので、切り捨てた本文より後ろの事実は復元できなくなる。

## 4. `nous/config/settings.py`
- `ConsolidationConfig` に `enabled: bool = Field(default=False, description="...")` を追加。
- `WikiConfig` から `archive_sources`, `page_body_chars`, `revision_source_memories`,
  `revision_recall_memories`, `orphan_archive_memories` を削除（コメントごと）。

## 5. `nous/main.py`
- `ConsolidationWorker` の起動を `if settings.consolidation.enabled:` で囲み、
  無効時は `logger.info("ConsolidationWorker disabled (Zero Inbox)")`。

## 6. `pyproject.toml`
- `dependencies` から `PyMuPDF`, `pdfplumber`, `pytesseract`, `aiosqlite` を削除。
- `[project.optional-dependencies]` の `ocr` グループを削除。`contract` は残す。
- Pillow / packaging を足さない（直接 import していない）。

## 7. テスト
- `tests/unit/test_wiki_worker.py`:
  - `test_compile_archives_sources` → `test_compile_deletes_sources`（編纂後 `find_by_key` が空、
    detail の `deleted` が 2）。
  - `archive_sources=False` のテストは削除（設定ごと廃止）。
  - `test_stale_topic_is_prioritized` / `test_archived_source_does_not_make_topic_stale` /
    `test_missing_or_tombstoned_source_is_stale` / `test_stale_topics_ignores_journal` は削除。
  - `test_topic_with_page_survives_archive_below_min_memories` は
    「ページのある topic は active 1 件でも巡回対象」のまま残す（lifecycle 変更は削除でも可）。
  - 二重計上テスト（`sum(d.get("archived", 0)) == 1`）→ `deleted` に読み替え。
  - 追加: 既存ジャーナルがある状態で記憶 0 件の 2 回目サイクルがページを上書きしないこと。
  - 追加: `archived` / `tombstoned` / `consolidated` の記憶が cycle 冒頭で物理削除され、
    `find_all()` に残らないこと。
- `tests/unit/test_sqlite_repos.py`: `delete_many` が `memories` / `memory_strength` /
  `memory_links`（両方向）から消し、戻り値が行数であること。`find_obsolete_keys` の 3 種。

## 完了条件
`pytest tests/unit` 全緑、`ruff check` + `ruff format --check` clean、
`mypy nous/ | mypy_baseline filter` が `new: 0`。
