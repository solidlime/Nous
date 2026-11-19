"""kanban #80: 旧 DB で DDL が途中で止まり migration が走らない／persona の backfill 欠落."""

from __future__ import annotations

import sqlite3
from typing import TYPE_CHECKING

from nous.infrastructure.sqlite.connection import SQLiteConnection, _exec_schema

if TYPE_CHECKING:
    from pathlib import Path

_PERSONA = "herta"

# v5 以前の emotion_history（persona 列が無い）
_LEGACY_EMOTION_DDL = (
    "CREATE TABLE emotion_history ("
    "    id INTEGER PRIMARY KEY AUTOINCREMENT,"
    "    emotion_type TEXT NOT NULL,"
    "    intensity REAL DEFAULT 0.5,"
    "    timestamp TEXT NOT NULL,"
    "    trigger_memory_key TEXT,"
    "    context TEXT"
    ")"
)

# v11 以前の memory_blocks（persona 列が無い）
_LEGACY_BLOCK_DDL = (
    "CREATE TABLE memory_blocks ("
    "    block_name TEXT PRIMARY KEY,"
    "    content TEXT NOT NULL,"
    "    block_type TEXT DEFAULT 'custom',"
    "    max_tokens INTEGER DEFAULT 500,"
    "    priority INTEGER DEFAULT 0,"
    "    created_at TEXT NOT NULL,"
    "    updated_at TEXT NOT NULL,"
    "    metadata TEXT DEFAULT '{}'"
    ")"
)


def _legacy_db(tmp_path: Path) -> Path:
    path = tmp_path / _PERSONA / "db" / "memory.sqlite"
    path.parent.mkdir(parents=True)
    conn = sqlite3.connect(str(path))
    conn.execute(_LEGACY_EMOTION_DDL)  # pi-lens-ignore: python-sql-injection
    conn.execute("INSERT INTO emotion_history (emotion_type, timestamp) VALUES ('joy', '2026-01-01T00:00:00')")
    conn.execute(_LEGACY_BLOCK_DDL)  # pi-lens-ignore: python-sql-injection
    conn.execute(
        "INSERT INTO memory_blocks (block_name, content, created_at, updated_at)"
        " VALUES ('me', '旧データ', '2026-01-01T00:00:00', '2026-01-01T00:00:00')"
    )
    conn.commit()
    conn.close()
    return path


def _tables(conn: sqlite3.Connection) -> set[str]:
    return {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def test_legacy_db_gets_every_table_and_migrations(tmp_path: Path) -> None:
    """1 つの INDEX 失敗で残りの DDL と migration が消えないこと（B3）."""
    _legacy_db(tmp_path)

    manager = SQLiteConnection(str(tmp_path), _PERSONA)
    manager.initialize_schema()  # 例外を投げない

    conn = manager.get_memory_db()
    assert {
        "emotion_history",
        "memory_blocks",
        "session_events",
        "body_state_history",
        "chat_sessions",
        "_migration_version",
    } <= _tables(conn)
    applied = {row[0] for row in conn.execute("SELECT version FROM _migration_version")}
    assert 5 in applied and 11 in applied and 15 in applied


def test_legacy_emotion_and_block_rows_get_real_persona(tmp_path: Path) -> None:
    """v5/v11 が残した persona='' / 'default' を実 persona で埋めること（B4/B5）."""
    _legacy_db(tmp_path)

    manager = SQLiteConnection(str(tmp_path), _PERSONA)
    manager.initialize_schema()
    conn = manager.get_memory_db()

    assert [row[0] for row in conn.execute("SELECT persona FROM emotion_history")] == [_PERSONA]
    assert [row[0] for row in conn.execute("SELECT persona FROM memory_blocks")] == [_PERSONA]


def test_backfill_keeps_existing_persona_block_on_conflict(tmp_path: Path) -> None:
    """同名ブロックが既に実 persona に在るとき PK 衝突で落ちないこと（UPDATE OR IGNORE）."""
    manager = SQLiteConnection(str(tmp_path), _PERSONA)
    manager.initialize_schema()
    conn = manager.get_memory_db()

    now = "2026-01-01T00:00:00"
    conn.execute("DELETE FROM memory_blocks")
    conn.execute(
        "INSERT INTO memory_blocks (persona, block_name, content, created_at, updated_at)"
        " VALUES (?, 'me', '今のデータ', ?, ?)",
        (_PERSONA, now, now),
    )
    conn.execute(
        "INSERT INTO memory_blocks (persona, block_name, content, created_at, updated_at)"
        " VALUES ('default', 'me', '旧データ', ?, ?)",
        (now, now),
    )
    conn.execute("DELETE FROM _migration_version WHERE version = 15")

    manager.initialize_schema()  # 例外なし

    rows = dict(conn.execute("SELECT persona, content FROM memory_blocks").fetchall())
    assert rows[_PERSONA] == "今のデータ"
    assert rows["default"] == "旧データ"


def test_backfill_runs_on_already_migrated_db(tmp_path: Path) -> None:
    """既に v14 まで適用済みの DB でも v15 が空行を拾うこと."""
    manager = SQLiteConnection(str(tmp_path), _PERSONA)
    manager.initialize_schema()
    conn = manager.get_memory_db()

    conn.execute(
        "INSERT INTO emotion_history (emotion_type, timestamp, persona) VALUES ('sad', '2026-01-01T00:00:00', '')"
    )
    conn.execute("DELETE FROM _migration_version WHERE version = 15")

    manager.initialize_schema()

    assert {row[0] for row in conn.execute("SELECT persona FROM emotion_history")} == {_PERSONA}


def test_one_bad_statement_does_not_stop_the_rest(tmp_path: Path) -> None:
    """_exec_schema は失敗した文を飛ばして残りを適用する."""
    conn = sqlite3.connect(str(tmp_path / "t.sqlite"), isolation_level=None)
    _exec_schema(
        conn,
        "CREATE INDEX idx_bad ON no_such_table(col); CREATE TABLE kept (id INTEGER PRIMARY KEY);",
        "test",
    )

    assert "kept" in _tables(conn)
