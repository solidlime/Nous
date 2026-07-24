"""SQLite repository base class with shared connection and DB access."""

from __future__ import annotations

import sqlite3
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from nous.infrastructure.sqlite.connection import SQLiteConnection


class SQLiteRepository:
    """Base class for SQLite-backed repositories.

    Subclasses set ``_db_method`` to ``"get_memory_db"`` or
    ``"get_inventory_db"`` to select the correct SQLite database.

    Mixins (e.g. SQLiteBlockMixin, SQLiteStrengthMixin) inherit ``_db``
    from the concrete repository — they do *not* need their own ``_db_method``.
    """

    _db_method: str = "get_memory_db"

    def __init__(self, connection: SQLiteConnection) -> None:
        self._conn = connection

    @property
    def _db(self):
        return getattr(self._conn, self._db_method)()

    # ------------------------------------------------------------------
    # Template method helpers for common query patterns
    # ------------------------------------------------------------------

    def _execute_query(self, sql: str, params: tuple = ()) -> list[sqlite3.Row]:
        """Execute SELECT and return all rows."""
        return self._db.execute(sql, params).fetchall()

    def _execute_single(self, sql: str, params: tuple = ()) -> sqlite3.Row | None:
        """Execute SELECT and return first row or None."""
        return self._db.execute(sql, params).fetchone()

    def _execute_write(self, sql: str, params: tuple = ()) -> None:
        """Execute INSERT/UPDATE/DELETE (returns no rows)."""
        self._db.execute(sql, params)
