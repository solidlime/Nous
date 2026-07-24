"""Database migration routines for Nous SQLite stores.

All functions are designed to be *idempotent* — safe to run multiple
times against the same database.
"""

from __future__ import annotations

import sqlite3
from typing import TYPE_CHECKING

from nous.infrastructure.logging.structured import get_logger

if TYPE_CHECKING:
    pass

logger = get_logger(__name__)


def run_migrations(db_conn: sqlite3.Connection, persona: str) -> None:
    """Run all pending DB-side migrations on *memory* database *db_conn*.

    Parameters
    ----------
    db_conn:
        An open connection to the per-persona ``memory.sqlite`` database.
    persona:
        Persona identifier used for logging and one-shot migration scoping.
    """
    _migrate_add_last_consumed_at(db_conn)
    _migrate_fts_backfill(db_conn)
    _migrate_context_state_to_memories(db_conn, persona)
    logger.info("Migrations complete for persona '%s'", persona)


# ---------------------------------------------------------------------------
# Individual migration helpers  (all idempotent)
# ---------------------------------------------------------------------------


def _migrate_add_last_consumed_at(db_conn: sqlite3.Connection) -> None:
    """Add ``last_consumed_at`` column to ``memories`` if missing."""
    try:
        db_conn.execute("ALTER TABLE memories ADD COLUMN last_consumed_at TEXT")
        db_conn.commit()
        logger.info("Added last_consumed_at column to memories (migration)")
    except sqlite3.OperationalError:
        pass  # column already exists


def _migrate_fts_backfill(db_conn: sqlite3.Connection) -> None:
    """Backfill the FTS5 index from the ``memories`` table when empty.

    This handles the case of an existing database that was created before the
    FTS5 index was introduced.
    """
    count = db_conn.execute(
        "SELECT COUNT(*) as cnt FROM memories_fts"
    ).fetchone()["cnt"]
    if count > 0:
        return

    existing = db_conn.execute(
        "SELECT COUNT(*) as cnt FROM memories"
    ).fetchone()["cnt"]
    if existing > 0:
        db_conn.execute(
            "INSERT INTO memories_fts(rowid, content, memories_key) "
            "SELECT rowid, content, key FROM memories"
        )
        db_conn.commit()
        logger.info("FTS5 index backfilled: %d documents", existing)


def _migrate_context_state_to_memories(
    db_conn: sqlite3.Connection, persona: str
) -> None:
    """One-shot migration: transfer ``context_state`` records into ``memories``.

    This is a best-effort migration that silenty ignores failures so that it
    can be safely shipped inside the regular init path.
    """
    try:
        from nous.infrastructure.sqlite.migration_one_shot import (  # noqa: PLC0415
            migrate_context_state_to_memories,
        )

        migrated = migrate_context_state_to_memories(db_conn, persona)
        if migrated:
            db_conn.commit()
            logger.info(
                "One-shot migration: %d state records -> memories", migrated
            )
    except Exception:  # noqa: S110
        pass
