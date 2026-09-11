# 内省衛生と抽出LLM分割 実装計画

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 内省バグ（対話時刻汚染・2h発火・ツールコール非表示）を根絶し、抽出LLMを context/item に2分割し、内省プロンプトを設定可能にする。

**Architecture:** A（汚染根絶: resolver/record/allowlist/last_activity/失敗時クロック）を土台に、B（spontaneous クロック分離+1h化）、C（tool.called publish+要約永続化+フロント）、D（プロンプト設定化）、F（抽出LLM 2分割+除外ルール）、G（リサーチ継続性修復）、H（デフォルト値）を順に載せる。introspection.py がホットファイルのため Task 順序で衝突を回避する。

**Tech Stack:** Python 3.12 / pydantic / SQLite / vanilla JS (vitest) / pytest

**Spec:** `docs/superpowers/specs/2026-09-12-introspection-hygiene-and-extractor-split-design.md`

## Global Constraints

- Windows/pwsh。テストは `.venv\Scripts\python -m pytest <path> -q`（`scripts/run-tests.sh` は systemd-run 前提で Windows 不可）
- lint: `.venv\Scripts\python -m ruff check .`（0件必達）。mypy: 既存 baseline（新規エラー禁止・nosec を付けるなら根拠コメント必須）
- 禁止操作: `git push --force` / `git commit --no-verify`
- コミット: conventional prefixes（fix:/feat:/test:/docs: 等・日本語サブジェクト可）
- フル unit suite 基準: 2258+ passed（回帰ゲート）
- 検証用の設定変更は `POST /api/chat/{persona}/config` で行う（config.json 直編集は UI 保存で上書きされる）
- E（欲スロット）は**実装しない**（ユーザー決定: 中断）
- D: 一人称遵守ブロックは注入しない（ユーザー決定「プロンプト入ってれば十分」）
- F: 抽出LLMは**逐次実行**（並列化しない）。命名は `item_llm_*`。context 側は既存 `extract_model` 流用
- G: リサーチの絞り込みループは**導入しない**（持ち越しは1質問/周期まで）
- H: LLM 呼び出し周期のみ 1h。emotion/body 半減期・novelty 閾値は触らない

---

### Task 1: A1 — 対話時刻 resolver 修正（stored を正とする）

**Files:**
- Modify: `nous/infrastructure/sqlite/persona_repo.py:327-341`（`_resolve_last_conversation_time`）
- Test: `tests/unit/test_last_conversation_resolver.py`（新規）

**Interfaces:**
- Consumes: 既存 `_parse_or_none`（persona_repo.py 内）・`parse_iso`
- Produces: `_resolve_last_conversation_time(db, state_map)` — 振る舞い変更のみ、シグネチャ不変

- [ ] **Step 1: 失敗するテストを書く**

```python
# tests/unit/test_last_conversation_resolver.py
import sqlite3

from nous.infrastructure.sqlite.persona_repo import _resolve_last_conversation_time


def _db():
    con = sqlite3.connect(":memory:")
    con.execute("CREATE TABLE memories (id INTEGER PRIMARY KEY, updated_at TEXT, created_at TEXT)")
    return con


def test_stored_value_wins_over_newer_memory():
    con = _db()
    con.execute("INSERT INTO memories (updated_at, created_at) VALUES ('2099-01-01T00:00:00', '2099-01-01T00:00:00')")
    got = _resolve_last_conversation_time(con, {"last_conversation_time": "2026-01-01T10:00:00"})
    assert got is not None and got.isoformat().startswith("2026-01-01T10:00:00")


def test_memory_fallback_when_stored_missing():
    con = _db()
    con.execute("INSERT INTO memories (updated_at, created_at) VALUES ('2026-01-01T10:00:00', '2026-01-01T09:00:00')")
    got = _resolve_last_conversation_time(con, {})
    assert got is not None and got.isoformat().startswith("2026-01-01T10:00:00")


def test_none_when_both_missing():
    con = _db()
    assert _resolve_last_conversation_time(con, {}) is None
```

- [ ] **Step 2: テストを実行して失敗を確認**

Run: `.venv\Scripts\python -m pytest tests/unit/test_last_conversation_resolver.py -q`
Expected: `test_stored_value_wins_over_newer_memory` が FAIL（現行は max() で 2099 を返す）

- [ ] **Step 3: resolver を書き換える**

`nous/infrastructure/sqlite/persona_repo.py:327-341` を丸ごと置換:

```python
def _resolve_last_conversation_time(db, state_map: dict):
    """Return the authoritative last conversation time.

    The stored context_state value is the single source of truth. Memories are
    only a legacy fallback for rows predating the stored value — introspection
    and other background writers create memories without any conversation, so
    the old max() merge let them reset decay clocks (spec 2026-09-12 A1).
    """
    stored_time = _parse_or_none(state_map.get("last_conversation_time"))
    if stored_time is not None:
        return stored_time
    try:
        row = db.execute("SELECT MAX(COALESCE(updated_at, created_at)) AS last_activity FROM memories").fetchone()
        if row and row["last_activity"]:
            return parse_iso(row["last_activity"])
    except Exception:
        pass
    return None
```

- [ ] **Step 4: テストを実行して通過を確認**

Run: `.venv\Scripts\python -m pytest tests/unit/test_last_conversation_resolver.py -q`
Expected: 3 passed

- [ ] **Step 5: 既存テストの期待値更新（あれば）**

Run: `.venv\Scripts\python -m pytest tests/unit -q -k "last_conversation or persona_repo"`
resolver の旧挙動（max マージ）を期待するテストがあれば stored 優先に期待値を修正する

- [ ] **Step 6: コミット**

```bash
git add nous/infrastructure/sqlite/persona_repo.py tests/unit/test_last_conversation_resolver.py
git commit -m "fix(a1): 対話時刻resolverをstored正・記憶はfallbackのみに (内省による減衰時計汚染を根絶)"
```

---

### Task 2: A2 record一本化 + A3 curiosity read-only allowlist

**Files:**
- Modify: `nous/api/mcp/_tools_persona.py:246-247`（record_conversation_time 削除）
- Modify: `nous/application/chat/introspection.py:785-786`（allowlist フィルタ追加）+ 新ヘルパー
- Test: `tests/unit/test_curiosity_allowlist.py`（新規）

**Interfaces:**
- Consumes: `pool.list_all_tools()` の `t.name`
- Produces: `_curiosity_tool_allowed(tool_name: str) -> bool`（Task 8 のテストで再利用）

- [ ] **Step 1: A2 — record_conversation_time を削除**

`nous/api/mcp/_tools_persona.py:246-247` を削除（post.py:141 ターン終了が唯一の記録点になる。L88 get_context 内のものは外部クライアント互換のため**残す**）:

```python
    # 状態の自発的更新 = ユーザーとの接触として最終接触時刻を記録
    ctx.persona_service.record_conversation_time(persona)
```

- [ ] **Step 2: record を期待する既存テストを更新**

Run: `rg -n "record_conversation_time" tests/`
update_context 経由の記録を期待するテストがあれば削除/修正（post.py 経路のテストは維持）

