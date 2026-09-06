"""SQLite repository for the persistent enrichment queue.

Dedupes pending rows via the partial unique index
``ux_enrichment_queue_pending ON(memory_key) WHERE processed_at IS NULL``.
"""

from __future__ import annotations

from collections import namedtuple
from typing import TYPE_CHECKING

from nous.domain.shared.time_utils import format_iso, get_now, parse_iso

if TYPE_CHECKING:
    from nous.infrastructure.sqlite.connection import SQLiteConnection

PendingItem = namedtuple("PendingItem", ["memory_key", "enqueued_at"])


class EnrichmentQueueRepository:
    """SQLite repository for the persistent enrichment queue (memory.sqlite)."""

    def __init__(self, connection: SQLiteConnection) -> None:
        self._conn = connection

    @property
    def _db(self):
        return self._conn.get_memory_db()

    def enqueue(self, memory_key: str) -> None:
        """Add a pending item; no-op when the key is already pending."""
        self._db.execute(
            "INSERT OR IGNORE INTO enrichment_queue (memory_key, enqueued_at) VALUES (?, ?)",
            (memory_key, format_iso(get_now())),
        )

    def pending_keys(self) -> list[PendingItem]:
        """List distinct pending keys with their (earliest) enqueue time.

        No defer judgment here — the worker decides from the raw enqueued_at.
        """
        rows = self._db.execute(
            """
            SELECT memory_key, MIN(enqueued_at) AS enqueued_at
            FROM enrichment_queue
            WHERE processed_at IS NULL
            GROUP BY memory_key
            """
        ).fetchall()
        return [PendingItem(memory_key=r["memory_key"], enqueued_at=parse_iso(r["enqueued_at"])) for r in rows]

    def mark_processed(self, memory_key: str) -> None:
        """Mark all pending rows for the key as processed."""
        self._db.execute(
            "UPDATE enrichment_queue"
            " SET processed_at = ?"
            " WHERE memory_key = ? AND processed_at IS NULL",
            (format_iso(get_now()), memory_key),
        )

    def has_processed(self, memory_key: str) -> bool:
        """Whether any processed row exists for the key (re-enrich guard)."""
        row = self._db.execute(
            "SELECT 1 FROM enrichment_queue"
            " WHERE memory_key = ? AND processed_at IS NOT NULL LIMIT 1",
            (memory_key,),
        ).fetchone()
        return row is not None
