from __future__ import annotations

from nous.infrastructure.sqlite.base_repo import SQLiteRepository
from nous.infrastructure.sqlite.block_repo import SQLiteBlockMixin
from nous.infrastructure.sqlite.memory_aux_repo import MemoryAuxMixin
from nous.infrastructure.sqlite.memory_crud_repo import MemoryCrudMixin
from nous.infrastructure.sqlite.memory_search_repo import MemorySearchMixin
from nous.infrastructure.sqlite.strength_repo import SQLiteStrengthMixin


class SQLiteMemoryRepository(
    SQLiteRepository,
    SQLiteBlockMixin,
    SQLiteStrengthMixin,
    MemoryCrudMixin,
    MemorySearchMixin,
    MemoryAuxMixin,
):
    """SQLite-backed implementation of the MemoryRepository protocol.

    Composed from mixins:
    - MemoryCrudMixin: save, find_by_key, update, delete, count, etc.
    - MemorySearchMixin: FTS5 full-text search, keyword search
    - MemoryAuxMixin: versions, pagination, tags, stats, validity window
    """
