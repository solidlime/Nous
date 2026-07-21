from __future__ import annotations

from nous.domain.shared.errors import RepositoryError
from nous.domain.shared.result import Failure, Result, Success
from nous.domain.shared.time_utils import format_iso, get_now
from nous.infrastructure.logging.structured import get_logger

logger = get_logger(__name__)


class SQLiteBlockMixin:
    """Mixin providing memory block operations for SQLiteMemoryRepository."""

    def get_block(self, block_name: str) -> Result[dict | None, RepositoryError]:
        """Get a named memory block."""
        try:
            row = self._db.execute("SELECT * FROM memory_blocks WHERE block_name = ?", (block_name,)).fetchone()
            if row is None:
                return Success(None)
            return Success(dict(row))
        except Exception as e:
            logger.error("Failed to get block %s: %s", block_name, e)
            return Failure(RepositoryError(str(e)))

    def save_block(
        self,
        block_name: str,
        content: str,
        block_type: str = "custom",
        max_tokens: int = 500,
        priority: int = 0,
        metadata: str = "{}",
    ) -> Result[None, RepositoryError]:
        """Save or update a named memory block."""
        try:
            now = format_iso(get_now())
            self._db.execute(
                """
                INSERT INTO memory_blocks
                    (block_name, content, block_type, max_tokens, priority,
                     created_at, updated_at, metadata)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(block_name) DO UPDATE SET
                    content = excluded.content,
                    block_type = excluded.block_type,
                    max_tokens = excluded.max_tokens,
                    priority = excluded.priority,
                    updated_at = excluded.updated_at,
                    metadata = excluded.metadata
                """,
                (block_name, content, block_type, max_tokens, priority, now, now, metadata),
            )
            return Success(None)
        except Exception as e:
            logger.error("Failed to save block %s: %s", block_name, e)
            return Failure(RepositoryError(str(e)))

    def list_blocks(self) -> Result[list[dict], RepositoryError]:
        """List all memory blocks."""
        try:
            rows = self._db.execute("SELECT * FROM memory_blocks ORDER BY priority DESC").fetchall()
            return Success([dict(r) for r in rows])
        except Exception as e:
            logger.error("Failed to list blocks: %s", e)
            return Failure(RepositoryError(str(e)))

    def delete_block(self, block_name: str) -> Result[None, RepositoryError]:
        """Delete a named memory block."""
        try:
            self._db.execute("DELETE FROM memory_blocks WHERE block_name = ?", (block_name,))
            return Success(None)
        except Exception as e:
            logger.error("Failed to delete block %s: %s", block_name, e)
            return Failure(RepositoryError(str(e)))
