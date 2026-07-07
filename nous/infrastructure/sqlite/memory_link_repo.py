"""SQLite repository for memory_links — Hebbian co-activation network persistence."""

from __future__ import annotations

from typing import TYPE_CHECKING

from nous.domain.memory.memory_link import MemoryLink

if TYPE_CHECKING:
    from nous.infrastructure.sqlite.connection import SQLiteConnection


class MemoryLinkRepository:
    """SQLite repository for associative memory links (Collins & Loftus 1975).

    Follows the existing project pattern of accepting ``SQLiteConnection``
    and using the ``_db`` property to access the per-persona memory database.
    """

    def __init__(self, connection: SQLiteConnection) -> None:
        self._conn = connection

    @property
    def _db(self):
        return self._conn.get_memory_db()

    # ------------------------------------------------------------------
    # Write operations
    # ------------------------------------------------------------------

    def upsert(self, source_key: str, target_key: str, link_type: str = "semantic") -> None:
        """Insert or Hebbian-boost a memory link.

        If the link already exists, increase its weight by 0.1 (capped at 1.0)
        and bump ``co_activation_count``.  Otherwise create a new link with
        weight 0.5.
        """
        existing = self._db.execute(
            "SELECT weight, co_activation_count FROM memory_links WHERE source_key=? AND target_key=? AND link_type=?",
            (source_key, target_key, link_type),
        ).fetchone()

        if existing:
            weight = min(1.0, existing["weight"] + 0.1)
            count = existing["co_activation_count"] + 1
            self._db.execute(
                "UPDATE memory_links SET weight=?, co_activation_count=?, last_activated=datetime('now') "
                "WHERE source_key=? AND target_key=? AND link_type=?",
                (weight, count, source_key, target_key, link_type),
            )
        else:
            self._db.execute(
                "INSERT INTO memory_links (source_key, target_key, weight, link_type, co_activation_count, last_activated) "
                "VALUES (?,?,?,?,?,datetime('now'))",
                (source_key, target_key, 0.5, link_type, 1),
            )
        self._db.commit()

    # ------------------------------------------------------------------
    # Read operations
    # ------------------------------------------------------------------

    def get_links(self, source_key: str) -> list[MemoryLink]:
        """Return all links originating from *source_key*."""
        rows = self._db.execute(
            "SELECT source_key, target_key, weight, link_type, co_activation_count, last_activated "
            "FROM memory_links WHERE source_key=?",
            (source_key,),
        ).fetchall()
        return [MemoryLink(*self._row_values(r)) for r in rows]

    def get_links_for_keys(self, keys: list[str]) -> list[MemoryLink]:
        """Return all links whose *source_key* is in *keys*."""
        if not keys:
            return []
        placeholders = ",".join("?" * len(keys))
        rows = self._db.execute(
            f"SELECT source_key, target_key, weight, link_type, co_activation_count, last_activated "
            f"FROM memory_links WHERE source_key IN ({placeholders})",
            keys,
        ).fetchall()
        return [MemoryLink(*self._row_values(r)) for r in rows]

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _row_values(row) -> tuple:
        """Extract ordered values from a sqlite3.Row for MemoryLink constructor."""
        return (
            row["source_key"],
            row["target_key"],
            row["weight"],
            row["link_type"],
            row["co_activation_count"],
            row["last_activated"],
        )
