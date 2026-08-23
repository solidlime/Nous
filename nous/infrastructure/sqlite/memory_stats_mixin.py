from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from nous.domain.shared.errors import RepositoryError
from nous.domain.shared.result import Failure, Result, Success
from nous.infrastructure.logging.structured import get_logger
from nous.infrastructure.sqlite._utils import _parse_json_list

if TYPE_CHECKING:
    from nous.domain.memory.entities import Memory

logger = get_logger(__name__)


class MemoryStatsMixin:
    """Mixin providing paginated queries, stats, search logging, and smart queries."""

    # ------------------------------------------------------------------
    # Paginated queries (dashboard)
    # ------------------------------------------------------------------

    def find_with_pagination(
        self,
        page: int = 1,
        per_page: int = 20,
        tag: str | None = None,
        query: str | None = None,
        sort_order: str = "desc",
    ) -> Result[tuple[list[Memory], int], RepositoryError]:
        """Return paginated memories with optional filtering.

        Returns (memories, total_count) tuple.
        """
        conditions: list[str] = [self._active_where()]
        params: list[str] = []

        if tag:
            conditions.append("tags LIKE ?")
            params.append(f"%{tag}%")
        if query:
            conditions.append("content LIKE ?")
            params.append(f"%{query}%")

        where_clause = " WHERE " + " AND ".join(conditions)
        order = "ASC" if sort_order.lower() == "asc" else "DESC"

        count_row = self._db.execute(
            f"SELECT COUNT(*) as cnt FROM memories{where_clause}",  # noqa: S608  # nosec B608 — variables are placeholder-protected, safe against SQL injection
            params,
        ).fetchone()
        total_count: int = count_row["cnt"]

        offset = (page - 1) * per_page
        rows = self._db.execute(
            f"SELECT * FROM memories{where_clause} ORDER BY updated_at {order} LIMIT ? OFFSET ?",  # order whitelisted; where_clause internally built; params bound  # nosec B608
            [*params, per_page, offset],
        ).fetchall()

        return Success(([self._row_to_memory(r) for r in rows], total_count))

    def get_all_tags(self) -> Result[list[str], RepositoryError]:
        """Return a deduplicated list of all tags used across memories."""
        rows = self._db.execute(
            f"SELECT tags FROM memories WHERE {self._active_where()}"  # values bound via sqlite params; identifiers from internal constants  # nosec B608
        ).fetchall()
        all_tags: set[str] = set()
        for row in rows:
            all_tags.update(_parse_json_list(row["tags"]))
        return Success(sorted(all_tags))

    def consume_memory(self, key: str) -> Result[None, RepositoryError]:
        """Mark a memory as consumed by setting last_consumed_at = now()."""  # noqa: D401
        try:
            now = datetime.now(UTC).isoformat()
            self._db.execute(
                "UPDATE memories SET last_consumed_at = ? WHERE key = ?",
                (now, key),
            )
            return Success(None)
        except Exception as e:
            logger.error("Failed to consume memory %s: %s", key, e)
            return Failure(RepositoryError(str(e)))

    def get_by_tags(self, tags: list[str], include_consumed: bool = False) -> Result[list[Memory], RepositoryError]:
        """Get memories that contain ALL specified tags."""
        if not tags:
            return Success([])
        match_conditions = ["tags LIKE ?" for _ in tags]
        params = [f'%"{t}"%' for t in tags]
        all_conditions = [self._active_where(), *match_conditions]
        if not include_consumed:
            all_conditions.append("last_consumed_at IS NULL")
        where = " AND ".join(all_conditions)
        rows = self._db.execute(
            f"SELECT * FROM memories WHERE {where} ORDER BY updated_at DESC",  # where built from internal conditions; params bound  # nosec B608
            params,
        ).fetchall()
        return Success([self._row_to_memory(r) for r in rows])

    # ------------------------------------------------------------------
    # Smart recent + Search log + Gap alert
    # ------------------------------------------------------------------

    def find_smart_recent(self, limit: int = 8) -> Result[list[Memory], RepositoryError]:
        """Get memories ranked by importance * recency * strength."""
        rows = self._db.execute(
            f"""
            SELECT m.*,
                m.importance * 0.4 +
                (1.0 / (1.0 + (julianday('now') - julianday(m.created_at)) * 0.1)) * 0.3 +
                COALESCE(ms.strength, 0.5) * 0.3 AS smart_score
            FROM memories m
            LEFT JOIN memory_strength ms ON m.key = ms.memory_key
            WHERE {self._active_where()}
            ORDER BY smart_score DESC
            LIMIT ?
            """,  # values bound via sqlite params; identifiers from internal constants  # nosec B608
            (limit,),
        ).fetchall()
        return Success([self._row_to_memory(r) for r in rows])

    def log_search(self, query: str, mode: str, result_count: int) -> Result[None, RepositoryError]:
        """Log a search query for topic detection."""
        try:
            self._db.execute(
                "INSERT INTO search_log (query, mode, result_count, searched_at) VALUES (?, ?, ?, datetime('now'))",
                (query, mode, result_count),
            )
            return Success(None)
        except Exception as e:
            logger.error("Failed to log search: %s", e)
            return Failure(RepositoryError(str(e)))

    def get_recent_searches(self, limit: int = 5) -> Result[list[dict], RepositoryError]:
        """Get recent search queries."""
        rows = self._db.execute(
            "SELECT query, mode, result_count, searched_at FROM search_log ORDER BY searched_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return Success([dict(r) for r in rows])

    def count_decayed_important(
        self, min_importance: float = 0.7, max_strength: float = 0.3
    ) -> Result[int, RepositoryError]:
        """Count important memories that have decayed below strength threshold."""
        row = self._db.execute(
            "SELECT COUNT(*) as cnt FROM memories m INNER JOIN memory_strength ms ON m.key = ms.memory_key WHERE m.importance >= ? AND ms.strength <= ?",
            (min_importance, max_strength),
        ).fetchone()
        return Success(row["cnt"] if row else 0)

    def get_memory_index(self) -> Result[dict, RepositoryError]:
        """Get compressed memory index for context snapshot."""
        total = self._db.execute(
            f"SELECT COUNT(*) as cnt FROM memories WHERE {self._active_where()}"  # values bound via params; identifiers from internal constants  # nosec B608
        ).fetchone()["cnt"]  # values bound via sqlite params; identifiers from internal constants  # nosec B608

        tag_rows = self._db.execute(f"""
            SELECT tags FROM memories WHERE {self._active_where()} AND tags IS NOT NULL AND tags != '' AND tags != '[]'
        """).fetchall()  # values bound via sqlite params; identifiers from internal constants  # nosec B608
        tag_dist: dict[str, int] = {}
        for row in tag_rows:
            try:
                tags = json.loads(row["tags"]) if isinstance(row["tags"], str) else row["tags"]
                if isinstance(tags, list):
                    for t in tags:
                        tag_dist[t] = tag_dist.get(t, 0) + 1
            except (json.JSONDecodeError, TypeError):
                pass
        top_tags = sorted(tag_dist.items(), key=lambda x: x[1], reverse=True)[:10]

        emotion_rows = self._db.execute(f"""
            SELECT emotion, COUNT(*) as cnt FROM memories
            WHERE {self._active_where()} AND emotion IS NOT NULL AND emotion != ''
            GROUP BY emotion ORDER BY cnt DESC
        """).fetchall()  # values bound via sqlite params; identifiers from internal constants  # nosec B608
        emotion_dist = [(r["emotion"], r["cnt"]) for r in emotion_rows[:8]]
        emotion_others = max(0, len(emotion_rows) - 8)

        timeline_rows = self._db.execute(f"""
            SELECT strftime('%Y-%m', created_at) as month, COUNT(*) as cnt
            FROM memories
            WHERE {self._active_where()} AND created_at >= datetime('now', '-12 months')
            GROUP BY month ORDER BY month
        """).fetchall()  # values bound via sqlite params; identifiers from internal constants  # nosec B608
        timeline = [(r["month"], r["cnt"]) for r in timeline_rows]

        high_imp = self._db.execute(
            f"SELECT COUNT(*) as cnt FROM memories WHERE {self._active_where()} AND importance >= 0.8"  # values bound via sqlite params; identifiers from internal constants  # nosec B608
        ).fetchone()["cnt"]

        return Success(
            {
                "total": total,
                "top_tags": top_tags,
                "emotion_dist": emotion_dist,
                "emotion_others": emotion_others,
                "timeline": timeline,
                "high_importance_count": high_imp,
            }
        )

    def find_relationship_highlights(self, limit: int = 5) -> Result[list, RepositoryError]:
        """Find important relationship-related memories."""
        rows = self._db.execute(
            f"""
            SELECT * FROM memories
            WHERE importance >= 0.7
            AND {self._active_where()}
            AND (
                tags LIKE '%relationship%'
                OR tags LIKE '%first_meeting%'
                OR tags LIKE '%milestone%'
                OR tags LIKE '%promise%'
                OR tags LIKE '%important_moment%'
                OR tags LIKE '%nickname%'
                OR tags LIKE '%shared_experience%'
            )
            ORDER BY importance DESC, created_at ASC
            LIMIT ?
        """,  # values bound via sqlite params; identifiers from internal constants  # nosec B608
            (limit,),
        ).fetchall()
        return Success([self._row_to_memory(r) for r in rows])

    def find_top_by_importance(self, limit: int = 15) -> Result[list[Memory], RepositoryError]:
        """Find memories ranked purely by importance descending."""
        rows = self._db.execute(
            f"SELECT * FROM memories WHERE {self._active_where()} ORDER BY importance DESC LIMIT ?",  # values bound via sqlite params; identifiers from internal constants  # nosec B608
            (limit,),
        ).fetchall()
        return Success([self._row_to_memory(r) for r in rows])
