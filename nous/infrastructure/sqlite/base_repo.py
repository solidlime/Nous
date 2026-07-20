"""SQLite repository base class with shared connection and DB access."""

from __future__ import annotations

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
