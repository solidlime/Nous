"""Unit tests for T2 hardening: thread-local connections, update allowlist,
migration guards, and the CLI stats-table allowlist."""

from __future__ import annotations

import sqlite3
import threading

import pytest

from nous.cli.__main__ import _COUNTABLE_TABLES, _print_count
from nous.infrastructure.sqlite.connection import SQLiteConnection
from nous.infrastructure.sqlite.memory_repo import SQLiteMemoryRepository
from nous.infrastructure.sqlite.migrations import (
    _ensure_version_table,
    _get_applied_versions,
    _record_version,
    run_migrations,
)

pytestmark = pytest.mark.unit


class TestThreadLocalConnections:
    def test_same_thread_reuses_connection(self, tmp_path):
        mgr = SQLiteConnection(str(tmp_path), "p1")
        assert mgr.get_memory_db() is mgr.get_memory_db()
        assert mgr.get_inventory_db() is not mgr.get_memory_db()
        mgr.close()

    def test_threads_get_distinct_connections(self, tmp_path):
        mgr = SQLiteConnection(str(tmp_path), "p1")
        main_conn = mgr.get_memory_db()
        seen: dict[str, sqlite3.Connection] = {}

        def worker():
            seen["conn"] = mgr.get_memory_db()
            mgr.close()

        t = threading.Thread(target=worker)
        t.start()
        t.join()
        assert seen["conn"] is not main_conn
        mgr.close()

    def test_cross_thread_use_raises(self, tmp_path):
        """Default check_same_thread=True: a conn from another thread refuses work."""
        mgr = SQLiteConnection(str(tmp_path), "p1")
        seen: dict[str, sqlite3.Connection] = {}

        def worker():
            seen["conn"] = mgr.get_memory_db()

        t = threading.Thread(target=worker)
        t.start()
        t.join()
        with pytest.raises(sqlite3.ProgrammingError):
            seen["conn"].execute("SELECT 1")
        mgr.close()

    def test_close_only_affects_calling_thread(self, tmp_path):
        mgr = SQLiteConnection(str(tmp_path), "p1")
        main_conn = mgr.get_memory_db()
        mgr.close()
        with pytest.raises(sqlite3.ProgrammingError):
            main_conn.execute("SELECT 1")
        # Manager still usable after close (lazy re-open).
        assert mgr.get_memory_db() is not None
        mgr.close()


class TestUpdateAllowlist:
    def test_unknown_field_raises_value_error(self, sqlite_conn):
        repo = SQLiteMemoryRepository(sqlite_conn)
        with pytest.raises(ValueError, match="Unknown memory fields"):
            repo.update("memory_nope", bogus_col="x")

    def test_allowed_fields_still_work(self, sqlite_conn):
        from nous.domain.memory.entities import Memory
        from nous.domain.shared.time_utils import get_now

        repo = SQLiteMemoryRepository(sqlite_conn)
        now = get_now()
        repo.save(Memory(key="k1", content="a", created_at=now, updated_at=now))
        result = repo.update("k1", content="b", importance=0.9, tags=["t"], kind="episodic")
        assert result.is_ok
        assert result.value.content == "b"

    def test_q8_service_fields_pass_through(self, sqlite_conn):
        """Oracle Q8 BLOCKER: service.update_memory fields must pass."""
        from nous.domain.memory.entities import Memory
        from nous.domain.shared.time_utils import format_iso, get_now

        repo = SQLiteMemoryRepository(sqlite_conn)
        now = get_now()
        repo.save(Memory(key="k8", content="a", created_at=now, updated_at=now))
        result = repo.update(
            "k8",
            updated_at=format_iso(now),
            emotion="joy",
            emotion_intensity=0.7,
            access_count=3,
            last_accessed=format_iso(now),
            privacy_level="private",
            lifecycle_status="active",
            summary_ref="sum-1",
            confidence=0.9,
        )
        assert result.is_ok

    def test_q8_key_and_created_at_still_rejected(self, sqlite_conn):
        # Note: `key` is update()'s lookup param so it cannot be passed as a
        # field at all (Python binds it positionally); only created_at reaches
        # the allowlist check.
        repo = SQLiteMemoryRepository(sqlite_conn)
        with pytest.raises(ValueError, match="Unknown memory fields"):
            repo.update("k8", created_at="2026-01-01T00:00:00")


