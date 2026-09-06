# REM アイドル駆動化・脳用LLM設定・モーダル統一 実装計画

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** enrichment トリガーをアイドル駆動ハイブリッド化し、脳シミュレーター用 LLM 設定 UI を追加し、メモリ詳細モーダルを Memories 版に統一し、確実リストの重複実装を解消する。

**Architecture:** 永続キュー（部分一意インデックスで dedupe）+ 既存 EnrichmentWorker スレッドをアイドルゲート付きドレイナーに変更。脳用 LLM は `_init_enricher` 一点で解決（OFF=チャット 4 点セット流用）。フロントは `openMemModalByKey` を共通経路にし、SSE/バー/日付を core コンポーネントへ集約。

**Tech Stack:** Python 3.12 / pydantic / SQLite (schema.py DDL) / pytest・vitest / vanilla JS (N.* namespace)

**Spec:** `docs/superpowers/specs/2026-09-06-rem-idle-and-modal-unification-design.md`（#081 レビュー反映済み。実装前に一読すること）

## Global Constraints

- emit 規約: wiring emit は try/except + `logger.debug`（`enrich_service.py` の replay_fire 前例に倣う）
- `Result` パターン: `nous/domain/shared/result.py`。失敗は黙殺しない（最低 debug ログ）
- **インスタンス属性で LLM usage/状態を共有禁止**（worker スレッドと background task の並行呼び出し）
- mypy 既存エラー（enrich_service.py:56,82 等）は本件スコープ外。**新規エラー 0** が条件
- UI トグル文言・見た目は #057 設計判断。機械的配線は #011
- テスト実行: `python -m pytest tests/unit/test_enrichment_worker.py` 等の絞り実行 → 全体は検証レーンで
- 契約テスト: `nous/api/http/static/chat/chat-settings-brain.test.js`（brain 設定 10 キーの契約。既存）

---

## Workstream A: バックエンド REM アイドル駆動化（#011、直列）

### Task A1: enrichment_queue テーブル + リポジトリ

**Files:**
- Modify: `nous/infrastructure/sqlite/schema.py`（DDL 追加。既存テーブル定義ブロックに追従）
- Create: `nous/infrastructure/sqlite/enrichment_queue_repo.py`
- Modify: `nous/infrastructure/sqlite/__init__.py`（エクスポート）
- Test: `tests/unit/test_enrichment_queue_repo.py`

**Interfaces:**
- Produces: `EnrichmentQueueRepository` with `enqueue(memory_key: str) -> None` / `pending_keys() -> list[PendingItem]`（`PendingItem = namedtuple("PendingItem", ["memory_key", "enqueued_at"])`） / `mark_processed(memory_key: str) -> None` / `has_processed(memory_key: str) -> bool`（defer 超過判定は worker 側が enqueued_at から行う。repo は判断しない）

**Steps:**
- [ ] **Step 1: 失敗テスト**（defer_exceeded の計算・INSERT OR IGNORE による dedupe・mark_processed 後は pending から消える・has_processed が True）

```python
def test_enqueue_dedupes_pending(tmp_path):
    repo = make_repo(tmp_path)  # 既存 sqlite テストの fixture パターンに倣う
    repo.enqueue("k1"); repo.enqueue("k1")
    assert len(repo.pending_keys()) == 1

def test_mark_processed_allows_reenqueue(tmp_path):
    repo = make_repo(tmp_path)
    repo.enqueue("k1"); repo.mark_processed("k1")
    assert repo.has_processed("k1")
    assert repo.pending_keys() == []
    repo.enqueue("k1")  # processed 行があっても pending 行は作れる
    assert len(repo.pending_keys()) == 1
```

- [ ] **Step 2: 実行して FAIL** — `python -m pytest tests/unit/test_enrichment_queue_repo.py -v`
- [ ] **Step 3: DDL** — `schema.py` に追加:

```sql
CREATE TABLE IF NOT EXISTS enrichment_queue (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  memory_key TEXT NOT NULL,
  enqueued_at TEXT NOT NULL,
  processed_at TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_enrichment_queue_pending
  ON enrichment_queue(memory_key) WHERE processed_at IS NULL;
CREATE INDEX IF NOT EXISTS ix_enrichment_queue_key
  ON enrichment_queue(memory_key);
```

- [ ] **Step 4: リポジトリ実装** — `pending_keys()` は `SELECT DISTINCT memory_key, MIN(enqueued_at) FROM enrichment_queue WHERE processed_at IS NULL GROUP BY memory_key`。`defer_exceeded` は `min_batch_size` と独立に、呼び出し側（worker）が enqueued_at から判定するため repo は生の enqueued_at を返すだけでよい（namedtuple から defer_exceeded を外す＝判定は worker 側）
- [ ] **Step 5: PASS 確認 → commit** `feat(brain): enrichment_queue table with pending dedupe`

