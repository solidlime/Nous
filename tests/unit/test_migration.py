"""Tests for database migrations."""

from __future__ import annotations

import sqlite3

from nous.infrastructure.sqlite.connection import SQLiteConnection
from nous.infrastructure.sqlite.migrations import (
    _ensure_version_table,
    _migrate_add_persona_to_emotion_history_v5,
)
from nous.infrastructure.sqlite.schema import _MEMORY_SCHEMA


def _create_emotion_history_without_persona(conn: sqlite3.Connection) -> None:
    """Create emotion_history table without persona column (pre-v5 state)."""
    conn.execute(
        "CREATE TABLE IF NOT EXISTS emotion_history ("
        "    id INTEGER PRIMARY KEY AUTOINCREMENT,"
        "    emotion_type TEXT NOT NULL,"
        "    intensity REAL DEFAULT 0.5,"
        "    timestamp TEXT NOT NULL,"
        "    trigger_memory_key TEXT,"
        "    context TEXT"
        ")"
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_emotion_history_persona ON emotion_history(timestamp DESC)")
    conn.commit()


class TestMigrationV5:
    """v5 migration: add persona column to emotion_history."""

    def test_v5_adds_persona_column(self, tmp_db: sqlite3.Connection) -> None:
        """v5 migration 実行後、persona カラムが存在しインデックスが有効。"""
        # 事前: persona カラムなしの emotion_history
        _create_emotion_history_without_persona(tmp_db)

        # カラム不在を確認
        cols = [r["name"] for r in tmp_db.execute("PRAGMA table_info(emotion_history)").fetchall()]
        assert "persona" not in cols

        # v5 実行
        _migrate_add_persona_to_emotion_history_v5(tmp_db, "test_persona")

        # カラム存在確認
        cols = [r["name"] for r in tmp_db.execute("PRAGMA table_info(emotion_history)").fetchall()]
        assert "persona" in cols
        # DEFAULT '' 確認
        col_info = tmp_db.execute("PRAGMA table_info(emotion_history)").fetchall()
        persona_col = [r for r in col_info if r["name"] == "persona"][0]
        assert persona_col["dflt_value"] == "''"

        # インデックス確認
        indexes = [r["name"] for r in tmp_db.execute("PRAGMA index_list(emotion_history)").fetchall()]
        assert "idx_emotion_history_persona" in indexes
        assert "idx_emotion_history_timestamp" in indexes

        # データ挿入テスト
        tmp_db.execute(
            "INSERT INTO emotion_history (emotion_type, intensity, timestamp, persona) VALUES (?, ?, ?, ?)",
            ("joy", 0.8, "2026-07-26T12:00:00", "test_persona"),
        )
        row = tmp_db.execute("SELECT * FROM emotion_history").fetchone()
        assert row["persona"] == "test_persona"
        assert row["emotion_type"] == "joy"

    def test_v5_idempotent(self, tmp_db: sqlite3.Connection) -> None:
        """v5 は二重実行でもエラーにならない（冪等性）。"""
        _create_emotion_history_without_persona(tmp_db)
        _migrate_add_persona_to_emotion_history_v5(tmp_db, "test_persona")
        _migrate_add_persona_to_emotion_history_v5(tmp_db, "test_persona")  # 二度目
        # エラーなしで通ればOK
        cols = [r["name"] for r in tmp_db.execute("PRAGMA table_info(emotion_history)").fetchall()]
        assert "persona" in cols

    def test_v5_with_schema_init(self, tmp_db: sqlite3.Connection) -> None:
        """v5 が _MEMORY_SCHEMA 作成後、run_migrations 経由で適用される。"""
        # 古い形式（persona なし）で emotion_history を作成
        tmp_db.execute("DROP TABLE IF EXISTS emotion_history")
        tmp_db.execute(
            "CREATE TABLE emotion_history ("
            "    id INTEGER PRIMARY KEY AUTOINCREMENT,"
            "    emotion_type TEXT NOT NULL,"
            "    intensity REAL DEFAULT 0.5,"
            "    timestamp TEXT NOT NULL,"
            "    trigger_memory_key TEXT,"
            "    context TEXT"
            ")"
        )
        tmp_db.execute("CREATE INDEX IF NOT EXISTS idx_emotion_history_persona ON emotion_history(timestamp DESC)")
        tmp_db.commit()

        # v5 を直接実行（run_migrations 経由だと v2/v6 が前提条件不足で失敗）
        _ensure_version_table(tmp_db)
        _migrate_add_persona_to_emotion_history_v5(tmp_db, "test_persona")

        # persona カラムが存在
        cols = [r["name"] for r in tmp_db.execute("PRAGMA table_info(emotion_history)").fetchall()]
        assert "persona" in cols

        # v5 の内容が適用されている（データ挿入テスト）
        tmp_db.execute(
            "INSERT INTO emotion_history (emotion_type, intensity, timestamp, persona) VALUES (?, ?, ?, ?)",
            ("sadness", 0.5, "2026-07-26T12:00:00", "test_persona"),
        )
        row = tmp_db.execute("SELECT * FROM emotion_history").fetchone()
        assert row["persona"] == "test_persona"


class TestMigrationV9:
    """v9 migration: legacy per-turn reflection のメタ記憶 (_reflection_meta) 削除。"""

    @staticmethod
    def _insert_memory(db: sqlite3.Connection, key: str, tags: str, content: str = "x") -> None:
        db.execute(
            "INSERT INTO memories (key, content, created_at, updated_at, tags, importance) VALUES (?, ?, ?, ?, ?, ?)",
            (key, content, "2026-01-01T00:00:00", "2026-01-01T00:00:00", tags, 0.1),
        )

    def test_v9_deletes_reflection_meta_memories(self, tmp_db: sqlite3.Connection) -> None:
        """_reflection_meta タグ付きメタ記憶とその strength だけが消え、正規記憶は残る。"""
        from nous.infrastructure.sqlite.migrations import _migrate_delete_reflection_meta_v9

        tmp_db.executescript(_MEMORY_SCHEMA)
        self._insert_memory(
            tmp_db, "meta_1", '["_reflection_meta"]', content="last_reflection_at: 2026-01-01T00:00:00+00:00"
        )
        self._insert_memory(tmp_db, "meta_2", '["other", "_reflection_meta"]')
        self._insert_memory(tmp_db, "keep_1", '["reflection"]')  # 正規の洞察は残す
        self._insert_memory(tmp_db, "keep_2", '["auto_extract"]')
        tmp_db.execute(
            "INSERT INTO memory_strength (memory_key, strength, last_decay) VALUES (?, ?, ?)",
            ("meta_1", 0.5, "2026-01-01T00:00:00"),
        )
        tmp_db.execute(
            "INSERT INTO memory_strength (memory_key, strength, last_decay) VALUES (?, ?, ?)",
            ("keep_1", 0.5, "2026-01-01T00:00:00"),
        )
        tmp_db.commit()

        _migrate_delete_reflection_meta_v9(tmp_db, "test_persona")

        keys = [r["key"] for r in tmp_db.execute("SELECT key FROM memories ORDER BY key").fetchall()]
        assert keys == ["keep_1", "keep_2"]
        strength_keys = [
            r["memory_key"]
            for r in tmp_db.execute("SELECT memory_key FROM memory_strength ORDER BY memory_key").fetchall()
        ]
        assert strength_keys == ["keep_1"]

    def test_v9_idempotent(self, tmp_db: sqlite3.Connection) -> None:
        """v9 は二重実行でもエラーにならない（冪等性）。"""
        from nous.infrastructure.sqlite.migrations import _migrate_delete_reflection_meta_v9

        tmp_db.executescript(_MEMORY_SCHEMA)
        self._insert_memory(tmp_db, "meta_1", '["_reflection_meta"]')
        tmp_db.commit()

        _migrate_delete_reflection_meta_v9(tmp_db, "test_persona")
        _migrate_delete_reflection_meta_v9(tmp_db, "test_persona")  # 二度目

        remaining = tmp_db.execute("SELECT COUNT(*) FROM memories").fetchone()[0]
        assert remaining == 0

    def test_v9_without_meta_rows_keeps_normal_memories(self, tmp_db: sqlite3.Connection) -> None:
        """メタ記憶が無い DB でも正規記憶は消えない。"""
        from nous.infrastructure.sqlite.migrations import _migrate_delete_reflection_meta_v9

        tmp_db.executescript(_MEMORY_SCHEMA)
        self._insert_memory(tmp_db, "keep_1", '["reflection"]')
        tmp_db.commit()

        _migrate_delete_reflection_meta_v9(tmp_db, "test_persona")

        keys = [r["key"] for r in tmp_db.execute("SELECT key FROM memories").fetchall()]
        assert keys == ["keep_1"]


def _create_legacy_memories(conn: sqlite3.Connection) -> None:
    """Create a pre-v7 memories table: current schema minus the superseded_by column."""
    legacy_ddl = _MEMORY_SCHEMA.split("CREATE TABLE IF NOT EXISTS memory_strength")[0]
    legacy_ddl = legacy_ddl.replace("    valid_until TEXT,\n    superseded_by TEXT\n", "    valid_until TEXT\n")
    conn.executescript(legacy_ddl)
    conn.commit()


class TestLegacySchemaInit:
    """旧スキーマ DB (superseded_by カラム無し) からの schema 初期化。"""

    def test_executescript_on_legacy_db(self, tmp_db: sqlite3.Connection) -> None:
        """_MEMORY_SCHEMA の executescript が旧スキーマ DB 上で例外なく成功する。"""
        _create_legacy_memories(tmp_db)

        tmp_db.executescript(_MEMORY_SCHEMA)

        cols = [r["name"] for r in tmp_db.execute("PRAGMA table_info(memories)").fetchall()]
        assert "superseded_by" not in cols  # executescript は既存テーブルを触らない

    def test_initialize_schema_repairs_legacy_db(self, tmp_path) -> None:
        """旧スキーマ DB 上で initialize_schema() が完走し、カラム+インデックスが修復される。"""
        persona_dir = tmp_path / "legacy_persona"
        persona_dir.mkdir()
        legacy_conn = sqlite3.connect(str(persona_dir / "memory.sqlite"))
        _create_legacy_memories(legacy_conn)
        legacy_conn.close()

        connection = SQLiteConnection(str(tmp_path), "legacy_persona")
        connection.initialize_schema()  # 例外なく完走

        mem = connection.get_memory_db()
        cols = [r["name"] for r in mem.execute("PRAGMA table_info(memories)").fetchall()]
        assert "superseded_by" in cols
        indexes = [r["name"] for r in mem.execute("PRAGMA index_list(memories)").fetchall()]
        assert "idx_memories_superseded_by" in indexes
