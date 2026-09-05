"""Phase 3a wiring tests: Hebbian co-activation (tracker → link_service → memory_links).

Covers:
1. upsert_link atomic upsert (insert / accumulate / cap)
2. get_links_for_keys union read (co-occurrence base + persistent override + reverse expansion)
3. MemoryLinkService: tracker → Memory lookup → real DB rows, self-link skip, max-5 cap
4. session_id propagation: registry tool.called event → SessionEventRecorder persistence
"""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

import pytest

from nous.application.chat.tools.registry import ToolRegistry
from nous.application.event_bus import EventBus
from nous.application.session_event_recorder import SessionEventRecorder
from nous.domain.memory.entities import Memory
from nous.domain.memory.link_service import MemoryLinkService
from nous.domain.shared.time_utils import get_now
from nous.infrastructure.sqlite.entity_repo import SQLiteEntityRepository
from nous.infrastructure.sqlite.memory_repo import SQLiteMemoryRepository
from nous.infrastructure.sqlite.session_event_repo import SessionEventRepository


def _make_memory(key: str, content: str = "content") -> Memory:
    now = get_now()
    return Memory(key=key, content=content, created_at=now, updated_at=now)


def _make_entity(entity_id: str):
    from nous.domain.memory.graph import Entity

    return Entity(id=entity_id, entity_type="entity")


# ---------------------------------------------------------------------------
# 1. upsert_link
# ---------------------------------------------------------------------------


class TestUpsertLink:
    def test_insert_then_accumulate(self, sqlite_conn):
        repo = SQLiteEntityRepository(sqlite_conn)
        repo.upsert_link("a", "b", "semantic", strength=0.1)
        row = (
            sqlite_conn.get_memory_db()
            .execute("SELECT * FROM memory_links WHERE source_key='a' AND target_key='b'")
            .fetchone()
        )
        assert row["weight"] == pytest.approx(0.6)
        assert row["co_activation_count"] == 1

        repo.upsert_link("a", "b", "semantic", strength=0.1)
        row = (
            sqlite_conn.get_memory_db()
            .execute("SELECT * FROM memory_links WHERE source_key='a' AND target_key='b'")
            .fetchone()
        )
        assert row["weight"] == pytest.approx(0.7)
        assert row["co_activation_count"] == 2

    def test_weight_caps_at_one(self, sqlite_conn):
        repo = SQLiteEntityRepository(sqlite_conn)
        for _ in range(6):
            repo.upsert_link("a", "b", "semantic", strength=0.1)
        row = (
            sqlite_conn.get_memory_db()
            .execute("SELECT * FROM memory_links WHERE source_key='a' AND target_key='b'")
            .fetchone()
        )
        assert row["weight"] == 1.0
        assert row["co_activation_count"] == 6


# ---------------------------------------------------------------------------
# 2. get_links_for_keys union read
# ---------------------------------------------------------------------------


class TestGetLinksForKeysUnion:
    def test_empty_memory_links_cooccurrence_only(self, sqlite_conn):
        """Day-1 regression guard: memory_links空 → 共起エッジのみ（現行挙動と同一）."""
        repo = SQLiteEntityRepository(sqlite_conn)
        # a and b share entity "e1" (entity row must exist: FK on memory_entities)
        repo.save_entity(_make_entity("e1"))
        repo.link_memory_entity("a", "e1")
        repo.link_memory_entity("b", "e1")

        links = repo.get_links_for_keys(["a", "b"])
        pairs = {(lnk.source_key, lnk.target_key) for lnk in links}
        assert ("a", "b") in pairs
        assert ("b", "a") in pairs  # co-occurrence join yields both directions
        assert all(lnk.weight == 0.5 for lnk in links)

    def test_persistent_overrides_and_adds(self, sqlite_conn):
        """永続エッジ: 同一ペアは永続weight優先・entity非共有ペア追加・逆方向展開."""
        repo = SQLiteEntityRepository(sqlite_conn)
        # a-b share an entity (co-occurrence base), a-c do not
        repo.save_entity(_make_entity("e1"))
        repo.link_memory_entity("a", "e1")
        repo.link_memory_entity("b", "e1")
        # Hebbian: strengthen a-b beyond 0.5 and create a-c (no shared entity)
        repo.upsert_link("a", "b", "semantic", strength=0.1)  # weight 0.6
        repo.upsert_link("a", "c", "semantic", strength=0.1)  # weight 0.6

        links = repo.get_links_for_keys(["a"])
        by_pair = {(lnk.source_key, lnk.target_key): lnk for lnk in links}

        # persistent weight overrides co-occurrence for (a, b)
        assert by_pair[("a", "b")].weight == pytest.approx(0.6)
        # entity-less pair (a, c) added by persistent edge
        assert by_pair[("a", "c")].weight == pytest.approx(0.6)
        # reverse expansion of persistent edges
        assert by_pair[("c", "a")].weight == pytest.approx(0.6)
        assert by_pair[("b", "a")].weight == pytest.approx(0.6)


