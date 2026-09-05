"""Database migration routines for Nous SQLite stores.

All functions are designed to be *idempotent* — safe to run multiple
times against the same database.

Migration version tracking
--------------------------
Migrations are assigned sequential version numbers.  A ``_migration_version``
table (created by :meth:`~nous.infrastructure.sqlite.connection.SQLiteConnection.initialize_schema`)
records which versions have been applied.  On each run, only pending
migrations are executed.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime

from nous.infrastructure.logging.structured import get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def run_migrations(db_conn: sqlite3.Connection, persona: str) -> None:
    """Run all pending DB-side migrations on *memory* database *db_conn*.

    Parameters
    ----------
    db_conn:
        An open connection to the per-persona ``memory.sqlite`` database.
    persona:
        Persona identifier used for logging and one-shot migration scoping.
    """
    _ensure_version_table(db_conn)
    current = _get_current_version(db_conn)

    for version, desc, func in MIGRATIONS:
        if version > current:
            logger.info("Applying v%d: %s (persona='%s')", version, desc, persona)
            func(db_conn, persona)
            _record_version(db_conn, version)

    logger.info("Migrations complete for persona '%s'", persona)


# ---------------------------------------------------------------------------
# Version helpers
# ---------------------------------------------------------------------------


def _ensure_version_table(db_conn: sqlite3.Connection) -> None:
    """Create ``_migration_version`` if it somehow doesn't exist yet (atomic)."""
    own_txn = not db_conn.in_transaction
    if own_txn:
        db_conn.execute("BEGIN")
    try:
        db_conn.execute(
            "CREATE TABLE IF NOT EXISTS _migration_version (    version INTEGER PRIMARY KEY,    applied_at TEXT NOT NULL)"
        )
    except Exception:
        if own_txn:
            db_conn.rollback()
        raise
    if own_txn:
        db_conn.execute("COMMIT")


def _get_current_version(db_conn: sqlite3.Connection) -> int:
    """Return the highest applied migration version (0 = none)."""
    try:
        row = db_conn.execute("SELECT COALESCE(MAX(version), 0) AS v FROM _migration_version").fetchone()
        if row is None:
            return 0
        version = row["v"]
        return version if version is not None else 0
    except sqlite3.OperationalError:
        return 0


def _record_version(db_conn: sqlite3.Connection, version: int) -> None:
    """Record that *version* was successfully applied."""
    db_conn.execute(
        "INSERT INTO _migration_version(version, applied_at) VALUES (?, ?)",
        (version, datetime.now(UTC).isoformat()),
    )
    db_conn.commit()


# ---------------------------------------------------------------------------
# Individual migration helpers  (all idempotent)
# ---------------------------------------------------------------------------


def _migrate_add_last_consumed_at(
    db_conn: sqlite3.Connection,
    persona: str,  # noqa: ARG001
) -> None:
    """Add ``last_consumed_at`` column to ``memories`` if missing."""
    try:
        db_conn.execute("ALTER TABLE memories ADD COLUMN last_consumed_at TEXT")
        db_conn.commit()
        logger.info("Added last_consumed_at column to memories (migration)")
    except sqlite3.OperationalError:
        pass  # column already exists


def _migrate_fts_backfill(
    db_conn: sqlite3.Connection,
    persona: str,  # noqa: ARG001
) -> None:
    """Backfill the FTS5 index from the ``memories`` table when empty.

    This handles the case of an existing database that was created before the
    FTS5 index was introduced.
    """
    count = db_conn.execute("SELECT COUNT(*) as cnt FROM memories_fts").fetchone()["cnt"]
    if count > 0:
        return

    existing = db_conn.execute("SELECT COUNT(*) as cnt FROM memories").fetchone()["cnt"]
    if existing > 0:
        db_conn.execute(
            "INSERT INTO memories_fts(rowid, content, memories_key) SELECT rowid, content, key FROM memories"
        )
        db_conn.commit()
        logger.info("FTS5 index backfilled: %d documents", existing)


def _migrate_context_state_to_memories(db_conn: sqlite3.Connection, persona: str) -> None:
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
            logger.info("One-shot migration: %d state records -> memories", migrated)
    except Exception:  # noqa: S110
        pass


