from __future__ import annotations

from typing import TYPE_CHECKING

from nous.domain.shared.result import Result, Success
from nous.infrastructure.logging.structured import get_logger

if TYPE_CHECKING:
    from datetime import datetime

    from nous.domain.memory.entities import Memory
    from nous.domain.shared.errors import RepositoryError

logger = get_logger(__name__)


class MemorySearchMixin:
    """Mixin providing FTS and keyword search for SQLiteMemoryRepository."""

    def search_fts(
        self,
        query: str,
        top_k: int = 10,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
        valid_at: datetime | None = None,
    ) -> Result[list[tuple[Memory, float]], RepositoryError]:
        """FTS5 full-text search using BM25 ranking.

        Returns [(Memory, normalized_bm25_score), ...] sorted by relevance.
        Score normalized to 0-1 range via ``1 / (1 + |bm25|)``.

        When ``valid_at`` is specified, only memories whose validity window
        covers that timestamp are returned (bi-temporal filtering).
        """
        fts_query = self._sanitize_fts_query(query)
        if not fts_query:
            return Success([])

        conditions: list[str] = ["memories_fts MATCH ?"]
        params: list = [fts_query]

        # Exclude tombstoned
        conditions.append("m.lifecycle_status != 'tombstoned'")

        # Date range filter
        if date_from is not None or date_to is not None:
            if date_from is not None and date_to is not None:
                conditions.append("m.created_at BETWEEN ? AND ?")
                params.extend([date_from.isoformat(), date_to.isoformat()])
            elif date_from is not None:
                conditions.append("m.created_at >= ?")
                params.append(date_from.isoformat())
            elif date_to is not None:
                conditions.append("m.created_at <= ?")
                params.append(date_to.isoformat())

        # Temporal validity filter
        if valid_at is not None:
            iso = valid_at.isoformat()
            conditions.append("(m.valid_from IS NULL OR m.valid_from <= ?)")
            params.append(iso)
            conditions.append("(m.valid_until IS NULL OR m.valid_until > ?)")
            params.append(iso)

        where_clause = " AND ".join(conditions)
        rows = self._db.execute(
            f"""
            SELECT m.*, rank
            FROM memories_fts
            JOIN memories m ON m.key = memories_fts.memories_key
            WHERE {where_clause}
            ORDER BY rank
            LIMIT ?
            """,  # noqa: S608  # nosec B608 — variables are placeholder-protected, safe against SQL injection
            [*params, top_k],
        ).fetchall()

        scored: list[tuple[Memory, float]] = []
        for row in rows:
            memory = self._row_to_memory(row)
            bm25 = row["rank"]
            # BM25: lower = more relevant (usually -5 to 5)
            # Normalize to 0-1: 1/(1+|bm25|)
            score = 1.0 / (1.0 + abs(bm25))
            scored.append((memory, score))
        return Success(scored)

    @staticmethod
    def _sanitize_fts_query(query: str) -> str:
        """Convert a plain-text query to safe FTS5 MATCH syntax (AND logic).

        Splits on whitespace, double-quotes each term, and joins with ``AND``
        to ensure all terms must match. This protects against FTS5 special
        characters (``OR``, ``NOT``, ``*``, ``(...)``) while preserving
        Unicode text including Japanese.
        """
        terms = query.strip().split()
        if not terms:
            return ""
        escaped = []
        for t in terms:
            # Escape embedded double-quotes by doubling them (FTS5 convention)
            t = t.replace('"', '""')
            escaped.append(f'"{t}"')
        return " AND ".join(escaped)

    def search_keyword(
        self,
        query: str,
        limit: int = 10,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
        valid_at: datetime | None = None,
    ) -> Result[list[tuple[Memory, float]], RepositoryError]:
        """Search memories by keyword with relevance scoring.

        Multi-word queries use AND logic: all terms must appear in the content.
        Optionally filter by date range (created_at BETWEEN date_from AND date_to).
        When ``valid_at`` is specified, only memories whose validity window
        covers that timestamp are returned (bi-temporal filtering).
        """
        terms = [t for t in query.split() if t]
        if not terms:
            return Success([])
        # Each term must match independently (AND logic)
        conditions: list[str] = ["content LIKE ?" for _ in terms]  # noqa: UP028
        params: list[str] = list(f"%{t}%" for t in terms)

        # Exclude tombstoned memories
        conditions.append("lifecycle_status != 'tombstoned'")

        # Date range filter
        if date_from is not None or date_to is not None:
            if date_from is not None and date_to is not None:
                conditions.append("created_at BETWEEN ? AND ?")
                params.extend([date_from.isoformat(), date_to.isoformat()])
            elif date_from is not None:
                conditions.append("created_at >= ?")
                params.append(date_from.isoformat())
            elif date_to is not None:
                conditions.append("created_at <= ?")
                params.append(date_to.isoformat())

        # Temporal validity filter
        if valid_at is not None:
            iso = valid_at.isoformat()
            conditions.append("(valid_from IS NULL OR valid_from <= ?)")
            params.append(iso)
            conditions.append("(valid_until IS NULL OR valid_until > ?)")
            params.append(iso)

        where_clause = " AND ".join(conditions)
        rows = self._db.execute(
            f"SELECT * FROM memories WHERE {where_clause} ORDER BY updated_at DESC",  # noqa: S608  # nosec B608 — variables are placeholder-protected, safe against SQL injection
            tuple(params),
        ).fetchall()
        scored: list[tuple[Memory, float]] = []
        for row in rows:
            score = self._simple_relevance_score(row["content"], query)
            scored.append((self._row_to_memory(row), score))
        scored.sort(key=lambda x: x[1], reverse=True)
        return Success(scored[:limit])

    @staticmethod
    def _simple_relevance_score(content: str, query: str) -> float:
        """Simple relevance: count query term occurrences."""
        query_lower = query.lower()
        content_lower = content.lower()
        terms = query_lower.split()
        if not terms:
            return 0.0
        matches = sum(1 for t in terms if t in content_lower)
        return matches / len(terms)