### Task A2: enqueue 配線（create 即時廃止 + read/search）

**Files:**
- Modify: `nous/domain/memory/service.py:204-213`（create の即時 `_enrich_service.enrich_memory` バックグラウンドタスクを削除 → `ctx.enrichment_queue.enqueue(m.key)`。MemoryService がキューを持たない場合は `ctx` 経由の注入を AppContext 側で行う——`use_cases.py` の MemoryService 生成箇所を確認し、コンストラクタ引数に `enrichment_queue_repo` を追加するのが正）
- Modify: `nous/api/mcp/_tools_memory.py` — `_tool_memory_read`（:111 付近）: 既存 boost_recall + record_memory_access は維持、ヒットに対して「`has_processed == False` なら enqueue」。`_tool_memory_search`（:325-427）: **ヒット先頭 `min(10, len)` 件に boost_recall**（現状 search は boost 無し→追加）、**record_memory_access は上位 `min(3, len)` 件のみ**、未 enrich の memory を enqueue
- Test: `tests/unit/test_tool_called_invariant.py`（search の co-access 窓不変条件を追加: top_k=200 の search 後 `_coaccess_keys` は 3 件しか増えない）、`tests/unit/test_memory_service.py`（create が即時 enrich を呼ばないこと）

**Interfaces:**
- Consumes: Task A1 の `EnrichmentQueueRepository`
- Produces: create/read/search がすべて enqueue する状態。**即時 enrich は無くなる**

- [ ] Step 1: 失敗テスト（search 窓不変条件 + create 非即時化）
- [ ] Step 2: FAIL 確認
- [ ] Step 3: 実装。search での boost/record は**ヒット 0 件の早期 return（:379-393）より後に**置く
- [ ] Step 4: PASS → commit `refactor(brain): route enrichment via persistent queue`

### Task A3: EnrichmentWorker アイドルゲート + キュードレイン

**Files:**
- Modify: `nous/application/workers/enrichment_worker.py`（カーソル機構 `_memories_since_cursor`/`_advance_cursor` は廃止しキュードレインへ。novelty ゲート `_novelty_gate`（:139-210）と `_enrich_batch`（:216-235）は維持）
- Modify: `nous/domain/session_config.py:95-104`（brain_* に `brain_idle_after_seconds: int = 120` / `brain_min_batch_size: int = 3` / `brain_max_defer_seconds: int = 3600` を追加。ChatConfig フラット分配は自動追随 `chat_config.py:175-186`）
- Test: `tests/unit/test_enrichment_worker.py`（既存をキュードレイン前提に書き直し + 新規: アイドルゲート・最小バッチ・強制ドレイン・repo None フォールバック）

**Interfaces:**
- Consumes: A1 repo, `ctx.session_event_repo`（None になり得る: `use_cases.py:239`）
- Produces: `_run_cycle()` の新契約:

```python
def _run_cycle(self):
    now = self._now()
    pending = self._queue.pending_keys()          # [(memory_key, enqueued_at)]
    defer_exceeded = any(
        (now - enq).total_seconds() >= self._num("brain_max_defer_seconds", 3600)
        for enq in [p.enqueued_at for p in pending]
    )
    if not defer_exceeded:
        idle = self._seconds_since_last_activity(now)
        if idle is None:            # session_event_repo なし → アイドル未達扱い
            return
        if idle < self._num("brain_idle_after_seconds", 120):
            return
        if len(pending) < self._num("brain_min_batch_size", 3):
            return
    # drain: DISTINCT keys、has_processed で再 enrich 防止、処理完了後に mark_processed
    for item in pending:
        if self._queue.has_processed(item.memory_key):
            self._queue.mark_processed(item.memory_key); continue
        self._enrich_one(item.memory_key)   # novelty gate → enrich_batch 流用
        self._queue.mark_processed(item.memory_key)
```

`_seconds_since_last_activity`: `SELECT MAX(timestamp) FROM session_events WHERE persona = ?`（`session_event_repo` の既存クエリメソッド追加か、生 SQL は repo 側に足す。persona は `self._persona`）。失敗/例外時は None（アイドル未達）。

- [ ] Step 1: 失敗テスト（アイドル中のみドレイン / min_batch 未満で待機 / max_defer 超過で強制 / event_repo None で skip except defer / processed 済み再 enrich しない）
- [ ] Step 2: FAIL
- [ ] Step 3: 実装（上記契約どおり。タイムゾーンは既存 `_naive`（:134-136）に倣う）
- [ ] Step 4: PASS → commit `feat(brain): idle-gated queue drain in EnrichmentWorker`