- [ ] **Step 3: A3 失敗テストを書く**

```python
# tests/unit/test_curiosity_allowlist.py
from nous.application.chat.introspection import _curiosity_tool_allowed


def test_mutating_tools_excluded():
    for name in (
        "update_context", "item_equip", "item_add", "item_remove", "item_update",
        "get_context", "memory_create", "memory_update", "memory_delete", "goal_manage",
        "create_memory", "delete_item", "set_state", "add_item",
    ):
        assert not _curiosity_tool_allowed(name), name


def test_readonly_tools_allowed():
    for name in ("memory_search", "memory_read", "memory_stats", "web_search", "fetch_url"):
        assert _curiosity_tool_allowed(name), name
```

- [ ] **Step 4: テスト実行 → FAIL 確認**

Run: `.venv\Scripts\python -m pytest tests/unit/test_curiosity_allowlist.py -q`
Expected: FAIL（関数未定義）

- [ ] **Step 5: ヘルパー実装 + 適用**

`introspection.py`（`_EXPLORATION_*` 定数の近く、L748 付近）に追加:

```python
_CURIOSITY_MUTATING_PREFIXES = (
    "update_", "item_", "create_", "delete_", "remove_", "add_", "set_",
    "memory_create", "memory_update", "memory_delete", "goal_manage",
)


def _curiosity_tool_allowed(tool_name: str) -> bool:
    """curiosity 探索は read-only カタログに制限する (spec A3)。

    状態変更系 (update_*)・item_*・goal_manage・memory 書き込みを除外。
    get_context は read-only だが record_conversation_time の副作用があるため除外。
    """
    if tool_name == "get_context":
        return False
    return not tool_name.startswith(_CURIOSITY_MUTATING_PREFIXES)
```

`_run_curiosity_exploration` 内 L785-786 を置換:

```python
            disabled = set(getattr(config, "disabled_tools", None) or [])
            tools = [
                t
                for t in pool.list_all_tools()
                if t.name not in disabled and _curiosity_tool_allowed(t.name)
            ]
```

- [ ] **Step 6: テスト実行 → PASS**

Run: `.venv\Scripts\python -m pytest tests/unit/test_curiosity_allowlist.py -q`
Expected: 2 passed

- [ ] **Step 7: コミット**

```bash
git add nous/api/mcp/_tools_persona.py nous/application/chat/introspection.py tests/unit/test_curiosity_allowlist.py
git commit -m "fix(a2,a3): update_contextでの対話時刻記録を削除・curiosity探索をread-only allowlist化"
```

---

### Task 3: A4 last_activity_at を対話イベントのみに

**Files:**
- Modify: `nous/infrastructure/sqlite/session_event_repo.py:118-126`
- Test: `tests/unit/test_session_event_last_activity.py`（新規）

**Interfaces:**
- Produces: `last_activity_at(persona)` — chat.message + chat.llm_response のみ対象。enrichment_worker `_seconds_since_last_activity` と Activity UI が消費

- [ ] **Step 1: 失敗テストを書く**

```python
# tests/unit/test_session_event_last_activity.py
import sqlite3

from nous.infrastructure.sqlite.session_event_repo import SessionEventRepository


class _FakeConn:
    def __init__(self):
        self._db = sqlite3.connect(":memory:")
        self._db.execute(
            "CREATE TABLE session_events (id INTEGER PRIMARY KEY, session_id TEXT, persona TEXT,"
            " event_type TEXT, timestamp TEXT, summary TEXT, detail TEXT, metadata_json TEXT)"
        )

    def get_memory_db(self):
        return self._db


def _repo_with_events(rows):
    conn = _FakeConn()
    for ts, etype in rows:
        conn._db.execute(
            "INSERT INTO session_events (session_id, persona, event_type, timestamp) VALUES ('s','p',?,?)",
            (etype, ts),
        )
    return SessionEventRepository(conn)


def test_brain_and_tool_events_do_not_count():
    repo = _repo_with_events(
        [("2026-01-01T12:00:00", "brain.introspection_spontaneous"), ("2026-01-01T11:00:00", "tool.called")]
    )
    assert repo.last_activity_at("p") is None


def test_chat_turn_events_count():
    repo = _repo_with_events(
        [("2026-01-01T10:00:00", "chat.message"), ("2026-01-01T10:05:00", "chat.llm_response")]
    )
    assert repo.last_activity_at("p").isoformat().startswith("2026-01-01T10:05:00")
```

- [ ] **Step 2: 実行 → FAIL 確認**

Run: `.venv\Scripts\python -m pytest tests/unit/test_session_event_last_activity.py -q`
Expected: FAIL（現行は全 event_type の MAX）

- [ ] **Step 3: 実装**

`session_event_repo.py` — クラス直上に定数を追加し `last_activity_at` を置換:

```python
# idle 判定の対象は「対話」のみ (spec A4)。tool.called / brain.* / session.* /
# events.ingested は内省・ツール実行でも idle タイマーをリセットさせない。
_IDLE_ACTIVITY_EVENT_TYPES = ("chat.message", "chat.llm_response")
```

```python
    def last_activity_at(self, persona: str) -> datetime | None:
        """Most recent chat turn timestamp for the persona (None if none)."""
        placeholders = ", ".join("?" for _ in _IDLE_ACTIVITY_EVENT_TYPES)
        row = self._db.execute(
            f"SELECT MAX(timestamp) FROM session_events WHERE persona = ? AND event_type IN ({placeholders})",  # nosec B608: placeholders are bound '?'
            (persona, *_IDLE_ACTIVITY_EVENT_TYPES),
        ).fetchone()
        if row is None or row[0] is None:
            return None
        return datetime.fromisoformat(row[0])
```

- [ ] **Step 4: 実行 → PASS**

Run: `.venv\Scripts\python -m pytest tests/unit/test_session_event_last_activity.py -q`
Expected: 2 passed

- [ ] **Step 5: コミット**

```bash
git add nous/infrastructure/sqlite/session_event_repo.py tests/unit/test_session_event_last_activity.py
git commit -m "fix(a4): last_activity_atをchat.message+chat.llm_responseのみに限定 (内省・ツールがidleを壊さない)"
```

---

### Task 4: B 実機時系列ダンプ + クロック分離 + A5 失敗時クロック不消費

**Files:**
- Modify: `nous/application/workers/enrichment_worker.py:128-165`（`_maybe_spontaneous` クロック）
- Modify: `nous/application/chat/introspection.py:616-618`（失敗時イベント記録の条件化）
- Test: `tests/unit/test_spontaneous_clock.py`（新規）
- 実機ダンプ: `tmp/dump_brain_events.py`（コミットしない）

**Interfaces:**
- Consumes: `repo.get_by_persona(persona, event_type, 1)`
- Produces: spontaneous クロックは `brain.introspection_spontaneous` のみ参照（ターン駆動 `brain.introspection` は乗らなくなる）

- [ ] **Step 1: 実機確認（修正前）— brain.* イベント時系列をダンプ**

