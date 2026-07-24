from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    from datetime import datetime

    from nous.domain.memory.entities import Memory, MemoryStrength
    from nous.domain.shared.errors import RepositoryError
    from nous.domain.shared.result import Result


@runtime_checkable
class MemoryRepository(Protocol):
    """Core repository interface for memory CRUD, keyword search, and consume."""

    def save(self, memory: Memory) -> Result[str, RepositoryError]: ...

    def find_by_key(self, key: str) -> Result[Memory | None, RepositoryError]: ...

    def find_recent(self, limit: int = 10, offset: int = 0) -> Result[list[Memory], RepositoryError]: ...

    def find_by_tags(self, tags: list[str], limit: int = 10) -> Result[list[Memory], RepositoryError]: ...

    def update(self, key: str, **kwargs: Any) -> Result[Memory, RepositoryError]: ...

    def delete(self, key: str) -> Result[None, RepositoryError]: ...

    def count(self) -> Result[int, RepositoryError]: ...

    def find_all(self) -> Result[list[Memory], RepositoryError]: ...

    def search_keyword(
        self, query: str, limit: int = 10, date_from: datetime | None = None, date_to: datetime | None = None
    ) -> Result[list[tuple[Memory, float]], RepositoryError]: ...

    def consume_memory(self, key: str) -> Result[None, RepositoryError]:
        """Mark a memory as consumed by setting last_consumed_at = now(). Atomic, single-query."""
        ...


@runtime_checkable
class MemoryStrengthRepository(Protocol):
    """Repository interface for memory strength operations."""

    def get_strength(self, key: str) -> Result[MemoryStrength | None, RepositoryError]: ...

    def save_strength(self, strength: MemoryStrength) -> Result[None, RepositoryError]: ...

    def get_all_strengths(
        self,
    ) -> Result[list[MemoryStrength], RepositoryError]: ...


@runtime_checkable
class MemoryAuxiliaryRepository(Protocol):
    """Extended repository interface for blocks, versions, goals, pagination, etc."""

    # Memory blocks (Core Memory)
    def get_block(self, block_name: str) -> Result[dict | None, RepositoryError]: ...

    def save_block(
        self,
        block_name: str,
        content: str,
        block_type: str = "custom",
        max_tokens: int = 500,
        priority: int = 0,
        metadata: dict | None = None,
    ) -> Result[None, RepositoryError]: ...

    def list_blocks(self) -> Result[list[dict], RepositoryError]: ...

    def delete_block(self, block_name: str) -> Result[None, RepositoryError]: ...

    # Memory versions
    def save_version(
        self,
        memory_key: str,
        version: int,
        content: str,
        metadata: dict | None,
        changed_by: str,
        change_type: str,
    ) -> Result[None, RepositoryError]: ...

    def get_versions(self, memory_key: str) -> Result[list[dict], RepositoryError]: ...

    def get_version(self, memory_key: str, version: int) -> Result[dict | None, RepositoryError]: ...

    def get_latest_version_number(self, memory_key: str) -> Result[int, RepositoryError]: ...

    # Smart recent + Search log + Gap alert
    def find_smart_recent(self, limit: int = 8) -> Result[list[Memory], RepositoryError]: ...

    def log_search(self, query: str, mode: str, result_count: int) -> Result[None, RepositoryError]: ...

    def get_recent_searches(self, limit: int = 5) -> Result[list[dict], RepositoryError]: ...

    def count_decayed_important(
        self, min_importance: float = 0.7, max_strength: float = 0.3
    ) -> Result[int, RepositoryError]: ...

    # Context Intelligence
    def get_memory_index(self) -> Result[dict, RepositoryError]: ...

    def find_relationship_highlights(self, limit: int = 5) -> Result[list, RepositoryError]: ...

    def find_top_by_importance(self, limit: int = 15) -> Result[list[Memory], RepositoryError]: ...

    # Temporal validity window
    def update_validity_window(
        self,
        memory_key: str,
        valid_from: datetime | None = None,
        valid_until: datetime | None = None,
    ) -> Result[None, RepositoryError]: ...

    # Goals / Promises (planned: tag-based retrieval via get_by_tags)
    def get_goals(self) -> Result[list[dict], RepositoryError]: ...

    def get_promises(self) -> Result[list[dict], RepositoryError]: ...

    # Tags (include_consumed variant; note: find_by_tags is in core MemoryRepository)
    def get_by_tags(self, tags: list[str], include_consumed: bool = False) -> Result[list[Memory], RepositoryError]: ...

    # Pagination + all tags
    def find_with_pagination(
        self,
        page: int = 1,
        per_page: int = 20,
        tag: str | None = None,
        query: str | None = None,
        sort_order: str = "desc",
    ) -> Result[tuple[list[Memory], int], RepositoryError]: ...

    def get_all_tags(self) -> Result[list[str], RepositoryError]: ...

    # Lifecycle (logical delete)
    def tombstone(self, key: str) -> Result[None, RepositoryError]: ...

    # FTS5 full-text search
    def search_fts(
        self,
        query: str,
        top_k: int = 10,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
        valid_at: datetime | None = None,
    ) -> Result[list[tuple[Memory, float]], RepositoryError]: ...