### Task A4: usage 収集 + enrich 失敗ログ

**Files:**
- Modify: `nous/infrastructure/llm/memory_enricher.py:124-147` — `_call_llm` を `(text, usage)` 返しに変更（`DoneEvent.usage`、base.py:57 の dict|None）。`enrich_async` → `EnrichmentResult`（dataclass、既存返り値型）に `usage: dict | None` 追加。**インスタンス属性禁止**
- Modify: `nous/domain/memory/enrich_service.py:45-46` — `contextlib.suppress` 内で `logger.debug("enrich failed: %s", exc)`。usage を INFO ログ + `replay_fire` emit meta に含める（`enrich_service.py:94-116`）
- Test: `tests/unit/test_enrichment_worker.py` または新規 `test_memory_enricher_usage.py`（usage が result に載る・失敗時に debug ログが出る）

- [ ] Step 1: 失敗テスト → Step 2: FAIL → Step 3: 実装 → Step 4: PASS → commit `feat(brain): collect enrichment token usage`

---

## Workstream B: 脳シミュレーター用 LLM 設定（#011 → #057）

### Task B1: brain_llm_* キー + 解決鎖 + 再解決フック

**Files:**
- Modify: `nous/domain/session_config.py:95-104` — `brain_llm_dedicated: bool = false`, `brain_llm_provider: str = ""`, `brain_llm_model: str = ""`, `brain_llm_base_url: str = ""`, `brain_llm_api_key: str = ""`
- Modify: `nous/application/use_cases.py:185-217` `_init_enricher` — 解決鎖（仕様 §4.2）:

```python
if cfg is None:                      # ChatConfig 無し: 現行 settings.memory_enrichment 鎖を維持
    ...
elif not session.brain_llm_dedicated:   # OFF: チャット 4 点セット
    p = cfg.provider_config
    provider, model = p.provider, p.get_effective_model()
    base_url, api_key = p.get_effective_base_url(), p.get_effective_api_key()
else:                                 # ON: brain_llm_* + 既存フォールバック鎖
    ...
    # チャットキー最終フォールバックは provider 一致時のみ。異種なら enricher=None + logger.debug
```

- Modify: 再解決フック — `chat/chat_management.py` の config 保存ルートから ctx の `_init_enricher` 再実行（メソッド `ctx.reload_enricher()` を AppContext に生やす）
- Test: `tests/unit/test_brain_llm_resolution.py`（新規: ON/OFF × cfg None/あり × provider 一致/不一致 × 空フィールドフォールバック、reload_enricher で enricher が差し替わる）

- [ ] Step 1: 失敗テスト → Step 2: FAIL → Step 3: 実装 → Step 4: PASS → commit `feat(brain): brain_llm_dedicated toggle with chat-config fallback chain`

### Task B2: WebUI 設定セクション（#057 主導、#011 配線）

**Files:**
- Modify: `nous/api/http/sections/chat/chat_sidebar_memory.py:159-232`（`_render_brain_simulation_section`）— トグルスイッチ「脳シミュレーター専用 LLM を使う」＋ ON 時のみ表示される provider/model/base_url/API キー項目（OFF=デフォルト、非表示）
- Modify: `nous/api/http/static/chat/chat-settings.js` — load（:314-329）に 5 キー追加、save（:472-484）に collect 追加。トグルの change で詳細フィールドの hidden 切替（CSP-safe: inline onclick 禁止、delegation.js パターン）
- Modify: `nous/api/http/static/core/delegation.js` — `data-action="brain-llm-toggle"` ケース追加
- Test: `nous/api/http/static/chat/chat-settings-brain.test.js`（契約拡張: 5 キー round-trip、トグル OFF で dedicated 以外を送らない）

- [ ] Step 1: #057 に設計委譲（ラベル文言・トグル見た目・配置。既存 brain セクションの美観に合わせる）
- [ ] Step 2: #011 が load/save/切替配線 + 契約テスト
- [ ] Step 3: vitest PASS → commit `feat(webui): brain simulator dedicated LLM settings`

---

## Workstream C: メモリ詳細モーダル統一（#057 主導）

### Task C0: openMemModalByKey の共通化

**Files:**
- Modify: `nous/api/http/static/features/memories/memories-edit.js:17-28,33-148` — `openMemModalByKey` / `openMemModal` を `N.Components.memModal.open(key)` として `nous/api/http/static/components/mem-modal.js`（新規）に抽出。memories-edit.js は薄ラッパーに（既存呼び出しを壊さない）
- `#mem-modal-overlay` DOM は `sections/base.py:191-192` サーバー生成のまま維持