# ---------------------------------------------------------------------------
# 3. MemoryLinkService end-to-end (tracker → lookup → DB rows)
# ---------------------------------------------------------------------------


class TestLinkServiceHebbianWiring:
    def test_creates_links_from_tracker(self, sqlite_conn):
        memory_repo = SQLiteMemoryRepository(sqlite_conn)
        link_repo = SQLiteEntityRepository(sqlite_conn)
        tracker: list[str] = []
        service = MemoryLinkService(link_repo, [None], memory_repo=memory_repo, coaccess_tracker=tracker)

        m1 = _make_memory("memory_20250101000001", "first")
        m2 = _make_memory("memory_20250101000002", "second")
        memory_repo.save(m1)
        memory_repo.save(m2)
        tracker.extend([m1.key, m2.key])

        new_memory = _make_memory("memory_20250101000003", "new")
        memory_repo.save(new_memory)
        service._create_hebbian_links(new_memory)

        rows = (
            sqlite_conn.get_memory_db()
            .execute("SELECT source_key, target_key FROM memory_links WHERE source_key=?", (new_memory.key,))
            .fetchall()
        )
        targets = {r["target_key"] for r in rows}
        assert targets == {m1.key, m2.key}

    def test_self_link_skipped_and_cap_at_five_most_recent(self, sqlite_conn):
        """自己リンクskip＋上限5件は「最新」側から取る（トラッカー末尾=最新）."""
        memory_repo = SQLiteMemoryRepository(sqlite_conn)
        link_repo = SQLiteEntityRepository(sqlite_conn)
        tracker: list[str] = []
        service = MemoryLinkService(link_repo, [None], memory_repo=memory_repo, coaccess_tracker=tracker)

        new_memory = _make_memory("memory_20250101000000", "new")
        memory_repo.save(new_memory)
        # tracker: 4 old keys → new_memory (self) → 5 recent keys
        # self-exclusion first, then [-5:] → exactly the 5 recent keys
        old_keys = [f"memory_2025010100001{i}" for i in range(4)]
        recent_keys = [f"memory_2025010100002{i}" for i in range(5)]
        for k in [*old_keys, new_memory.key, *recent_keys]:
            memory_repo.save(_make_memory(k))
        tracker.extend([*old_keys, new_memory.key, *recent_keys])

        service._create_hebbian_links(new_memory)

        rows = (
            sqlite_conn.get_memory_db()
            .execute("SELECT target_key FROM memory_links WHERE source_key=?", (new_memory.key,))
            .fetchall()
        )
        targets = {r["target_key"] for r in rows}
        assert targets == set(recent_keys)  # the 5 MOST RECENT, not the oldest
        assert new_memory.key not in targets  # self-link skipped
        assert not (targets & set(old_keys))  # oldest keys dropped by the cap

    def test_empty_tracker_creates_nothing(self, sqlite_conn):
        memory_repo = SQLiteMemoryRepository(sqlite_conn)
        link_repo = SQLiteEntityRepository(sqlite_conn)
        service = MemoryLinkService(link_repo, [None], memory_repo=memory_repo, coaccess_tracker=[])

        new_memory = _make_memory("memory_20250101000000", "new")
        memory_repo.save(new_memory)
        service._create_hebbian_links(new_memory)

        count = sqlite_conn.get_memory_db().execute("SELECT COUNT(*) FROM memory_links").fetchone()[0]
        assert count == 0


