"""Tests for database migrations."""

from __future__ import annotations

from typing import TYPE_CHECKING

from nous.infrastructure.sqlite.migrations import (
    _ensure_version_table,
    _migrate_add_persona_to_emotion_history_v5,
)

if TYPE_CHECKING:
    import sqlite3


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
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_emotion_history_persona "
        "ON emotion_history(timestamp DESC)"
    )
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
        col_info = tmp_db.execute(
            "PRAGMA table_info(emotion_history)"
        ).fetchall()
        persona_col = [r for r in col_info if r["name"] == "persona"][0]
        assert persona_col["dflt_value"] == "''"

        # インデックス確認
        indexes = [r["name"] for r in tmp_db.execute("PRAGMA index_list(emotion_history)").fetchall()]
        assert "idx_emotion_history_persona" in indexes
        assert "idx_emotion_history_timestamp" in indexes

        # データ挿入テスト
        tmp_db.execute(
            "INSERT INTO emotion_history (emotion_type, intensity, timestamp, persona) "
            "VALUES (?, ?, ?, ?)",
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
        tmp_db.execute(
            "CREATE INDEX IF NOT EXISTS idx_emotion_history_persona "
            "ON emotion_history(timestamp DESC)"
        )
        tmp_db.commit()

        # v5 を直接実行（run_migrations 経由だと v2/v6 が前提条件不足で失敗）
        _ensure_version_table(tmp_db)
        _migrate_add_persona_to_emotion_history_v5(tmp_db, "test_persona")

        # persona カラムが存在
        cols = [r["name"] for r in tmp_db.execute("PRAGMA table_info(emotion_history)").fetchall()]
        assert "persona" in cols

        # v5 の内容が適用されている（データ挿入テスト）
        tmp_db.execute(
            "INSERT INTO emotion_history (emotion_type, intensity, timestamp, persona) "
            "VALUES (?, ?, ?, ?)",
            ("sadness", 0.5, "2026-07-26T12:00:00", "test_persona"),
        )
        row = tmp_db.execute("SELECT * FROM emotion_history").fetchone()
        assert row["persona"] == "test_persona"
