from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from nous.domain.shared.errors import RepositoryError
from nous.domain.shared.result import Failure, Result, Success
from nous.domain.shared.time_utils import format_iso, get_now
from nous.infrastructure.logging.structured import get_logger
from nous.infrastructure.sqlite._utils import _parse_json_list

if TYPE_CHECKING:
    from nous.domain.memory.entities import Memory

logger = get_logger(__name__)


class MemoryAuxMixin:
    """Mixin providing auxiliary operations for SQLiteMemoryRepository."""

    # ------------------------------------------------------------------
    # Memory versions
    # ------------------------------------------------------------------

    def save_version(
        self,
        memory_key: str,
        version: int,
        content: str,
        metadata: dict | None,
        changed_by: str,
        change_type: str,
    ) -> Result[None, RepositoryError]:
        """Save a version snapshot of a memory."""
        try:
            now = format_iso(get_now())
            self._db.execute(
                """
                INSERT INTO memory_versions
                    (memory_key, version, content, metadata,
                     changed_by, change_type, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    memory_key,
                    version,
                    content,
                    json.dumps(metadata, ensure_ascii=False) if metadata else None,
                    changed_by,
                    change_type,
                    now,
                ),
            )
            logger.info(
                "Version %d saved for memory %s (%s)",
                version,
                memory_key,
                change_type,
            )
            return Success(None)
        except Exception as e:
            logger.error("Failed to save version for %s: %s", memory_key, e)
            return Failure(RepositoryError(str(e)))

    def get_versions(self, memory_key: str) -> Result[list[dict], RepositoryError]:
        """Get all version records for a memory, ordered by version."""
        rows = self._db.execute(
            "SELECT * FROM memory_versions WHERE memory_key = ? ORDER BY version ASC",
            (memory_key,),
        ).fetchall()
        return Success([dict(r) for r in rows])

    def get_version(self, memory_key: str, version: int) -> Result[dict | None, RepositoryError]:
        """Get a specific version record."""
        row = self._db.execute(
            "SELECT * FROM memory_versions WHERE memory_key = ? AND version = ?",
            (memory_key, version),
        ).fetchone()
        return Success(dict(row) if row else None)

    def get_latest_version_number(self, memory_key: str) -> Result[int, RepositoryError]:
        """Get the latest version number for a memory, 0 if none."""
        row = self._db.execute(
            "SELECT MAX(version) as max_ver FROM memory_versions WHERE memory_key = ?",
            (memory_key,),
        ).fetchone()
        return Success(row["max_ver"] if row and row["max_ver"] is not None else 0)

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
            f"SELECT * FROM memories{where_clause} ORDER BY updated_at {order} LIMIT ? OFFSET ?",  # noqa: S608  # nosec B608 — variables are placeholder-protected, safe against SQL injection
            [*params, per_page, offset],
        ).fetchall()

        return Success(([self._row_to_memory(r) for r in rows], total_count))

    def get_all_tags(self) -> Result[list[str], RepositoryError]:
        """Return a deduplicated list of all tags used across memories."""
        rows = self._db.execute(f"SELECT tags FROM memories WHERE {self._active_where()}").fetchall()
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
            f"SELECT * FROM memories WHERE {where} ORDER BY updated_at DESC",  # nosec B608
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
            """,
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
        total = self._db.execute(f"SELECT COUNT(*) as cnt FROM memories WHERE {self._active_where()}").fetchone()[
            "cnt"
        ]

        tag_rows = self._db.execute(f"""
            SELECT tags FROM memories WHERE {self._active_where()} AND tags IS NOT NULL AND tags != '' AND tags != '[]'
        """).fetchall()
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
        """).fetchall()
        emotion_dist = [(r["emotion"], r["cnt"]) for r in emotion_rows[:8]]
        emotion_others = max(0, len(emotion_rows) - 8)

        timeline_rows = self._db.execute(f"""
            SELECT strftime('%Y-%m', created_at) as month, COUNT(*) as cnt
            FROM memories
            WHERE {self._active_where()} AND created_at >= datetime('now', '-12 months')
            GROUP BY month ORDER BY month
        """).fetchall()
        timeline = [(r["month"], r["cnt"]) for r in timeline_rows]

        high_imp = self._db.execute(
            f"SELECT COUNT(*) as cnt FROM memories WHERE {self._active_where()} AND importance >= 0.8"
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
        """,
            (limit,),
        ).fetchall()
        return Success([self._row_to_memory(r) for r in rows])

    def find_top_by_importance(self, limit: int = 15) -> Result[list[Memory], RepositoryError]:
        """Find memories ranked purely by importance descending."""
        rows = self._db.execute(
            f"SELECT * FROM memories WHERE {self._active_where()} ORDER BY importance DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return Success([self._row_to_memory(r) for r in rows])

    # ------------------------------------------------------------------
    # Temporal validity window
    # ------------------------------------------------------------------

    def update_validity_window(
        self,
        memory_key: str,
        valid_from: datetime | None = None,
        valid_until: datetime | None = None,
    ) -> Result[None, RepositoryError]:
        """Set validity window for a memory.

        ``valid_until=None`` means "currently valid" (open-ended).
        ``valid_from=None`` leaves the existing value unchanged.
        """
        try:
            existing = self._db.execute("SELECT * FROM memories WHERE key = ?", (memory_key,)).fetchone()
            if existing is None:
                return Failure(RepositoryError(f"Memory not found: {memory_key}"))

            now = format_iso(get_now())
            params: dict[str, object] = {"updated_at": now}

            if valid_from is not None:
                params["valid_from"] = format_iso(valid_from)
            if valid_until is not None:
                params["valid_until"] = format_iso(valid_until)
            else:
                # Explicitly set valid_until to NULL to mark as currently valid
                params["valid_until"] = None

            set_clause = ", ".join(f"{k} = ?" for k in params)
            values = list(params.values()) + [memory_key]
            self._db.execute(
                f"UPDATE memories SET {set_clause} WHERE key = ?",  # noqa: S608  # nosec B608 — variables are placeholder-protected, safe against SQL injection
                values,
            )
            logger.info("Validity window updated for memory %s", memory_key)
            return Success(None)
        except Exception as e:
            logger.error("Failed to update validity window for %s: %s", memory_key, e)
            return Failure(RepositoryError(str(e)))
