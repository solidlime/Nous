from __future__ import annotations

from nous.domain.shared.errors import RepositoryError
from nous.domain.shared.result import Failure, Result, Success
from nous.domain.shared.time_utils import format_iso, get_now
from nous.infrastructure.logging.structured import get_logger

logger = get_logger(__name__)

# 常載プロフィールドキュメントの block 名（target: me / user に対応）
PROFILE_BLOCK_NAMES = ("me", "user")


class SQLiteBlockMixin:
    """Mixin providing memory block operations for SQLiteMemoryRepository.

    Blocks are keyed by ``(persona, block_name)``.  ``persona`` defaults to
    ``'default'`` everywhere so callers that predate per-persona blocks (HTTP
    API, dashboard) keep working unchanged.
    """

    def get_block(self, block_name: str, persona: str = "default") -> Result[dict | None, RepositoryError]:
        """Get a named memory block."""
        try:
            row = self._db.execute(
                "SELECT * FROM memory_blocks WHERE persona = ? AND block_name = ?", (persona, block_name)
            ).fetchone()
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
        persona: str = "default",
    ) -> Result[None, RepositoryError]:
        """Save or update a named memory block."""
        try:
            now = format_iso(get_now())
            self._db.execute(
                """
                INSERT INTO memory_blocks
                    (persona, block_name, content, block_type, max_tokens, priority,
                     created_at, updated_at, metadata)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(persona, block_name) DO UPDATE SET
                    content = excluded.content,
                    block_type = excluded.block_type,
                    max_tokens = excluded.max_tokens,
                    priority = excluded.priority,
                    updated_at = excluded.updated_at,
                    metadata = excluded.metadata
                """,
                (persona, block_name, content, block_type, max_tokens, priority, now, now, metadata),
            )
            return Success(None)
        except Exception as e:
            logger.error("Failed to save block %s: %s", block_name, e)
            return Failure(RepositoryError(str(e)))

    def list_blocks(self, persona: str = "default") -> Result[list[dict], RepositoryError]:
        """List all memory blocks for a persona."""
        try:
            rows = self._db.execute(
                "SELECT * FROM memory_blocks WHERE persona = ? ORDER BY priority DESC", (persona,)
            ).fetchall()
            return Success([dict(r) for r in rows])
        except Exception as e:
            logger.error("Failed to list blocks: %s", e)
            return Failure(RepositoryError(str(e)))

    def delete_block(self, block_name: str, persona: str = "default") -> Result[None, RepositoryError]:
        """Delete a named memory block."""
        try:
            self._db.execute("DELETE FROM memory_blocks WHERE persona = ? AND block_name = ?", (persona, block_name))
            return Success(None)
        except Exception as e:
            logger.error("Failed to delete block %s: %s", block_name, e)
            return Failure(RepositoryError(str(e)))

    # ------------------------------------------------------------------
    # Profile blocks (B-2) — 常載プロフィールドキュメント
    # ------------------------------------------------------------------

    def get_profile_blocks(self, persona: str = "default") -> Result[dict[str, dict], RepositoryError]:
        """Return ``{"me": {...}, "user": {...}}`` for the blocks that exist."""
        listed = self.list_blocks(persona)
        if not listed.is_ok:
            return Failure(listed.error)  # type: ignore[union-attr]
        return Success(
            {row["block_name"]: row for row in listed.value if row["block_name"] in PROFILE_BLOCK_NAMES}  # type: ignore[union-attr]
        )

    def upsert_profile_block(self, persona: str, name: str, content: str) -> Result[None, RepositoryError]:
        """Upsert a profile block (``block_type='profile'``, 全体リライト型)."""
        if name not in PROFILE_BLOCK_NAMES:
            return Failure(RepositoryError(f"Invalid profile block name: {name}"))
        return self.save_block(name, content, block_type="profile", persona=persona)