# ---------------------------------------------------------------------------
# F2: decay_stale_links (floor 0.5 invariant)
# ---------------------------------------------------------------------------


def _insert_link(db, src: str, dst: str, weight: float, last_activated: str) -> None:
    db.execute(
        "INSERT INTO memory_links (source_key, target_key, weight, link_type, co_activation_count, last_activated) "
        "VALUES (?, ?, ?, 'semantic', 1, ?)",
        (src, dst, weight, last_activated),
    )


class TestDecayStaleLinks:
    def test_recent_links_untouched(self, sqlite_conn):
        """7日以内のリンクは無影響."""
        repo = SQLiteEntityRepository(sqlite_conn)
        recent = "2099-01-01T00:00:00+00:00"
        _insert_link(sqlite_conn.get_memory_db(), "a", "b", 0.8, recent)
        repo.decay_stale_links("2000-01-01T00:00:00+00:00")
        row = sqlite_conn.get_memory_db().execute("SELECT weight FROM memory_links").fetchone()
        assert row["weight"] == pytest.approx(0.8)

    def test_stale_link_decayed_by_rate(self, sqlite_conn):
        """7日超のリンクは rate だけ減衰."""
        repo = SQLiteEntityRepository(sqlite_conn)
        stale = "2020-01-01T00:00:00+00:00"
        _insert_link(sqlite_conn.get_memory_db(), "a", "b", 0.8, stale)
        repo.decay_stale_links("2021-01-01T00:00:00+00:00", rate=0.005)
        row = sqlite_conn.get_memory_db().execute("SELECT weight FROM memory_links").fetchone()
        assert row["weight"] == pytest.approx(0.795)

    def test_floor_at_0_5(self, sqlite_conn):
        """floor 0.5 で停止——永続weight ≥ 0.5 の不変条件."""
        repo = SQLiteEntityRepository(sqlite_conn)
        stale = "2020-01-01T00:00:00+00:00"
        _insert_link(sqlite_conn.get_memory_db(), "a", "b", 0.52, stale)
        # 大きな rate でも floor を割らない
        repo.decay_stale_links("2021-01-01T00:00:00+00:00", rate=0.1)
        row = sqlite_conn.get_memory_db().execute("SELECT weight FROM memory_links").fetchone()
        assert row["weight"] == 0.5

    def test_boundary_timestamp_not_decayed(self, sqlite_conn):
        """last_activated == cutoff は減衰対象外（厳密な < 比较）."""
        repo = SQLiteEntityRepository(sqlite_conn)
        boundary = "2021-01-01T00:00:00+00:00"
        _insert_link(sqlite_conn.get_memory_db(), "a", "b", 0.8, boundary)
        repo.decay_stale_links(boundary)
        row = sqlite_conn.get_memory_db().execute("SELECT weight FROM memory_links").fetchone()
        assert row["weight"] == pytest.approx(0.8)

    def test_decay_worker_calls_decay_stale_links(self):
        """DecayWorker._decay_cycle が decay_stale_links を呼ぶこと."""
        from unittest.mock import MagicMock

        from nous.application.workers.decay_worker import DecayWorker

        ctx = MagicMock()
        ctx.memory_repo.get_all_strengths.return_value = MagicMock(is_ok=True, value=[])
        worker = DecayWorker(ctx, interval_seconds=9999)
        worker._decay_cycle()
        ctx.entity_repo.decay_stale_links.assert_called_once()


# ---------------------------------------------------------------------------
# 4. session_id propagation: registry → recorder
# ---------------------------------------------------------------------------


class TestSessionIdPropagation:
    def test_registry_event_session_id_persisted(self, sqlite_conn):
        bus = EventBus()
        repo = SessionEventRepository(sqlite_conn)
        recorder = SessionEventRecorder(bus, repo)
        recorder.start()

        ctx = MagicMock()
        ctx.event_bus = bus
        ctx.session_id = "sess_hebbian"

        registry = ToolRegistry(builtin_tools=[])
        result = asyncio.run(registry.execute(ctx, MagicMock(), "some_tool", {"a": 1}))
        assert result["status"] in ("ok", "error")

        events = repo.get_by_session("sess_hebbian")
        assert len(events) == 1
        assert events[0].session_id == "sess_hebbian"
        assert events[0].event_type == "tool.called"
