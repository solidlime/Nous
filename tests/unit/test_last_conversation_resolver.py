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
