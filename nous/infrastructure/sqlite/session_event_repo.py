from __future__ import annotations

import json
from datetime import datetime
from typing import TYPE_CHECKING, Any

from nous.domain.memory.session_event import SessionEvent
from nous.domain.memory.session_ids import INTERNAL_SESSION_PREFIXES

if TYPE_CHECKING:
    from nous.infrastructure.sqlite.connection import SQLiteConnection


# idle 判定の対象は「対話」のみ (spec A4)。tool.called / brain.* / session.* /
# events.ingested は内省・ツール実行でも idle タイマーをリセットさせない。
_IDLE_ACTIVITY_EVENT_TYPES = ("chat.message", "chat.llm_response")

# ユーザー発話の判定（kanban #44 / #65）。worker が内部で回すターン（self: /
# proactive: / activity:）も chat.message を発行するので、これらを数えると
# 自分で idle をリセットする自己ループになる。接頭辞は domain 側に集約。
_INTERNAL_SESSION_PREFIXES = INTERNAL_SESSION_PREFIXES


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
    # Delete
    # ------------------------------------------------------------------

    def delete_by_session(self, persona: str, session_id: str) -> None:
        """Delete all session events for one persona's session."""
        self._db.execute("DELETE FROM session_events WHERE persona=? AND session_id=?", (persona, session_id))

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
        since: str | None = None,
        until: str | None = None,
    ) -> list[SessionEvent]:
        """Get events for a persona, optionally filtered by event_type and time window.

        ``since``/``until`` are ISO-8601 strings in any offset. Comparison uses
        ``julianday()`` because ``timestamp`` mixes offsets (UTC ``Z`` from the pi
        hook, local ``+09:00`` from the workers), so string comparison is wrong.
        """
        clauses = ["persona = ?"]
        params: list[object] = [persona]
        if event_type:
            clauses.append("event_type = ?")
            params.append(event_type)
        if since:
            clauses.append("julianday(timestamp) >= julianday(?)")
            params.append(since)
        if until:
            clauses.append("julianday(timestamp) < julianday(?)")
            params.append(until)
        where = " AND ".join(clauses)  # nosec B608: clause strings are literals
        rows = self._db.execute(
            f"SELECT * FROM session_events WHERE {where} ORDER BY timestamp DESC LIMIT ?",  # nosec B608
            (*params, limit),
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

    def _max_timestamp(self, where: str, params: tuple[Any, ...]) -> datetime | None:
        row = self._db.execute(f"SELECT MAX(timestamp) FROM session_events WHERE {where}", params).fetchone()  # nosec B608: where は呼び出し側の定数、値はバインド
        if row is None or row[0] is None:
            return None
        return datetime.fromisoformat(row[0])

    def last_event_at(self, persona: str, event_type: str) -> datetime | None:
        """指定イベント種別の最終時刻（None なら記録なし）。"""
        return self._max_timestamp("persona = ? AND event_type = ?", (persona, event_type))

    def last_user_message_at(self, persona: str) -> datetime | None:
        """ユーザー自身の発言（``chat.message``）の最終時刻。"""
        prefixes = " AND ".join("session_id NOT LIKE ?" for _ in _INTERNAL_SESSION_PREFIXES)
        return self._max_timestamp(
            f"persona = ? AND event_type = 'chat.message' AND {prefixes}",
            (persona, *(f"{p}%" for p in _INTERNAL_SESSION_PREFIXES)),
        )

    def last_activity_at(self, persona: str) -> datetime | None:
        """Most recent chat turn timestamp for the persona (None if none)."""
        placeholders = ", ".join("?" for _ in _IDLE_ACTIVITY_EVENT_TYPES)
        return self._max_timestamp(
            f"persona = ? AND event_type IN ({placeholders})", (persona, *_IDLE_ACTIVITY_EVENT_TYPES)
        )

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
