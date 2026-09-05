from __future__ import annotations

from typing import TYPE_CHECKING

from nous.domain.shared.errors import RepositoryError
from nous.domain.shared.result import Failure, Result, Success
from nous.domain.shared.time_utils import format_iso, get_now
from nous.infrastructure.logging.structured import get_logger
from nous.infrastructure.sqlite.memory_stats_mixin import MemoryStatsMixin
from nous.infrastructure.sqlite.memory_version_mixin import MemoryVersionMixin

if TYPE_CHECKING:
    from datetime import datetime

logger = get_logger(__name__)


class MemoryAuxMixin(MemoryVersionMixin, MemoryStatsMixin):
    """Composite Mixin for all auxiliary memory operations.

    Composed from:
    - MemoryVersionMixin: version snapshot operations
    - MemoryStatsMixin: pagination, tags, stats, smart queries, search logging
    """

    # ------------------------------------------------------------------
    # Temporal validity window
    # ------------------------------------------------------------------

    def update_validity_window(
        self,
        memory_key: str,
        valid_from: datetime | None = None,
        valid_until: datetime | None = None,
        superseded_by: str | None = None,
    ) -> Result[None, RepositoryError]:
        """Set validity window for a memory.

        ``valid_until=None`` means "currently valid" (open-ended).
        ``valid_from=None`` leaves the existing value unchanged.
        ``superseded_by`` chains to the newer memory key; ``None`` leaves it unchanged.
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
            if superseded_by is not None:
                params["superseded_by"] = superseded_by

            set_clause = ", ".join(f"{k} = ?" for k in params)
            values = list(params.values()) + [memory_key]
            self._db.execute(
                f"UPDATE memories SET {set_clause} WHERE key = ?",  # set_clause keys from params dict; values bound via params  # nosec B608
                values,
            )
            logger.info("Validity window updated for memory %s", memory_key)
            return Success(None)
        except Exception as e:
            logger.error("Failed to update validity window for %s: %s", memory_key, e)
            return Failure(RepositoryError(str(e)))
