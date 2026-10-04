"""B-1: memory_blocks persona カラム追加 + PK (persona, block_name) マイグレーション."""

from __future__ import annotations

import sqlite3

import pytest

from nous.infrastructure.sqlite.connection import SQLiteConnection
from nous.infrastructure.sqlite.migrations import _migrate_memory_blocks_persona_v11

_LEGACY_DDL = (
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


def _legacy_db(path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute(_LEGACY_DDL)
    conn.execute(
        "INSERT INTO memory_blocks (block_name, content, block_type, created_at, updated_at, metadata)"
        " VALUES (?,?,?,?,?,?)",
        ("me", "旧データ", "custom", "2026-01-01T00:00:00", "2026-01-01T00:00:00", None),
    )
    conn.execute(
        "INSERT INTO memory_blocks (block_name, content, block_type, created_at, updated_at) VALUES (?,?,?,?,?)",
        ("user", "ユーザー旧データ", "custom", "2026-01-01T00:00:00", "2026-01-01T00:00:00"),
    )
    conn.commit()
    return conn


class TestMemoryBlocksPersonaMigration:
    def test_rows_preserved_with_default_persona(self, tmp_path):
        conn = _legacy_db(tmp_path / "legacy.sqlite")
        _migrate_memory_blocks_persona_v11(conn, "test")

        rows = conn.execute(
            "SELECT persona, block_name, content, metadata FROM memory_blocks ORDER BY block_name"
        ).fetchall()
        assert [r["block_name"] for r in rows] == ["me", "user"]
        assert all(r["persona"] == "default" for r in rows)
        assert rows[0]["content"] == "旧データ"
        # NULL metadata は DEFAULT に填め直す（NOT NULL 制約は無いが既存慣行に合わせる）
        assert rows[0]["metadata"] == "{}"

    def test_pk_is_persona_block_name(self, tmp_path):
        conn = _legacy_db(tmp_path / "legacy.sqlite")
        _migrate_memory_blocks_persona_v11(conn, "test")

        # 別 persona なら同名 block を許す
        conn.execute(
            "INSERT INTO memory_blocks (persona, block_name, content, created_at, updated_at)"
            " VALUES ('other', 'me', 'x', 'now', 'now')"
        )
        # 同一 persona の重複は PK 制約違反
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO memory_blocks (persona, block_name, content, created_at, updated_at)"
                " VALUES ('default', 'me', 'y', 'now', 'now')"
            )
        # persona デフォルト 'default'
        conn.execute(
            "INSERT INTO memory_blocks (block_name, content, created_at, updated_at) VALUES ('z', 'c', 'now', 'now')"
        )
        assert conn.execute("SELECT persona FROM memory_blocks WHERE block_name='z'").fetchone()[0] == "default"
        conn.close()

    def test_idempotent(self, tmp_path):
        conn = _legacy_db(tmp_path / "legacy.sqlite")
        _migrate_memory_blocks_persona_v11(conn, "test")
        _migrate_memory_blocks_persona_v11(conn, "test")
        assert conn.execute("SELECT COUNT(*) FROM memory_blocks").fetchone()[0] == 2
        cols = [r["name"] for r in conn.execute("PRAGMA table_info(memory_blocks)").fetchall()]
        assert "persona" in cols
        conn.close()

    def test_missing_table_is_noop(self, tmp_db):
        _migrate_memory_blocks_persona_v11(tmp_db, "test")  # 例外なし

    def test_fresh_schema_has_persona_pk(self, tmp_path):
        conn = SQLiteConnection(data_dir=str(tmp_path), persona="test")
        conn.initialize_schema()
        db = conn.get_memory_db()
        cols = [r["name"] for r in db.execute("PRAGMA table_info(memory_blocks)").fetchall()]
        assert cols[0] == "persona"
        assert conn  # keep ref alive