class TestMigrationGuards:
    def test_get_applied_versions_empty_table(self, tmp_path):
        conn = sqlite3.connect(str(tmp_path / "m.sqlite"))
        conn.row_factory = sqlite3.Row
        conn.execute("CREATE TABLE _migration_version (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)")
        assert _get_applied_versions(conn) == set()
        conn.close()

    def test_a_backfilled_version_number_still_runs(self, tmp_path, monkeypatch):
        """MAX(version) で判定すると、欠番を後から埋めても既存 DB で走らない。"""
        import nous.infrastructure.sqlite.migrations as m

        ran: list[int] = []
        monkeypatch.setattr(
            m, "MIGRATIONS", [(1, "one", lambda c, p: ran.append(1)), (2, "two", lambda c, p: ran.append(2))]
        )
        conn = sqlite3.connect(str(tmp_path / "m.sqlite"))
        conn.row_factory = sqlite3.Row
        m._ensure_version_table(conn)
        m._record_version(conn, 1)
        m._record_version(conn, 2)
        # 既存 DB に後から v3（欠番だった番号）が現れた想定
        monkeypatch.setattr(
            m, "MIGRATIONS", [(1, "one", lambda c, p: ran.append(1)), (3, "three", lambda c, p: ran.append(3))]
        )
        m.run_migrations(conn, "p")
        assert ran == [3]
        conn.close()

    def test_ensure_version_table_atomic(self, tmp_path):
        conn = sqlite3.connect(str(tmp_path / "m.sqlite"))
        conn.row_factory = sqlite3.Row
        _ensure_version_table(conn)
        assert not conn.in_transaction
        assert _get_applied_versions(conn) == set()
        conn.close()

    def test_record_version_twice_is_ignored(self, tmp_path):
        """同じ version を2回記録しても IntegrityError で落ちない（競合時の保険）。"""
        conn = sqlite3.connect(str(tmp_path / "m.sqlite"))
        conn.row_factory = sqlite3.Row
        _ensure_version_table(conn)
        _record_version(conn, 7)
        _record_version(conn, 7)
        assert _get_applied_versions(conn) == {7}
        conn.close()

    def test_run_migrations_idempotent(self, tmp_path):
        mgr = SQLiteConnection(str(tmp_path), "p1")
        db = mgr.get_memory_db()
        db.execute("CREATE TABLE IF NOT EXISTS memories (key TEXT PRIMARY KEY, content TEXT, kind TEXT)")
        db.execute("CREATE TABLE IF NOT EXISTS memory_strength (memory_key TEXT)")
        db.execute("CREATE TABLE IF NOT EXISTS emotion_history (id INTEGER PRIMARY KEY, timestamp TEXT)")
        db.execute("CREATE TABLE IF NOT EXISTS memories_fts (content TEXT, memories_key TEXT)")
        run_migrations(db, "p1")
        first = _get_applied_versions(db)
        run_migrations(db, "p1")
        assert _get_applied_versions(db) == first
        mgr.close()


class TestCliTableAllowlist:
    def test_expected_tables_covered(self):
        assert {
            "memories",
            "memory_strength",
            "emotion_history",
            "context_state",
            "goals",
            "promises",
            "items",
            "equipment_slots",
            "equipment_history",
        } <= _COUNTABLE_TABLES

    def test_disallowed_table_reports_not_found(self, tmp_path, capsys):
        conn = sqlite3.connect(str(tmp_path / "m.sqlite"))
        _print_count(conn, "sqlite_master; DROP TABLE x; --", "Evil")
        out = capsys.readouterr().out
        assert "(table not found)" in out
        conn.close()
