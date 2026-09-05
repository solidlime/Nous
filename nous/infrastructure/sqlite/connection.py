from __future__ import annotations

import sqlite3
import threading
from pathlib import Path

from nous.infrastructure.logging.structured import get_logger
from nous.infrastructure.sqlite.schema import (
    _CHAT_SESSIONS_SCHEMA,
    _INVENTORY_SCHEMA,
    _MEMORY_SCHEMA,
)

logger = get_logger(__name__)


class _ThreadConnections(threading.local):
    """Per-thread connection cache (declared attrs keep mypy happy)."""

    connections: dict[str, sqlite3.Connection]


class SQLiteConnection:
    """SQLite connection manager with WAL mode and per-persona DB isolation.

    Connections are cached per thread (``threading.local``): each thread
    gets its own ``sqlite3.Connection`` with the default
    ``check_same_thread=True``, so connections are never shared across
    threads.

    Args:
        data_dir: Base directory for per-persona data (i.e. persona_dir,
                  typically ``{data_root}/persona``). DB files live at
                  ``{data_dir}/{persona}/memory.sqlite`` etc.
        persona: Persona identifier used to construct the DB path.
    """

    def __init__(self, data_dir: str, persona: str) -> None:
        self.data_dir = data_dir
        self.persona = persona
        self._local = _ThreadConnections()

    def get_memory_db(self) -> sqlite3.Connection:
        """Get connection to memory.sqlite for this persona."""
        return self._get_or_create(f"{self.persona}/memory.sqlite")

    def get_inventory_db(self) -> sqlite3.Connection:
        """Get connection to inventory.sqlite for this persona."""
        return self._get_or_create(f"{self.persona}/inventory.sqlite")

    def _thread_conns(self) -> dict[str, sqlite3.Connection]:
        try:
            return self._local.connections
        except AttributeError:
            self._local.connections = {}
            return self._local.connections

    def _get_or_create(self, relative_path: str) -> sqlite3.Connection:
        conns = self._thread_conns()
        if relative_path not in conns:
            db_path = Path(self.data_dir) / relative_path
            db_path.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(str(db_path), isolation_level=None)
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA foreign_keys=ON")
            conn.row_factory = sqlite3.Row
            conns[relative_path] = conn
            logger.info("SQLite connection opened: %s", db_path)
        return conns[relative_path]

    def initialize_schema(self) -> None:
        """Create all tables if they don't exist."""
        from nous.infrastructure.sqlite.migrations import run_migrations

        memory_conn = self.get_memory_db()
        memory_conn.executescript(_MEMORY_SCHEMA + _CHAT_SESSIONS_SCHEMA)
        self._init_fts_schema(memory_conn)
        memory_conn.execute(
            "CREATE TABLE IF NOT EXISTS _migration_version ("
            "    version INTEGER PRIMARY KEY,"
            "    applied_at TEXT NOT NULL"
            ")"
        )
        run_migrations(memory_conn, self.persona)
        logger.info("Memory schema initialized for persona '%s'", self.persona)

        inventory_conn = self.get_inventory_db()
        inventory_conn.executescript(_INVENTORY_SCHEMA)

        # Migration: accessories → accessory_1 rename (slot expansion v1)
        try:
            cursor = inventory_conn.execute("SELECT COUNT(*) as cnt FROM equipment_slots WHERE slot = 'accessories'")
            if cursor.fetchone()["cnt"] > 0:
                inventory_conn.execute("UPDATE equipment_slots SET slot = 'accessory_1' WHERE slot = 'accessories'")
                inventory_conn.execute("UPDATE equipment_history SET slot = 'accessory_1' WHERE slot = 'accessories'")
                inventory_conn.commit()
                logger.info("Migration: renamed 'accessories' slot to 'accessory_1'")
        except Exception as e:
            logger.warning("Migration 'accessories→accessory_1' skipped: %s", e)

        inventory_conn.commit()
        logger.info("Inventory schema initialized for persona '%s'", self.persona)

    def _init_fts_schema(self, conn: sqlite3.Connection) -> None:
        """Create FTS5 virtual table and sync triggers for full-text search.

        Uses a standalone FTS5 table (not external-content) with its own copy of
        ``content`` and a ``memories_key`` column for JOINs. Triggers use standard
        SQL ``DELETE FROM`` (the FTS5-specific ``'delete'`` command is not available
        in bundled libsqlite3 3.46).
        """
        conn.execute(
            """
            CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts USING fts5(
                content,
                memories_key UNINDEXED,
                tokenize='unicode61'
            )
            """
        )
        conn.execute(
            """
            CREATE TRIGGER IF NOT EXISTS memories_ai AFTER INSERT ON memories BEGIN
                INSERT INTO memories_fts(rowid, content, memories_key)
                VALUES (new.rowid, new.content, new.key);
            END
            """
        )
        conn.execute(
            """
            CREATE TRIGGER IF NOT EXISTS memories_ad AFTER DELETE ON memories BEGIN
                DELETE FROM memories_fts WHERE rowid = old.rowid;
            END
            """
        )
        conn.execute(
            """
            CREATE TRIGGER IF NOT EXISTS memories_au AFTER UPDATE ON memories BEGIN
                DELETE FROM memories_fts WHERE rowid = old.rowid;
                INSERT INTO memories_fts(rowid, content, memories_key)
                VALUES (new.rowid, new.content, new.key);
            END
            """
        )
        logger.info("FTS5 schema initialized for persona '%s'", self.persona)

    def close(self) -> None:
        """Close all connections owned by the calling thread."""
        conns = self._thread_conns()
        for path, conn in conns.items():
            try:
                conn.close()
                logger.info("SQLite connection closed: %s", path)
            except Exception as e:
                logger.warning("Error closing SQLite connection %s: %s", path, e)
        conns.clear()