```python
# tmp/dump_brain_events.py — 実行: .venv\Scripts\python tmp/dump_brain_events.py
import glob
import sqlite3

paths = glob.glob("data/**/*.db", recursive=True) or glob.glob("**/*.db", recursive=True)
for p in paths:
    try:
        con = sqlite3.connect(p)
        rows = con.execute(
            "SELECT event_type, timestamp FROM session_events "
            "WHERE event_type LIKE 'brain.%' ORDER BY timestamp DESC LIMIT 40"
        ).fetchall()
    except sqlite3.OperationalError:
        continue
    if rows:
        print("==", p)
        for etype, ts in rows:
            print(etype, ts)
```

2h 機序（brain.introspection_spontaneous 直後に brain.introspection が書かれ、次回発火が後退する時系列）を実データで確認し、結果を報告メモに記録する。DB が見つからない/実機未起動なら「未確認」と記録して先へ進む（コード上の機序は ora 審査で確定済み）。

- [ ] **Step 2: 失敗テストを書く**

```python
# tests/unit/test_spontaneous_clock.py
import sqlite3
from datetime import datetime, timedelta
from unittest.mock import MagicMock

from nous.application.workers.enrichment_worker import EnrichmentWorker


class _FakeConn:
    def __init__(self):
        self._db = sqlite3.connect(":memory:")
        self._db.execute(
            "CREATE TABLE session_events (id INTEGER PRIMARY KEY, session_id TEXT, persona TEXT,"
            " event_type TEXT, timestamp TEXT, summary TEXT, detail TEXT, metadata_json TEXT)"
        )

    def get_memory_db(self):
        return self._db


def _worker(repo, now):
    w = EnrichmentWorker.__new__(EnrichmentWorker)
    w._persona = "p"
    w.context = MagicMock()
    w.context._session_event_repo = repo
    w.context.introspection_engine = None  # 発火させずクロック判定のみ見る
    w._config = MagicMock()
    w._config.brain_spontaneous_enabled = True
    w._now = lambda: now
    w._naive = EnrichmentWorker._naive
    w._num = EnrichmentWorker._num
    return w


def _insert(conn, etype, ts):
    conn.get_memory_db().execute(
        "INSERT INTO session_events (session_id, persona, event_type, timestamp) VALUES ('s','p',?,?)",
        (etype, ts.isoformat()),
    )


def test_turn_introspection_does_not_block_spontaneous(monkeypatch):
    now = datetime(2026, 1, 1, 12, 0, 0)
    conn = _FakeConn()
    _insert(conn, "brain.introspection", now - timedelta(minutes=5))  # ターン駆動が直前
    _insert(conn, "brain.introspection_spontaneous", now - timedelta(hours=2))  # spontaneous は1h前
    repo = MagicMock()
    repo.get_by_persona = lambda persona, etype, limit: _rows(conn, etype)
    w = _worker(repo, now)
    monkeypatch.setattr("nous.application.chat.introspection.run_spontaneous", lambda *a, **k: _noop())
    w._maybe_spontaneous(idle_seconds=9999)  # クロック通過 → 発火（engine=None で run_spontaneous は呼ばれない）
```

実装は EnrichmentWorker の実構造（`_num`/`_naive` が staticmethod でない場合は MagicMock に差し替え）に合わせて調整すること。判定の本質: spontaneous 1h前 + ターン内省 5m前 のとき、発火ガードを通過すること。

- [ ] **Step 3: 実行 → FAIL 確認**

Run: `.venv\Scripts\python -m pytest tests/unit/test_spontaneous_clock.py -q`
Expected: FAIL（現行は両種別 MAX のため 5m 前の brain.introspection でブロックされる）

- [ ] **Step 4: クロックを spontaneous のみに変更**

`enrichment_worker.py:128-132` の docstring を更新（「種別は brain.introspection_spontaneous のみを見る（ターン駆動内省が自発のクロックを進めない・spec B）」）し、L142-153 を置換:

```python
            interval = self._num("brain_spontaneous_interval_hours", 1.0)
            events = repo.get_by_persona(self._persona, "brain.introspection_spontaneous", 1)
            last = events[0].timestamp if events else None
            if last is not None:
                elapsed = (self._naive(self._now()) - self._naive(last)).total_seconds()
                if elapsed < interval * 3600.0:
                    return
```

- [ ] **Step 5: A5 — 失敗時クロック不消費**

`introspection.py:616-618` を条件化:

```python
    if result is not None:
        _record_introspection_event(
            repo, persona, "brain.introspection_spontaneous", result, applied, 0, len(memory_texts), stored
        )
```

注: 失敗時はクロックが進まず、次 worker 周期（`brain_enrich_interval_seconds`=60s tick × idle 条件）で再試行になる。LLM 障害中は最大 1回/分の再試行になるが、即座に None を返す性質のコストとして許容（spec A5 通り）。

- [ ] **Step 6: 実行 → PASS**

Run: `.venv\Scripts\python -m pytest tests/unit/test_spontaneous_clock.py tests/unit/test_last_conversation_resolver.py -q`
Expected: all passed

- [ ] **Step 7: コミット**

```bash
git add nous/application/workers/enrichment_worker.py nous/application/chat/introspection.py tests/unit/test_spontaneous_clock.py
git commit -m "fix(b,a5): spontaneousクロックを専用種別のみ参照+失敗時にクロック消費しない (1h設定が2h化するバグ)"
```

---

### Task 5: H デフォルト値変更

**Files:**
- Modify: `nous/domain/session_config.py:131-147,172`

**Interfaces:**
- Produces: `brain_monologue_enabled=True`, `brain_spontaneous_enabled=True`, `brain_spontaneous_interval_hours=1`, `forgetting_decay_interval_seconds=3600`（デフォルトのみ。既存 config.json を持つ persona は実効値不変）

- [ ] **Step 1: 現デフォルトを期待するテストを特定**

Run: `rg -n "86400|spontaneous_interval|brain_monologue_enabled|brain_spontaneous_enabled" tests/ nous/ --type py`
既存テストで旧デフォルト（6 / 86400 / False / False）を期待する箇所を列挙する

- [ ] **Step 2: session_config.py を更新**

```python
    # REM 独り言 (drain バッチ完走時に LLM 1 call で生成・session_events 保存)
    brain_monologue_enabled: bool = True
```

```python
    # 自発的内省: 誰も話しかけてこない静かな時間に記憶と現在状態から独り言を産出。
    # 発火間隔は brain.introspection_spontaneous の最新タイムスタンプから
    # interval_hours 以上経過で判定（worker 側ガード・spec B）。
    brain_spontaneous_enabled: bool = True
    brain_spontaneous_interval_hours: int = 1
```

```python
    forgetting_decay_interval_seconds: int = 3600  # 1h sweep — 減衰は経過時間依存なので sweep は平滑性にのみ影響
```

- [ ] **Step 3: 既存テストの期待値更新 + 新規デフォルトテスト**

既存テストの期待値を新デフォルトに合わせ修正。新規:

