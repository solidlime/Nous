from __future__ import annotations

import json
from typing import TYPE_CHECKING

from nous.domain.shared.errors import RepositoryError
from nous.domain.shared.result import Failure, Result, Success
from nous.domain.shared.time_utils import format_iso, get_now
from nous.infrastructure.logging.structured import get_logger

if TYPE_CHECKING:
    from nous.domain.memory.entities import Memory

logger = get_logger(__name__)


class MemoryVersionMixin:
    """Mixin providing memory versioning operations for SQLiteMemoryRepository."""

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