def _migrate_cleanup_orphan_strengths_v4(
    db_conn: sqlite3.Connection,
    persona: str,  # noqa: ARG001
) -> None:
    """Delete orphan memory_strength records whose memory_key has been removed."""
    cursor = db_conn.execute("DELETE FROM memory_strength WHERE memory_key NOT IN (SELECT key FROM memories)")
    delete_count = cursor.rowcount
    db_conn.commit()
    logger.info("Cleaned up %d orphan memory_strength records", delete_count)


def _migrate_add_persona_to_emotion_history_v5(
    db_conn: sqlite3.Connection,
    persona: str,  # noqa: ARG001
) -> None:
    """Add persona column to emotion_history and rebuild index."""
    try:
        db_conn.execute("ALTER TABLE emotion_history ADD COLUMN persona TEXT NOT NULL DEFAULT ''")
        db_conn.commit()
        logger.info("Added persona column to emotion_history (migration v5)")
    except sqlite3.OperationalError:
        pass  # column already exists

    # Rebuild the index: old idx_emotion_history_persona was on timestamp (misnamed)
    try:
        db_conn.execute("DROP INDEX IF EXISTS idx_emotion_history_persona")
        db_conn.execute("CREATE INDEX IF NOT EXISTS idx_emotion_history_persona ON emotion_history(persona)")
        db_conn.execute("CREATE INDEX IF NOT EXISTS idx_emotion_history_timestamp ON emotion_history(timestamp DESC)")
        db_conn.commit()
    except sqlite3.OperationalError:
        pass


def _migrate_remove_chat_kind_v6(
    db_conn: sqlite3.Connection,
    persona: str,  # noqa: ARG001
) -> None:
    """Replace kind='chat' with kind='semantic' for existing records.

    'chat' was removed from VALID_KINDS; existing records with this value
    are updated to the default 'semantic' kind. Idempotent — safe to run
    multiple times.
    """
    cursor = db_conn.execute("UPDATE memories SET kind = 'semantic' WHERE kind = 'chat'")
    affected = cursor.rowcount
    if affected:
        db_conn.commit()
        logger.info("Migration v6: updated %d records from kind='chat' to 'semantic'", affected)
    else:
        logger.info("Migration v6: no records with kind='chat' found")


def _migrate_add_superseded_by_v7(
    db_conn: sqlite3.Connection,
    persona: str,  # noqa: ARG001
) -> None:
    """Add ``superseded_by`` column + index to ``memories`` (bitemporal chain)."""
    try:
        db_conn.execute("ALTER TABLE memories ADD COLUMN superseded_by TEXT")
        db_conn.commit()
        logger.info("Added superseded_by column to memories (migration v7)")
    except sqlite3.OperationalError:
        pass  # column already exists
    try:
        db_conn.execute("CREATE INDEX IF NOT EXISTS idx_memories_superseded_by ON memories(superseded_by)")
        db_conn.commit()
    except sqlite3.OperationalError:
        pass


def _migrate_mot_thoughts_v8(
    db_conn: sqlite3.Connection,
    persona: str,  # noqa: ARG001
) -> None:
    """Create ``mot_thoughts`` table + indexes (MoT high-confidence traces)."""
    from nous.infrastructure.sqlite.mot_thoughts import ensure_thoughts_table  # noqa: PLC0415

    ensure_thoughts_table(db_conn)
    db_conn.commit()
    logger.info("Created mot_thoughts table (migration v8)")


# ---------------------------------------------------------------------------
# Migration registry  (ordered by version)
# ---------------------------------------------------------------------------
# Defined at module level so ``run_migrations`` can reference it.  All helper
# functions are already defined above by this point.

MIGRATIONS = [
    (1, "Add last_consumed_at column to memories", _migrate_add_last_consumed_at),
    (2, "Backfill FTS5 index", _migrate_fts_backfill),
    (3, "Transfer context_state records into memories", _migrate_context_state_to_memories),
    (4, "cleanup_orphan_strengths", _migrate_cleanup_orphan_strengths_v4),
    (5, "Add persona column to emotion_history", _migrate_add_persona_to_emotion_history_v5),
    (6, "Replace kind='chat' with 'semantic'", _migrate_remove_chat_kind_v6),
    (7, "Add superseded_by column to memories", _migrate_add_superseded_by_v7),
    (8, "Create mot_thoughts table", _migrate_mot_thoughts_v8),
]