```python
# tests/unit/test_default_values.py
from nous.domain.session_config import SessionConfig


def test_h_spec_defaults():
    cfg = SessionConfig()
    assert cfg.brain_spontaneous_interval_hours == 1
    assert cfg.brain_spontaneous_enabled is True
    assert cfg.brain_monologue_enabled is True
    assert cfg.forgetting_decay_interval_seconds == 3600
```

- [ ] **Step 4: 実行 → PASS**

Run: `.venv\Scripts\python -m pytest tests/unit/test_default_values.py -q` → 次に列挙した既存テスト群も実行して全緑にする

- [ ] **Step 5: コミット**

```bash
git add nous/domain/session_config.py tests/
git commit -m "feat(h): デフォルト値変更 — LLM周期1h化(spontaneous)+monologue/spontaneousデフォルトON+忘却sweep 1h"
```

---

### Task 6: D 内省プロンプト設定化 + persona_identity 全文化

**Files:**
- Modify: `nous/domain/session_config.py`（brain_*_prompt 追加）
- Modify: `nous/application/chat/introspection.py:155-215`（prompt_override 引数+`_format_prompt`）、call site（`run_spontaneous` L591-593、`run_introspection` 内 `engine.generate` 呼び出し）
- Test: `tests/unit/test_introspection_prompt_override.py`（新規）

**Interfaces:**
- Consumes: `getattr(config, "brain_spontaneous_prompt", "")` / `"brain_introspection_prompt"`
- Produces: `_format_prompt(template, default, **fields)` — Task 7 も利用する共通ヘルパー
- Note: 一人称遵守ブロックは**注入しない**（ユーザー決定）

- [ ] **Step 1: session_config.py にフィールド追加**

`brain_spontaneous_interval_hours` の直後に追加:

```python
    # 内省プロンプト上書き (空文字 = コード内デフォルトを使用)。
    # プレースホルダ: {persona} {current_state} {memory_texts} {persona_identity}
    #   + ターン駆動のみ {recent_turns}。欠落があるとデフォルトへ自動フォールバック。
    brain_introspection_prompt: str = ""
    brain_spontaneous_prompt: str = ""
```

- [ ] **Step 2: 失敗テストを書く**

```python
# tests/unit/test_introspection_prompt_override.py
from nous.application.chat.introspection import IntrospectionEngine, _format_prompt


def test_default_when_empty():
    got = _format_prompt("", "Hello {persona}! {current_state}", persona="H", current_state="cs")
    assert got == "Hello H! cs"


def test_override_used():
    got = _format_prompt("X{persona}X", "Hello {persona}", persona="H", current_state="cs")
    assert got == "XHX"


def test_broken_override_falls_back():
    got = _format_prompt("broken {missing_key}", "Hello {persona}", persona="H", current_state="cs")
    assert got == "Hello H"


def test_generate_spontaneous_uses_override(monkeypatch):
    engine = IntrospectionEngine.__new__(IntrospectionEngine)
    captured = {}

    async def fake_call_llm(user_message):
        captured["msg"] = user_message
        return '{"monologue": "hi"}', None

    monkeypatch.setattr(engine, "_call_llm", fake_call_llm)
    import asyncio

    asyncio.run(
        engine.generate_spontaneous(
            "p", "sys", [], {}, prompt_override="OVERRIDE {persona} {current_state} {memory_texts} {persona_identity}"
        )
    )
    assert captured["msg"].startswith("OVERRIDE")
```

- [ ] **Step 3: 実行 → FAIL 確認**

Run: `.venv\Scripts\python -m pytest tests/unit/test_introspection_prompt_override.py -q`
Expected: FAIL（`_format_prompt` 未定義 / `prompt_override` 引数なし）

- [ ] **Step 4: 実装**

introspection.py — 定数 `_MAX_CHARS_PER_MEMORY` の下に追加:

```python
# persona_identity (system_prompt) の安全弁上限。全文化したため必要。
_PERSONA_IDENTITY_MAX_CHARS = 12000
```

新ヘルパー（`_format_current_state` 近くに追加）:

```python
def _format_prompt(override: str, default: str, **fields) -> str:
    """内省プロンプトの組み立て (spec D)。空文字=デフォルト。

    上書きテンプレートにプレースホルダ欠落等の不備があれば
    デフォルトにフォールバックする（ユーザー設定で内省を壊さない）。
    """
    template = (override or "").strip()
    if template:
        try:
            return template.format(**fields)
        except (KeyError, IndexError, ValueError) as e:
            logger.warning("introspection: prompt override invalid (%s) — using default", e)
    return default.format(**fields)
```

`generate`（L166-191）と `generate_spontaneous`（L193-215）に `prompt_override: str = ""` 引数を追加し、プロンプト組み立てを置換（両方共通の形）:

```python
        user_message = _format_prompt(
            prompt_override,
            _SPONTANEOUS_PROMPT,
            persona=persona,
            current_state=_format_current_state(current_state),
            memory_texts=mems,
            persona_identity=(system_prompt or "")[:_PERSONA_IDENTITY_MAX_CHARS],
        )
```

（`generate` 側は `_INTROSPECTION_PROMPT` + `recent_turns=turns_text` も渡す）

- [ ] **Step 5: call site に config から渡す**

`run_spontaneous` L593:

```python
        result = await engine.generate_spontaneous(
            persona,
            persona_identity,
            memory_texts,
            current_state,
            prompt_override=getattr(config, "brain_spontaneous_prompt", ""),
        )
```

`run_introspection` 内の `engine.generate(...)` 呼び出し（L500付近）にも `prompt_override=getattr(config, "brain_introspection_prompt", "")` を追加。

- [ ] **Step 6: 実行 → PASS**

Run: `.venv\Scripts\python -m pytest tests/unit/test_introspection_prompt_override.py -q`
Expected: 4 passed

- [ ] **Step 7: コミット**

```bash
git add nous/domain/session_config.py nous/application/chat/introspection.py tests/unit/test_introspection_prompt_override.py
git commit -m "feat(d): 内省プロンプトをconfig設定可能化+persona_identity全文化(安全弁12000字)"
```

---

### Task 7: G リサーチ継続性修復（exploration cap 免除 + 持ち越し）

**Files:**
- Modify: `nous/application/chat/introspection.py:29-34`（定数）、L176/L201（slice 削除）、`run_spontaneous` L580-586（cap 適用移動）、`run_introspection` の memory_texts 収集箇所（80字cap 移動）、`_summarize_and_record` L861-904（構造化出力+持ち越し）、`_select_tool` L835-851（JSONパース共通化）
- Test: `tests/unit/test_exploration_memory_cap.py`（新規）

**Interfaces:**
- Consumes: Task 6 の `_format_prompt` / `prompt_override` 引数（同ファイル先行タスク）
- Produces: memory_texts は**呼び出し側がcap済み**という契約（engine はsliceしない）。`_parse_json_object(text) -> dict | None`

- [ ] **Step 1: 失敗テストを書く**