### Task C1: Timeline → mem modal

**Files:** Modify `nous/api/http/static/features/timeline.js:161-207` — `showTimelineDetail` を `N.Components.memModal.open(key)` 呼び出しに置換。`#tl-detail-panel` / 手書き body bars（:174-195）/ `closeTimelineDetail` を削除。`select` イベント（:138-144）のみ流用。タイムライン項目に key がない場合は API レスポンス確認（`routers/memory.py` timeline エンドポイント）で key を取る

### Task C2: Graph メモリノード → mem modal

**Files:** Modify `nous/api/http/static/features/graph.js:437-530` — memory ノード select 分岐を `N.Components.memModal.open(key)` に。graph 側 memory 表示ブランチと手書き importance バー（:509-520、safeSetHTML で style が消える潜在バグ）を削除。**entity ブランチ（`openGraphDetailPanel` の entity 側）はサイドパネル維持**

### Task C3: Chat wiring 詳細の整理

**Files:** Modify `nous/api/http/static/chat/chat-memory-panel.js:883-1019` —
- エッジ詳細モーダル（`_wiringDetailHTML`）は存続（Edge/weight/kind 表示は別機能）だが、importance バー・タグ・日付を共通実装に置換
- 行から `data-action="wiring-open-memory"`（memory_key）で `N.Components.memModal.open` を開く導線を追加
- `_wiringEscAttr`（:360-367）削除 → `N.Core.esc`。自前 document 委譲（:997-1019）を `core/delegation.js` に移設

**検証:** 実ブラウザ（Playwright MCP）で Memories/Chat/Graph/Timeline 全タブのメモリ詳細表示を確認。networkidle 待ち禁止。

---

## Workstream D: 重複実装解消フェーズ1（#011、C3 以降に実施）

- [ ] **D1: SSE 統合** — `chat-memory-panel.js:728-810` `connectWiring` と `features/graph.js:114-135` `connectGraphFlash` を `core/sse.js` `connectSSE` に統合。`core/sse.js` に複数ストリーム同時管理が必要ならハンドル返し方式に拡張。graph 版は backoff 再接続を core に合わせる。vitest で接続/再接続/disconnect を確認 → commit `refactor(webui): unify SSE connection management`
- [ ] **D2: 日付集約** — `core/time.js` に `fmtDateTime`（完全日時バリアント）追加。置換対象: `timeline.js:169`（C1 で消える可能性大）、`activity.js:173,213`、`memories-edit.js:110,115,120`、`chat-memory-panel.js:931,935` → commit `refactor(webui): consolidate date formatting`
- [ ] **D3: モーダル開閉のクラス方式統一** — `overview-inventory.js:23-76` / `overview-core.js:198-240` / `base.js:543-580`（persona モーダル JS 自作 DOM）を `ov-modal-overlay` + クラストグルへ。**#057 に配置・見た目の確認を依頼してからマージ** → commit `refactor(webui): unify modal open/close pattern`
- [ ] **D4: mem-modal ID/クラス整理** — `memories-edit.js:34-54` の `#mem-modal-content` と `.mem-modal-content` ネストを別名（例: `.mem-modal-body`）に → commit `refactor(webui): disambiguate mem modal content names`

---

## 検証レーン（全タスク完了後）

- [ ] `python -m pytest` 全体（失敗 0）＋ `ruff check` 0 ＋ `ruff format --check` ＋ mypy 新規 0
- [ ] `npx vitest run` 全パス
- [ ] 実ブラウザ検証（Playwright MCP）:
  1. 脳シミュレーション設定: トグル OFF で LLM 項目非表示 / ON で表示・保存・再読込で反映 / **保存後 `reload_enricher` で即時反映**（トグル切替→ enricher 生成ログで確認）
  2. 全タブのメモリ詳細: Memories/Graph/Timeline/Chat wiring が同一モーダルで開く
  3. wiring SSE 接続: readyState 1、Graph フラッシュ動作
  4. 記憶作成 → アイドル 2 分後に enrichment 実行（ログ確認）
- [ ] coverage ≥ 60%（全体）確認

## 実行順序と並列性

1. A1 → A2 → A3 → A4（直列: 依存チェーン）
2. B1（A と並行可）→ B2（B1 完了後）
3. C0 → C1/C2/C3（バックエンドと並行可。C3 完了後 D1-D4）
4. 検証レーン → #081 REVIEW（REVIEW フェーズ）→ GATE → COMMIT/RECORD
