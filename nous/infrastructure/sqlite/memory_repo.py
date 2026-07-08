from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from nous.domain.memory.entities import Memory
from nous.domain.shared.errors import RepositoryError
from nous.domain.shared.result import Failure, Result, Success
from nous.domain.shared.time_utils import format_iso, get_now
from nous.infrastructure.logging.structured import get_logger
from nous.infrastructure.sqlite.block_repo import SQLiteBlockMixin
from nous.infrastructure.sqlite.strength_repo import SQLiteStrengthMixin

if TYPE_CHECKING:
    from datetime import datetime

    from nous.infrastructure.sqlite.connection import SQLiteConnection

logger = get_logger(__name__)


class SQLiteMemoryRepository(SQLiteBlockMixin, SQLiteStrengthMixin):
    """SQLite-backed implementation of the MemoryRepository protocol."""

    def __init__(self, connection: SQLiteConnection) -> None:
        self._conn = connection

    @property
    def _db(self):
        return self._conn.get_memory_db()

    @staticmethod
    def _active_where() -> str:
        """Return WHERE clause fragment to exclude tombstoned memories."""
        return "lifecycle_status != 'tombstoned'"

    # ------------------------------------------------------------------
    # Memory CRUD
    # ------------------------------------------------------------------

    def save(self, memory: Memory) -> Result[str, RepositoryError]:
        """Persist a Memory entity. Returns the memory key on success."""
        try:
            now = format_iso(get_now())
            self._db.execute(
                """
                INSERT OR REPLACE INTO memories (
                    key, content, created_at, updated_at, tags, importance,
                    emotion, emotion_intensity, physical_state, mental_state,
                    environment, relationship_status, source_context,
                    related_keys, summary_ref, equipped_items, access_count,
                    last_accessed, privacy_level, body_state, state_snapped_at,
                    lifecycle_status,
                    kind, episodic_time, episodic_place, episodic_people,
                    source_type, confidence, derived_from,
                    valid_from, valid_until
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    memory.key,
                    memory.content,
                    format_iso(memory.created_at),
                    now,
                    json.dumps(memory.tags, ensure_ascii=False),
                    memory.importance,
                    memory.emotion,
                    memory.emotion_intensity,
                    memory.physical_state,
                    memory.mental_state,
                    memory.environment,
                    memory.relationship_status,
                    memory.source_context,
                    json.dumps(memory.related_keys, ensure_ascii=False),
                    memory.summary_ref,
                    memory.equipped_items,
                    memory.access_count,
                    format_iso(memory.last_accessed) if memory.last_accessed else None,
                    memory.privacy_level,
                    json.dumps(memory.body_state, ensure_ascii=False) if memory.body_state else None,
                    format_iso(memory.state_snapped_at) if memory.state_snapped_at else None,
                    memory.lifecycle_status,
                    memory.kind,
                    memory.episodic_time,
                    memory.episodic_place,
                    json.dumps(memory.episodic_people, ensure_ascii=False) if memory.episodic_people else None,
                    memory.source_type,
                    memory.confidence,
                    memory.derived_from,
                    format_iso(memory.valid_from) if memory.valid_from else None,
                    format_iso(memory.valid_until) if memory.valid_until else None,
                ),
            )
            # T4-A: Insert initial memory_strength record so WebUI shows a
            # strength value immediately (before Ebbinghaus decay worker runs).
            # INSERT OR IGNORE preserves any existing record on re-save.
            self._db.execute(
                """
                INSERT OR IGNORE INTO memory_strength (memory_key, strength, stability, recall_count)
                VALUES (?, 1.0, 1.0, 0)
                """,
                (memory.key,),
            )
            self._db.commit()
            logger.info("Memory saved: %s", memory.key)
            return Success(memory.key)
        except Exception as e:
            self._db.rollback()
            logger.error("Failed to save memory %s: %s", memory.key, e)
            return Failure(RepositoryError(str(e)))

    def find_by_key(self, key: str) -> Result[Memory | None, RepositoryError]:
        """Find a single memory by its key."""
        try:
            row = self._db.execute("SELECT * FROM memories WHERE key = ?", (key,)).fetchone()
            if row is None:
                return Success(None)
            return Success(self._row_to_memory(row))
        except Exception as e:
            logger.error("Failed to find memory %s: %s", key, e)
            return Failure(RepositoryError(str(e)))

    def find_recent(self, limit: int = 10, offset: int = 0) -> Result[list[Memory], RepositoryError]:
        """Return the most recently updated memories with optional pagination offset."""
        try:
            rows = self._db.execute(
                f"SELECT * FROM memories WHERE {self._active_where()} ORDER BY updated_at DESC LIMIT ? OFFSET ?",
                (limit, offset),
            ).fetchall()
            return Success([self._row_to_memory(r) for r in rows])
        except Exception as e:
            logger.error("Failed to find recent memories: %s", e)
            return Failure(RepositoryError(str(e)))

    def find_by_tags(self, tags: list[str], limit: int = 10) -> Result[list[Memory], RepositoryError]:
        """Find memories that contain any of the specified tags."""
        try:
            rows = self._db.execute(
                f"SELECT * FROM memories WHERE {self._active_where()} ORDER BY updated_at DESC"
            ).fetchall()
            result: list[Memory] = []
            tag_set = set(tags)
            for row in rows:
                memory_tags = set(self._parse_json_list(row["tags"]))
                if memory_tags & tag_set:
                    result.append(self._row_to_memory(row))
                    if len(result) >= limit:
                        break
            return Success(result)
        except Exception as e:
            logger.error("Failed to find memories by tags %s: %s", tags, e)
            return Failure(RepositoryError(str(e)))

    def update(self, key: str, **kwargs: Any) -> Result[Memory, RepositoryError]:
        """Update specific fields of a memory."""
        try:
            existing = self._db.execute("SELECT * FROM memories WHERE key = ?", (key,)).fetchone()
            if existing is None:
                return Failure(RepositoryError(f"Memory not found: {key}"))

            updates: dict[str, Any] = {}
            for field, value in kwargs.items():
                if field in ("tags", "related_keys"):
                    updates[field] = json.dumps(value, ensure_ascii=False)
                elif field in ("created_at", "updated_at", "last_accessed") and value is not None:
                    updates[field] = format_iso(value) if not isinstance(value, str) else value
                elif field == "lifecycle_status":
                    updates[field] = str(value)
                else:
                    updates[field] = value
            updates["updated_at"] = format_iso(get_now())

            set_clause = ", ".join(f"{k} = ?" for k in updates)
            values = list(updates.values()) + [key]
            self._db.execute(
                f"UPDATE memories SET {set_clause} WHERE key = ?",  # noqa: S608  # nosec B608
                values,
            )
            self._db.commit()

            updated_row = self._db.execute("SELECT * FROM memories WHERE key = ?", (key,)).fetchone()
            logger.info("Memory updated: %s", key)
            return Success(self._row_to_memory(updated_row))
        except Exception as e:
            self._db.rollback()
            logger.error("Failed to update memory %s: %s", key, e)
            return Failure(RepositoryError(str(e)))

    def delete(self, key: str) -> Result[None, RepositoryError]:
        """Delete a memory and its strength record."""
        try:
            self._db.execute("DELETE FROM memory_strength WHERE memory_key = ?", (key,))
            self._db.execute("DELETE FROM memories WHERE key = ?", (key,))
            self._db.commit()
            logger.info("Memory deleted: %s", key)
            return Success(None)
        except Exception as e:
            self._db.rollback()
            logger.error("Failed to delete memory %s: %s", key, e)
            return Failure(RepositoryError(str(e)))

    def count(self) -> Result[int, RepositoryError]:
        """Count total memories."""
        try:
            row = self._db.execute(f"SELECT COUNT(*) as cnt FROM memories WHERE {self._active_where()}").fetchone()
            return Success(row["cnt"])
        except Exception as e:
            logger.error("Failed to count memories: %s", e)
            return Failure(RepositoryError(str(e)))

    def find_all(self) -> Result[list[Memory], RepositoryError]:
        """Return all memories."""
        try:
            rows = self._db.execute(
                f"SELECT * FROM memories WHERE {self._active_where()} ORDER BY updated_at DESC"
            ).fetchall()
            return Success([self._row_to_memory(r) for r in rows])
        except Exception as e:
            logger.error("Failed to find all memories: %s", e)
            return Failure(RepositoryError(str(e)))

    # ------------------------------------------------------------------
    # FTS5 full-text search
    # ------------------------------------------------------------------

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
        try:
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
                """,  # noqa: S608  # nosec B608
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
        except Exception as e:
            logger.error("FTS5 search failed for '%s': %s", query, e)
            return Failure(RepositoryError(str(e)))

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

    # ------------------------------------------------------------------
    # Keyword search
    # ------------------------------------------------------------------

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
        try:
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
                f"SELECT * FROM memories WHERE {where_clause} ORDER BY updated_at DESC",  # noqa: S608  # nosec B608
                tuple(params),
            ).fetchall()
            scored: list[tuple[Memory, float]] = []
            for row in rows:
                score = self._simple_relevance_score(row["content"], query)
                scored.append((self._row_to_memory(row), score))
            scored.sort(key=lambda x: x[1], reverse=True)
            return Success(scored[:limit])
        except Exception as e:
            logger.error("Failed to search memories for '%s': %s", query, e)
            return Failure(RepositoryError(str(e)))

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
            self._db.commit()
            logger.info(
                "Version %d saved for memory %s (%s)",
                version,
                memory_key,
                change_type,
            )
            return Success(None)
        except Exception as e:
            self._db.rollback()
            logger.error("Failed to save version for %s: %s", memory_key, e)
            return Failure(RepositoryError(str(e)))

    def get_versions(self, memory_key: str) -> Result[list[dict], RepositoryError]:
        """Get all version records for a memory, ordered by version."""
        try:
            rows = self._db.execute(
                "SELECT * FROM memory_versions WHERE memory_key = ? ORDER BY version ASC",
                (memory_key,),
            ).fetchall()
            return Success([dict(r) for r in rows])
        except Exception as e:
            logger.error("Failed to get versions for %s: %s", memory_key, e)
            return Failure(RepositoryError(str(e)))

    def get_version(self, memory_key: str, version: int) -> Result[dict | None, RepositoryError]:
        """Get a specific version record."""
        try:
            row = self._db.execute(
                "SELECT * FROM memory_versions WHERE memory_key = ? AND version = ?",
                (memory_key, version),
            ).fetchone()
            return Success(dict(row) if row else None)
        except Exception as e:
            logger.error(
                "Failed to get version %d for %s: %s",
                version,
                memory_key,
                e,
            )
            return Failure(RepositoryError(str(e)))

    def get_latest_version_number(self, memory_key: str) -> Result[int, RepositoryError]:
        """Get the latest version number for a memory, 0 if none."""
        try:
            row = self._db.execute(
                "SELECT MAX(version) as max_ver FROM memory_versions WHERE memory_key = ?",
                (memory_key,),
            ).fetchone()
            return Success(row["max_ver"] if row and row["max_ver"] is not None else 0)
        except Exception as e:
            logger.error(
                "Failed to get latest version for %s: %s",
                memory_key,
                e,
            )
            return Failure(RepositoryError(str(e)))

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
        try:
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
                f"SELECT COUNT(*) as cnt FROM memories{where_clause}",  # noqa: S608  # nosec B608
                params,
            ).fetchone()
            total_count: int = count_row["cnt"]

            offset = (page - 1) * per_page
            rows = self._db.execute(
                f"SELECT * FROM memories{where_clause} ORDER BY updated_at {order} LIMIT ? OFFSET ?",  # noqa: S608  # nosec B608
                [*params, per_page, offset],
            ).fetchall()

            return Success(([self._row_to_memory(r) for r in rows], total_count))
        except Exception as e:
            logger.error("Failed to find memories with pagination: %s", e)
            return Failure(RepositoryError(str(e)))

    def get_all_tags(self) -> Result[list[str], RepositoryError]:
        """Return a deduplicated list of all tags used across memories."""
        try:
            rows = self._db.execute(f"SELECT tags FROM memories WHERE {self._active_where()}").fetchall()
            all_tags: set[str] = set()
            for row in rows:
                all_tags.update(self._parse_json_list(row["tags"]))
            return Success(sorted(all_tags))
        except Exception as e:
            logger.error("Failed to get all tags: %s", e)
            return Failure(RepositoryError(str(e)))

    def get_by_tags(self, tags: list[str]) -> Result[list[Memory], RepositoryError]:
        """Get memories that contain ALL specified tags."""
        try:
            if not tags:
                return Success([])
            match_conditions = ["tags LIKE ?" for _ in tags]
            params = [f'%"{t}"%' for t in tags]
            all_conditions = [self._active_where(), *match_conditions]
            where = " AND ".join(all_conditions)
            rows = self._db.execute(
                f"SELECT * FROM memories WHERE {where} ORDER BY updated_at DESC",  # nosec B608
                params,
            ).fetchall()
            return Success([self._row_to_memory(r) for r in rows])
        except Exception as e:
            logger.error("Failed to get memories by tags %s: %s", tags, e)
            return Failure(RepositoryError(str(e)))

    # ------------------------------------------------------------------
    # Smart recent + Search log + Gap alert
    # ------------------------------------------------------------------

    def find_smart_recent(self, limit: int = 8) -> Result[list[Memory], RepositoryError]:
        """Get memories ranked by importance * recency * strength."""
        try:
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
        except Exception as e:
            logger.error("Failed to get smart recent: %s", e)
            return Failure(RepositoryError(str(e)))

    def log_search(self, query: str, mode: str, result_count: int) -> Result[None, RepositoryError]:
        """Log a search query for topic detection."""
        try:
            self._ensure_search_log_table()
            self._db.execute(
                "INSERT INTO search_log (query, mode, result_count, searched_at) VALUES (?, ?, ?, datetime('now'))",
                (query, mode, result_count),
            )
            self._db.commit()
            return Success(None)
        except Exception as e:
            self._db.rollback()
            logger.error("Failed to log search: %s", e)
            return Failure(RepositoryError(str(e)))

    def get_recent_searches(self, limit: int = 5) -> Result[list[dict], RepositoryError]:
        """Get recent search queries."""
        try:
            self._ensure_search_log_table()
            rows = self._db.execute(
                "SELECT query, mode, result_count, searched_at FROM search_log ORDER BY searched_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
            return Success([dict(r) for r in rows])
        except Exception as e:
            logger.error("Failed to get recent searches: %s", e)
            return Failure(RepositoryError(str(e)))

    def count_decayed_important(
        self, min_importance: float = 0.7, max_strength: float = 0.3
    ) -> Result[int, RepositoryError]:
        """Count important memories that have decayed below strength threshold."""
        try:
            row = self._db.execute(
                "SELECT COUNT(*) as cnt FROM memories m INNER JOIN memory_strength ms ON m.key = ms.memory_key WHERE m.importance >= ? AND ms.strength <= ?",
                (min_importance, max_strength),
            ).fetchone()
            return Success(row["cnt"] if row else 0)
        except Exception as e:
            logger.error("Failed to count decayed: %s", e)
            return Failure(RepositoryError(str(e)))

    def _ensure_search_log_table(self) -> None:
        """Create search_log table if it doesn't exist (safety fallback)."""
        self._db.execute(
            """
            CREATE TABLE IF NOT EXISTS search_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                query TEXT NOT NULL,
                mode TEXT DEFAULT 'hybrid',
                result_count INTEGER DEFAULT 0,
                searched_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
            """
        )

    def get_memory_index(self) -> Result[dict, RepositoryError]:
        """Get compressed memory index for context snapshot."""
        try:
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
        except Exception as e:
            logger.error("Failed to get memory index: %s", e)
            return Failure(RepositoryError(str(e)))

    def find_relationship_highlights(self, limit: int = 5) -> Result[list, RepositoryError]:
        """Find important relationship-related memories."""
        try:
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
        except Exception as e:
            logger.error("Failed to find relationship highlights: %s", e)
            return Failure(RepositoryError(str(e)))

    def find_top_by_importance(self, limit: int = 15) -> Result[list[Memory], RepositoryError]:
        """Find memories ranked purely by importance descending."""
        try:
            rows = self._db.execute(
                f"SELECT * FROM memories WHERE {self._active_where()} ORDER BY importance DESC LIMIT ?",
                (limit,),
            ).fetchall()
            return Success([self._row_to_memory(r) for r in rows])
        except Exception as e:
            logger.error("Failed to find top by importance: %s", e)
            return Failure(RepositoryError(str(e)))

    def tombstone(self, key: str) -> Result[None, RepositoryError]:
        """Logically delete a memory by setting lifecycle_status to 'tombstoned'."""
        try:
            now = format_iso(get_now())
            self._db.execute(
                "UPDATE memories SET lifecycle_status = 'tombstoned', updated_at = ? WHERE key = ?",
                (now, key),
            )
            self._db.commit()
            logger.info("Memory tombstoned: %s", key)
            return Success(None)
        except Exception as e:
            self._db.rollback()
            logger.error("Failed to tombstone memory %s: %s", key, e)
            return Failure(RepositoryError(str(e)))

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
                f"UPDATE memories SET {set_clause} WHERE key = ?",  # noqa: S608  # nosec B608
                values,
            )
            self._db.commit()
            logger.info("Validity window updated for memory %s", memory_key)
            return Success(None)
        except Exception as e:
            self._db.rollback()
            logger.error("Failed to update validity window for %s: %s", memory_key, e)
            return Failure(RepositoryError(str(e)))

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_json_list(value: str | None) -> list[str]:
        """Safely parse a JSON-encoded list from a database field."""
        if not value:
            return []
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, list) else []
        except (json.JSONDecodeError, TypeError):
            return []

    @staticmethod
    def _parse_json_dict(value: str | None) -> dict | None:
        """Parse a JSON dict column. Returns None for empty/null."""
        if not value:
            return None
        try:
            raw = json.loads(value)
            return raw if isinstance(raw, dict) else None
        except (json.JSONDecodeError, TypeError):
            return None

    @staticmethod
    def _parse_iso_or_none(value: str | None):
        """Parse ISO datetime string or return None."""
        if not value:
            return None
        from nous.domain.shared.time_utils import parse_iso

        return parse_iso(value)

    def _row_to_memory(self, row) -> Memory:
        """Convert a database row to a Memory entity."""
        row_keys = row.keys() if hasattr(row, "keys") else []
        return Memory(
            key=row["key"],
            content=row["content"],
            created_at=self._parse_iso_or_none(row["created_at"]) or get_now(),
            updated_at=self._parse_iso_or_none(row["updated_at"]) or get_now(),
            importance=row["importance"] or 0.5,
            emotion=row["emotion"] or "neutral",
            emotion_intensity=row["emotion_intensity"] or 0.0,
            tags=self._parse_json_list(row["tags"]),
            privacy_level=row["privacy_level"] or "internal",
            physical_state=row["physical_state"],
            mental_state=row["mental_state"],
            environment=row["environment"],
            relationship_status=row["relationship_status"],
            source_context=row["source_context"],
            related_keys=self._parse_json_list(row["related_keys"]),
            summary_ref=row["summary_ref"],
            equipped_items=row["equipped_items"],
            access_count=row["access_count"] or 0,
            last_accessed=self._parse_iso_or_none(row["last_accessed"]) if "last_accessed" in row_keys else None,
            body_state=self._parse_json_dict(row["body_state"]) if "body_state" in row_keys else None,
            state_snapped_at=self._parse_iso_or_none(row["state_snapped_at"])
            if "state_snapped_at" in row_keys
            else None,
            lifecycle_status=row["lifecycle_status"] if "lifecycle_status" in row_keys else "active",
            # kind fields (safe defaults for old rows)
            kind=row["kind"] if "kind" in row_keys else "semantic",
            episodic_time=row["episodic_time"] if "episodic_time" in row_keys else None,
            episodic_place=row["episodic_place"] if "episodic_place" in row_keys else None,
            episodic_people=row["episodic_people"] if "episodic_people" in row_keys else None,
            # source provenance (safe defaults for old rows)
            source_type=row["source_type"] if "source_type" in row_keys else "user_stated",
            confidence=row["confidence"] if "confidence" in row_keys else 1.0,
            derived_from=row["derived_from"] if "derived_from" in row_keys else None,
            # temporal validity (safe defaults for old rows)
            valid_from=self._parse_iso_or_none(row["valid_from"]) if "valid_from" in row_keys else None,
            valid_until=self._parse_iso_or_none(row["valid_until"]) if "valid_until" in row_keys else None,
        )

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