```python
# tests/unit/test_exploration_memory_cap.py
from nous.application.chat.introspection import (
    _MAX_CHARS_PER_MEMORY,
    _cap_memory_texts,
    _parse_json_object,
)


class _M:
    def __init__(self, content, tags):
        self.content = content
        self.tags = tags


def test_exploration_memories_get_500_cap():
    long_expl = "x" * 400
    long_norm = "y" * 200
    got = _cap_memory_texts([_M(long_expl, ["exploration", "introspection"]), _M(long_norm, ["preference"])])
    assert got[0] == long_expl  # 探索要約は切断されない (spec G)
    assert got[1] == "y" * _MAX_CHARS_PER_MEMORY


def test_parse_json_object_code_fence():
    assert _parse_json_object('```json\n{"a": 1}\n```') == {"a": 1}
    assert _parse_json_object("not json") is None
    assert _parse_json_object("[1,2]") is None
```

- [ ] **Step 2: 実行 → FAIL 確認**

Run: `.venv\Scripts\python -m pytest tests/unit/test_exploration_memory_cap.py -q`
Expected: FAIL（`_cap_memory_texts` / `_parse_json_object` 未定義）

- [ ] **Step 3: 実装**

定数追加（L34 付近）:

```python
# 探索 (exploration) タグ記憶のみに適用する緩い cap — 80字cap が500字探索要約を
# 切断して次回の curiosity が前回結果を踏めない問題の修復 (spec G)。
_EXPLORATION_MEMORY_CAP = 500
```

ヘルパー（`_curiosity_tool_allowed` 近く）:

```python
def _cap_memory_texts(memories: list) -> list[str]:
    """最近記憶を cap 済み文字列にする。exploration タグのみ緩い cap を適用 (spec G)。"""
    texts: list[str] = []
    for m in memories:
        content = getattr(m, "content", None)
        if not content:
            continue
        tags = set(getattr(m, "tags", None) or [])
        cap = _EXPLORATION_MEMORY_CAP if "exploration" in tags else _MAX_CHARS_PER_MEMORY
        texts.append(str(content)[:cap])
    return texts
```

