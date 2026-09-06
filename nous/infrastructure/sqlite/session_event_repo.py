from __future__ import annotations

import json
from datetime import datetime
from typing import TYPE_CHECKING, Any

from nous.domain.memory.session_event import SessionEvent

if TYPE_CHECKING:
    from nous.infrastructure.sqlite.connection import SQLiteConnection


class SessionEventRepository:
    """SQLite repository for session_event records."""

    def __init__(self, connection: SQLiteConnection) -> None:
        self._conn = connection

    @property
    def _db(self):
        return self._conn.get_memory_db()

    # ------------------------------------------------------------------
    # Insert
    # ------------------------------------------------------------------

    def insert(self, event: SessionEvent) -> int:
        """Insert a session event and return its row id."""
        self._db.execute(
            """
            INSERT INTO session_events
                (session_id, persona, event_type, timestamp, summary, detail, metadata_json)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event.session_id,
                event.persona,
                event.event_type,
                event.timestamp.isoformat(),
                event.summary,
                event.detail,
                json.dumps(event.metadata, ensure_ascii=False) if event.metadata else None,
            ),
        )
        return self._db.execute("SELECT last_insert_rowid()").fetchone()[0]

    # ------------------------------------------------------------------
    # Query
    # ------------------------------------------------------------------

    def get_by_session(self, session_id: str, limit: int = 50) -> list[SessionEvent]:
        """Get events for a session, ordered by timestamp DESC."""
        rows = self._db.execute(
            "SELECT * FROM session_events WHERE session_id = ? ORDER BY timestamp DESC LIMIT ?",
            (session_id, limit),
        ).fetchall()
        return [self._row_to_event(r) for r in rows]

    def get_by_persona(
        self,
        persona: str,
        event_type: str | None = None,
        limit: int = 50,
    ) -> list[SessionEvent]:
        """Get events for a persona, optionally filtered by event_type."""
        if event_type:
            rows = self._db.execute(
                "SELECT * FROM session_events WHERE persona = ? AND event_type = ? ORDER BY timestamp DESC LIMIT ?",
                (persona, event_type, limit),
            ).fetchall()
        else:
            rows = self._db.execute(
                "SELECT * FROM session_events WHERE persona = ? ORDER BY timestamp DESC LIMIT ?",
                (persona, limit),
            ).fetchall()
        return [self._row_to_event(r) for r in rows]

    # ------------------------------------------------------------------
    # Paginated query
    # ------------------------------------------------------------------

    def get_by_persona_paginated(
        self,
        persona: str,
        limit: int = 50,
        offset: int = 0,
        event_type: str | None = None,
        order: str = "desc",
    ) -> tuple[list[SessionEvent], int]:
        """Get paginated events for a persona, with optional event_type filter.

        Returns ``(events, total_count)``. *order* must be ``"asc"`` or ``"desc"``.
        """
        direction = "ASC" if order == "asc" else "DESC"

        if event_type:
            where_clause = "WHERE persona = ? AND event_type = ?"
            params = (persona, event_type)
        else:
            where_clause = "WHERE persona = ?"
            params = (persona,)

        # Total count
        count_row = self._db.execute(
            f"SELECT COUNT(*) FROM session_events {where_clause}",  # nosec B608: internally-built clause
            params,
        ).fetchone()
        total = count_row[0] if count_row else 0

        # Paginated rows
        rows = self._db.execute(
            f"SELECT * FROM session_events {where_clause} ORDER BY timestamp {direction} LIMIT ? OFFSET ?",  # where_clause internally built; direction whitelisted; params bound  # nosec B608
            (*params, limit, offset),
        ).fetchall()

        return [self._row_to_event(r) for r in rows], total

    def last_activity_at(self, persona: str) -> datetime | None:
        """Most recent session event timestamp for the persona (None if any)."""
        row = self._db.execute(
            "SELECT MAX(timestamp) FROM session_events WHERE persona = ?",
            (persona,),
        ).fetchone()
        if row is None or row[0] is None:
            return None
        return datetime.fromisoformat(row[0])

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _row_to_event(row: Any) -> SessionEvent:
        """Convert a database row to a SessionEvent."""
        return SessionEvent(
            id=row["id"],
            session_id=row["session_id"],
            persona=row["persona"],
            event_type=row["event_type"],
            timestamp=datetime.fromisoformat(row["timestamp"]),
            summary=row["summary"],
            detail=row["detail"],
            metadata=json.loads(row["metadata_json"]) if row["metadata_json"] else None,
        )