```python
def _parse_json_object(text: str) -> dict | None:
    """```json 囲み/素JSON 両対応の dict パース。失敗時 None。"""
    cleaned = text.strip()
    if cleaned.startswith("```"):
        lines = cleaned.splitlines()
        cleaned = "\n".join(lines[1:-1] if lines[-1].startswith("```") else lines[1:])
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None
```

`_select_tool` の L835-851 パース部を `_parse_json_object` 経由に置換（重複排除）。

`run_spontaneous` L580-586 を置換:

```python
    memory_texts: list[str] = []
    try:
        recent = ctx.memory_service.get_recent(limit=10)
        items = getattr(recent, "value", None) if getattr(recent, "is_ok", False) else None
        memory_texts = _cap_memory_texts(items or [])
    except Exception:
        logger.debug("introspection spontaneous: memory fetch failed", exc_info=True)
```

engine `generate`/`generate_spontaneous` の L176/L201 から slice を削除:

```python
        mems = "\n".join(f"- {t}" for t in memory_texts[:_MAX_MEMORIES]) or "(なし)"
```

`run_introspection` 側の memory_texts 収集箇所（drained 由来・L500付近）も呼び出し側 cap に変更（80字をそこで適用）。

- [ ] **Step 4: 構造化要約+持ち越し**

`_summarize_and_record` の prompt（L866-873）を置換:

```python
    prompt = (
        "静かな時間に気になって調べたことを、あなたらしい一人称の独り言にして。\n"
        f"気になっていたこと: {curiosity}\n"
        f"使ったツール: {tool_name}\n"
        f"結果:\n{result_text}\n\n"
        "出力は JSON のみ。\n"
        '{"summary": "わかったことを3文以内。「調べたら〜だった」の調子で。ツール名や「結果」という単語は出さない", '
        '"satisfied": true または false, "unresolved": "満たせなかった質問を一人称で一行。なければ null"}'
    )
```

パースと保存（L874 以降を置換）:

```python
    try:
        text, _usage = await engine._call_llm(prompt)
    except Exception:
        logger.info("introspection: curiosity summary LLM failed", exc_info=True)
        return
    data = _parse_json_object(text or "")
    if not data:
        return
    summary = str(data.get("summary") or "").strip()[:_EXPLORATION_SUMMARY_MAX_CHARS]
    if not summary:
        return

    try:
        await ctx.memory_service.create_memory(
            persona=persona,
            content=summary,
            importance=0.4,
            tags=["exploration", "introspection"],
            source_context="introspection",
        )
    except Exception:
        logger.debug("introspection: exploration memory failed", exc_info=True)

    # 「見つからなかった」質問を次周期の材料として持ち越す (spec G・絞り込みループは作らない)。
    unresolved = str(data.get("unresolved") or "").strip().strip('"')
    if data.get("satisfied") is False and unresolved and unresolved.lower() != "null":
        try:
            await ctx.memory_service.create_memory(
                persona=persona,
                content=unresolved[:_EXPLORATION_MEMORY_CAP],
                importance=0.5,
                tags=["exploration", "unresolved", "introspection"],
                source_context="introspection",
            )
        except Exception:
            logger.debug("introspection: unresolved question memory failed", exc_info=True)
```

（wiring emit 部は Task 8 で永続化と一緒に触るので現状維持）

- [ ] **Step 5: 実行 → PASS**

Run: `.venv\Scripts\python -m pytest tests/unit/test_exploration_memory_cap.py -q`
Expected: 3 passed

- [ ] **Step 6: コミット**

```bash
git add nous/application/chat/introspection.py tests/unit/test_exploration_memory_cap.py
git commit -m "feat(g): exploration記憶のcap免除+未解決質問の持ち越しでリサーチ継続性を修復"
```

---

### Task 8: C backend — tool.called publish + 要約の永続化

**Files:**
- Modify: `nous/application/chat/introspection.py:780-811`（publish 追加）、`_summarize_and_record`（brain.monologue 挿入）
- Test: `tests/unit/test_exploration_publish_persist.py`（新規）

**Interfaces:**
- Consumes: `nous.api.mcp._tools_helpers._emit_tool_called(ctx, tool_name, result_summary, success, params_summary, error)`、`SessionEvent`（introspection.py に既存 import 済み）
- Produces: event_bus `tool.called` に `source=introspection` 付きデータ（Task 9 のフロントフィルタが消費）。brain.monologue events に `metadata={"kind": "exploration", "tool": ...}`

- [ ] **Step 1: 失敗テストを書く**

```python
# tests/unit/test_exploration_publish_persist.py
import asyncio
from unittest.mock import MagicMock


def test_summarize_persists_brain_monologue_event(monkeypatch):
    from nous.application.chat import introspection as mod

    ctx = MagicMock()
    ctx._session_event_repo = MagicMock()
    ctx.memory_service = MagicMock()
    ctx.memory_service.create_memory = _async_ok()
    events = []
    ctx._session_event_repo.insert = lambda ev: events.append(ev)

    engine = MagicMock()
    asyncio.run(
        _fake_llm(engine, '{"summary": "調べたら面白かった。", "satisfied": true, "unresolved": null}')
    )

    asyncio.run(
        mod._summarize_and_record(ctx, engine, "p", "気になること", "web_search", {"result": "データ"})
    )
    mono = [e for e in events if getattr(e, "event_type", "") == "brain.monologue"]
    assert mono and mono[0].summary.startswith("調べたら")


def _async_ok():
    async def _ok(*a, **k):
        return MagicMock()

    return _ok


def _fake_llm(engine, payload):
    async def _llm(prompt):
        return payload, None

    engine._call_llm = _llm
    return engine
```

- [ ] **Step 2: 実行 → FAIL 確認**

Run: `.venv\Scripts\python -m pytest tests/unit/test_exploration_publish_persist.py -q`
Expected: FAIL（brain.monologue 挿入なし）

- [ ] **Step 3: publish 実装**

`_run_curiosity_exploration` 内 L799-802（call_tool 直後）を置換:

```python
            tool_result = await pool.call_tool(call["tool_name"], call.get("args") or {})
            errored = "error" in tool_result or tool_result.get("isError")
            try:
                from nous.api.mcp._tools_helpers import _emit_tool_called

                await _emit_tool_called(
                    ctx,
                    call["tool_name"],
                    "(空の結果)" if errored else str(tool_result.get("result") or "")[:80],
                    not errored,
                    params_summary=json.dumps(call.get("args") or {}, ensure_ascii=False)[:200],
                    error=str(tool_result.get("error") or "") if errored else None,
                )
            except Exception:
                logger.debug("introspection: tool.called publish failed", exc_info=True)
            if errored:
                logger.info("introspection: curiosity — tool call errored: %s", tool_result)
                return
```

`_emit_tool_called` の data dict に source を足すため、`nous/api/mcp/_tools_helpers.py:92-98` の data 生成後に1行追加（**通常経路のイベントにも source を付ける — 既存 UI への影響は新キー追加のみ**）:

```python
            data["source"] = "direct"  # 呼び出し側が introspection の場合は後から上書き
```

→ 内省側では publish 後に上書きせず、`_run_curiosity_exploration` 側で渡す前に設定する。簡潔のため `_emit_tool_called` に `source: str = "direct"` 引数を追加し、introspection 側は `source="introspection"` を渡す。

- [ ] **Step 4: 永続化実装**

`_summarize_and_record` の exploration memory create 直後に追加:

```python
    # 探索要約を brain.monologue の既存永続パスに乗せる (spec C) —
    # wiring emit だけだとリロードで消えるため。
    try:
        repo = getattr(ctx, "_session_event_repo", None)
        if repo is not None:
            repo.insert(
                SessionEvent(
                    session_id="unknown",
                    persona=persona,
                    event_type="brain.monologue",
                    summary=summary,
                    timestamp=get_now(),
                    metadata={"kind": "exploration", "tool": tool_name},
                )
            )
    except Exception:
        logger.debug("introspection: exploration monologue persist failed", exc_info=True)
```

- [ ] **Step 5: 実行 → PASS**

Run: `.venv\Scripts\python -m pytest tests/unit/test_exploration_publish_persist.py -q`
Expected: passed

- [ ] **Step 6: コミット**

```bash
git add nous/application/chat/introspection.py nous/api/mcp/_tools_helpers.py tests/unit/test_exploration_publish_persist.py
git commit -m "feat(c): curiosity探索のtool.calledをevent_busへpublish+探索要約をbrain.monologue永続パスで保存"
```

---

### Task 9: C frontend — チャットログ表示 + 実機確認

**Files:**
- Modify: `nous/api/http/static/chat/chat-send.js:881`（connectChatEvents ハンドラ）
- Test: `nous/api/http/static/chat/chat-monologue.test.js` に追記

**Interfaces:**
- Consumes: Task 8 の `tool.called`（`source=introspection`）
- Produces: チャット画面に探索ツールチップ＋要約バブル（要約バブルは wiring `kind=monologue` の既存ハンドラで自動表示・リロード後は `restoreMonologueBubbles()` が brain.monologue から復元）

- [ ] **Step 1: 既存の復元系ツールチップ実装を特定**

Run: `rg -n "tool chip|tool_call|chip" nous/api/http/static/chat/chat-history.js nous/api/http/static/chat/chat-monologue.test.js`
`restoreMonologueBubbles`（chat-history.js:933-963）が brain.tool_call をどう描画しているかを確認し、**同一の描画関数をライブでも再利用**する。専用の新 UI は作らない。

- [ ] **Step 2: connectChatEvents に tool.called ハンドラ追加**

`chat-send.js:881` の `connectChatEvents` 内 `handlers` オブジェクトに追加（既存の wiring ハンドラと同型）:

```javascript
      tool_called: function (e) {
        // 内省 curiosity 探索のツール実行をチャットに流す (spec C)。
        // メイン対話の tool_call SSE と二重表示しないため introspection 由来のみ。
        try {
          var d = JSON.parse(e.data || "{}");
          if (d && d.tool_name && d.source === "introspection") {
            N.Chat.tools.appendIntrospectionCall(d);
          }
        } catch (_e) { /* best-effort */ }
      },
```

`N.Chat.tools.appendIntrospectionCall` は chat-history.js の復元系チップ描画と同じ見た目を返す薄いラッパーとして chat-send.js に追加する（復元実装が直接再利用できない場合のみ、`chat-monologue-bubble` と同調の最小 chip を新設 — CSS class `chat-tool-chip` 既存流用）。

- [ ] **Step 3: vitest を追加**

`chat-monologue.test.js` に既存 describe の型踏襲で:

```javascript
  it('live tool.called handler renders introspection chips only', async () => {
    // connectChatEvents の tool_called ハンドラを呼び、source=introspection のときのみ
    // chip が追加されることを検証（source=direct では無視）
  });
```

（ハンドラ実装に合わせて実コードを書く。`source=direct` 無視のアサーションを必ず含める）

- [ ] **Step 4: vitest 実行**

Run: `npm test -- chat-monologue` （またはリポジトリの vitest 実行方法に従う — 前例: 「vitest 20 passed」）
Expected: 全緑

- [ ] **Step 5: 実機確認（Playwright MCP・orchestrator 実施）**

アプリ起動 → `/chat` を `domcontentloaded` + 要素待ちで開く（SSE 多用ページなので networkidle 待ち禁止）:
1. monologue バブル（💭）が表示されること（既存分）
2. チャット履歴リロード後も探索要約バブルが復元されること（brain.monologue 永続化の検証）
3. console errors 0 であること（`browser_console_messages` level=error で確認）
4. 探索チップが二重表示しないこと（チャット履歴復元の tool chips と live ハンドラの排他）

- [ ] **Step 6: コミット**

```bash
git add nous/api/http/static/chat/chat-send.js nous/api/http/static/chat/chat-monologue.test.js
git commit -m "feat(c): 内省探索のツールコールをチャットログに表示 (introspection由来のみ・復元チップと同調)"
```

---

### Task 10: F 抽出LLM 2分割（context / item）

**Files:**
- Modify: `nous/domain/session_config.py`（item_llm_* 追加）
- Modify: `nous/application/chat/memory_prompts.py:15-101`（プロンプト分割）
- Modify: `nous/application/chat/memory_extractor.py:78-143`（MemoryLLM.process mode 引数）、`run_memory_llm` L301-330（2呼び出し+マージ）
- Test: `tests/unit/test_memory_llm_split.py`（新規）

**Interfaces:**
- Consumes: `config.extract_model` / `config.get_effective_model()` / `get_provider`（既存）
- Produces: `MemoryLLM.process(..., mode: str = "context")` — `"context"` は facts/goals/promises/context_update、`"item"` は inventory_update のみ返す。`run_memory_llm` は context 呼び出し後に item 呼び出しを**逐次**実行し inventory_update を上書きマージ（並列化しない）

- [ ] **Step 1: session_config.py に item_llm_* を追加**

`brain_llm_*` ブロック（L126-130）の直後に追加:

```python
    # Dedicated LLM for the item (inventory) extractor — split from the context
    # extractor (spec F). OFF = reuse extract_model / the chat 4-piece set.
    item_llm_dedicated: bool = False
    item_llm_provider: str = ""
    item_llm_model: str = ""
    item_llm_base_url: str = ""
    item_llm_api_key: str = ""
```

- [ ] **Step 2: プロンプト分割**

`memory_prompts.py` — `_MEMORY_LLM_PROMPT` を以下の2つに分割（共通の[System Directive]/identity/context/会話ヘッダは踏襲。**既存名 `_MEMORY_LLM_PROMPT` は context 側の別名として残す**（memory_llm.py の re-export 互換）:

`_CONTEXT_LLM_PROMPT`: facts/goals/promises/context_update ブロックのみ（inventory_update と【現在の所持品】セクションを削除、【注意】の inventory 節を削除）。末尾の「何も抽出すべきものがなければ」例も inventory_update 抜きに更新。
`_ITEM_LLM_PROMPT`: 【現在の所持品】+ 会話 + `inventory_update` ブロックのみ。facts/goals/promises/context_update は含めない。注意節は inventory 関連のみ残す。

```python
_MEMORY_LLM_PROMPT = _CONTEXT_LLM_PROMPT  # 後方互換エイリアス
```

- [ ] **Step 3: MemoryLLM.process に mode 引数**

```python
    async def process(
        self,
        config: ChatConfig,
        user_message: str,
        assistant_response: str,
        *,
        context: str = "",
        commitments: str = "",
        inventory: str = "",
        persona_name: str = "assistant",
        persona_identity: str = "",
        drift: dict | None = None,
        mode: str = "context",
    ) -> dict:
```

provider 解決部（L94-108）を拡張:

```python
        extract_model = config.extract_model.strip() or config.get_effective_model()
        if mode == "item" and getattr(config, "item_llm_dedicated", False):
            model = getattr(config, "item_llm_model", "").strip() or extract_model
            api_key = getattr(config, "item_llm_api_key", "").strip() or config.get_effective_api_key()
            base_url = getattr(config, "item_llm_base_url", "").strip() or config.get_effective_base_url()
            provider_name = getattr(config, "item_llm_provider", "").strip() or config.provider
        else:
            model, api_key, base_url, provider_name = (
                extract_model,
                config.get_effective_api_key(),
                config.get_effective_base_url(),
                config.provider,
            )
        if not api_key or not model:
            return {}
```

prompt 選択:

```python
        prompt_template = _ITEM_LLM_PROMPT if mode == "item" else _CONTEXT_LLM_PROMPT
```

format 引数は共通（未使用プレースホルダはテンプレート側に存在しないだけで渡しても無害）。`mode="item"` では `drift_section` を空にする（inventory 抽出に drift 反省は不要）。

- [ ] **Step 4: run_memory_llm を 2 呼び出しに**

L310-328 を置換:

```python
        context_str, commitments_str, inventory_str = await _build_memory_llm_context(ctx)
        persona_name = ctx.persona or "assistant"
        persona_identity = (config.system_prompt or "").strip()
        from nous.application.chat.memory_llm import MemoryLLM as _MemoryLLM

        llm = _MemoryLLM()
        common = dict(
            user_message=user_message,
            assistant_response=assistant_response,
            context=context_str,
            commitments=commitments_str,
            inventory=inventory_str,
            persona_name=persona_name,
            persona_identity=persona_identity,
        )
        result = await llm.process(config, drift=payload.get("drift"), **common, mode="context") if False else await llm.process(
            config, **common, drift=payload.get("drift"), mode="context"
        )
        if not result:
            logger.warning("MemoryLLM: empty context result drift=empty_result persona=%s", persona_name)
            result = {"facts": [], "goals": [], "promises": [], "context_update": {}}
        item_result = await llm.process(config, **common, mode="item")
        result["inventory_update"] = (item_result or {}).get("inventory_update") or {}
        if not result.get("inventory_update"):
            logger.info("MemoryLLM: item extractor returned no inventory changes persona=%s", persona_name)
```

（`if False else` の駄目な試みを書かないこと — 正: `result = await llm.process(config, **common, drift=payload.get("drift"), mode="context")` の1文のみ。上は誤記防止の注釈であり実装には入れない）

- [ ] **Step 5: 失敗テスト → 実装 → PASS**

```python
# tests/unit/test_memory_llm_split.py
import asyncio
from unittest.mock import MagicMock, patch


def _capture_provider(calls):
    class _P:
        async def stream(self, **k):
            calls.append(k)
            return iter([])

    return _P


def test_item_mode_uses_item_llm_dedicated(monkeypatch):
    from nous.application.chat.memory_extractor import MemoryLLM

    cfg = MagicMock()
    cfg.extract_model = ""
    cfg.get_effective_model = lambda: "chat-model"
    cfg.get_effective_api_key = lambda: "sk"
    cfg.get_effective_base_url = lambda: "http://b"
    cfg.provider = "openai_compat"
    cfg.item_llm_dedicated = True
    cfg.item_llm_model = "item-model"
    cfg.item_llm_api_key = ""
    cfg.item_llm_base_url = ""
    cfg.item_llm_provider = ""

    got = {}
    def fake_get_provider(provider, api_key, model, base_url):
        got.update(provider=provider, api_key=api_key, model=model, base_url=base_url)
        raise RuntimeError("stop")
    monkeypatch.setattr("nous.application.chat.memory_extractor.get_provider", fake_get_provider)
    asyncio.run(MemoryLLM().process(cfg, "u", "a", inventory="i", mode="item"))
    assert got["model"] == "item-model" and got["provider"] == "openai_compat"


def test_context_prompt_has_no_inventory_json(monkeypatch):
    from nous.application.chat.memory_prompts import _CONTEXT_LLM_PROMPT, _ITEM_LLM_PROMPT

    assert "inventory_update" not in _CONTEXT_LLM_PROMPT
    assert "facts" not in _ITEM_LLM_PROMPT
    assert '"inventory_update"' in _ITEM_LLM_PROMPT
```

Run: `.venv\Scripts\python -m pytest tests/unit/test_memory_llm_split.py -q`
Expected: passed

- [ ] **Step 6: コミット**

```bash
git add nous/domain/session_config.py nous/application/chat/memory_prompts.py nous/application/chat/memory_extractor.py tests/unit/test_memory_llm_split.py
git commit -m "feat(f): MemoryLLMをcontext抽出とitem抽出の2呼び出しに分割 (item_llm_* 専用モデル設定)"
```

---

### Task 11: F 更新除外ルール拡張

**Files:**
- Modify: `nous/application/chat/memory_extractor.py:284-298`（`_context_update_skips` 拡張）、context_update/inventory 適用部 L483-594
- Test: `tests/unit/test_context_update_skips.py`（新規）

**Interfaces:**
- Consumes: `tool_calls_log` エントリ `{"name": str, "input": dict}`
- Produces: `_context_update_skips(log) -> tuple[bool, bool, bool, bool, bool]` — (skip_emotion, skip_body, skip_state_text, skip_user_info, skip_inventory)

- [ ] **Step 1: 失敗テストを書く**

```python
# tests/unit/test_context_update_skips.py
from nous.application.chat.memory_extractor import _context_update_skips


def test_update_context_fields_skip():
    log = [{"name": "update_context", "input": {"emotion": "joy", "mental_state": "眠い", "user_name": "x"}}]
    se, sb, st, su, _ = _context_update_skips(log)
    assert (se, st, su) == (True, True, True) and sb is False


def test_item_tool_skips_inventory_but_search_does_not():
    se, sb, st, su, si = _context_update_skips([{"name": "item_equip", "input": {"slot": "top"}}])
    assert (se, sb, st, su, si) == (False, False, False, False, True)
    assert _context_update_skips([{"name": "item_search", "input": {}}])[-1] is False


def test_no_log_all_false():
    assert _context_update_skips(None) == (False, False, False, False, False)
```

- [ ] **Step 2: 実装**

```python
_STATE_TEXT_KEYS = {"mental_state", "physical_state", "environment"}


def _context_update_skips(tool_calls_log: list[dict] | None) -> tuple[bool, bool, bool, bool, bool]:
    """メインLLMが今ターン直接更新した領域を抽出LLMの適用から除外する (spec F)。

    戻り値: (skip_emotion, skip_body, skip_state_text, skip_user_info, skip_inventory)
    - update_context: 感情/身体/状態テキスト/user_* をスキップ
    - item_* (検索除く・item_search は read-only): inventory_update をスキップ
    """
    skip_emotion = skip_body = skip_state_text = skip_user_info = skip_inventory = False
    for entry in tool_calls_log or []:
        if not isinstance(entry, dict):
            continue
        name = entry.get("name")
        tool_input = entry.get("input") if isinstance(entry.get("input"), dict) else {}
        if name == "update_context":
            if "emotion" in tool_input or "emotion_intensity" in tool_input:
                skip_emotion = True
            if {"body_state", "fatigue", "warmth", "arousal"} & tool_input.keys():
                skip_body = True
            if _STATE_TEXT_KEYS & tool_input.keys():
                skip_state_text = True
            if any(k.startswith("user_") for k in tool_input):
                skip_user_info = True
        elif isinstance(name, str) and name.startswith("item_") and name != "item_search":
            skip_inventory = True
    return skip_emotion, skip_body, skip_state_text, skip_user_info, skip_inventory
```

適用側（L484-555 context_update / L557-594 inventory）:
- `skip_emotion, skip_body, skip_state_text, skip_user_info, skip_inventory = _context_update_skips(tool_calls_log)` を取得
- state_fields ループ: `if not skip_state_text` のときだけ physical_state/mental_state/environment を収集（skip 時は `ctx_update.pop(key, None)`）
- user_info: `if user_info_map and not skip_user_info`
- inventory: `if skip_inventory: inv_update = {}` を適用前に置く（InventoryUpdateSSE にも流れない）

- [ ] **Step 3: 実行 → PASS**

Run: `.venv\Scripts\python -m pytest tests/unit/test_context_update_skips.py tests/unit/test_memory_llm_split.py -q`
Expected: all passed

- [ ] **Step 4: コミット**

```bash
git add nous/application/chat/memory_extractor.py tests/unit/test_context_update_skips.py
git commit -m "feat(f): 会話LLMが直接更新した領域を抽出LLM適用から除外するルール拡張"
```

---

### Task 12: 全体回帰 + REVIEW ゲート + 実機検証 + 記録

**Files:**
- なし（検証と記録のみ）

- [ ] **Step 1: lint / 型 / 全テスト**

```bash
.venv\Scripts\python -m ruff check .
.venv\Scripts\python -m mypy nous  # baseline 超過なし
.venv\Scripts\python -m pytest tests/unit -q  # 2258+ 基準・失敗0
```

- [ ] **Step 2: 実機検証 (spec 実機検証要件)**

1. 設定を `POST /api/chat/herta/config` で確認（spontaneous 1h / monologue ON が実効値に反映）
2. Playwright（Task 9 Step 5 の再確認・console errors 0）
3. A 検証: 内省発火後も last_conversation_time / last_activity が変わらないこと・emotion/body 減衰時計が内省でリセットされないこと（DB 値確認）

- [ ] **Step 3: #081 REVIEW（ora-1 セッション再利用）**

diff 全体と spec を渡して correctness 審査。PASS 以外は BLOCK → 修正ループ（max 3）。

- [ ] **Step 4: GATE**

`型チェック pass AND テスト失敗0 AND カバレッジ≥60% AND lint 0 AND format ok AND 契約テスト pass AND シークレット0 AND 監査≤moderate AND ドキュメント同期 AND 禁止操作なし`

- [ ] **Step 5: RECORD（nous 記憶）**

tags: `project:nous` + `task_state` + `decision`、kind=semantic、importance 0.75。content にコミットハッシュ群・検証結果・教訓（introspection.py ホットファイルの順序統制、cap 移動契約、_emit_tool_called source 引数追加の互換性）を含める。

---

## Self-Review 結果

- Spec 網羅: A1-A5→Task 1-4 / B→Task 4 / C→Task 8-9 / D→Task 6 / E→中断(実装なし) / F→Task 10-11 / G→Task 7 / H→Task 5。spec の実機検証要件 3 点→Task 4 Step 1 / Task 9 Step 5 / Task 12 Step 2。
- 型整合: `_format_prompt` / `prompt_override` / `_curiosity_tool_allowed` / `_cap_memory_texts` / `_parse_json_object` / `MemoryLLM.process(mode)` / `_context_update_skips` の 5 タプル — Task 間で名前統一。
- 既知の相互作用: Task 6→7 は introspection.py 同箇所（memory_texts 組み立て）を連続改変するため**必ずこの順で実行**。Task 8 の `_emit_tool_called` source 引数追加は既存呼び出し互換（デフォルト値）。
