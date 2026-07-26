from __future__ import annotations

import sqlite3

from nous.domain.memory.entities import MemoryStrength
from nous.domain.shared.errors import RepositoryError
from nous.domain.shared.result import Failure, Result, Success
from nous.domain.shared.time_utils import format_iso
from nous.infrastructure.logging.structured import get_logger

logger = get_logger(__name__)


class SQLiteStrengthMixin:
    """Mixin providing memory strength operations for SQLiteMemoryRepository."""

    def get_strength(self, key: str) -> Result[MemoryStrength | None, RepositoryError]:
        """Get the strength record for a memory."""
        try:
            row = self._db.execute("SELECT * FROM memory_strength WHERE memory_key = ?", (key,)).fetchone()
            if row is None:
                return Success(None)
            return Success(self._row_to_strength(row))
        except Exception as e:
            logger.error("Failed to get strength for %s: %s", key, e)
            return Failure(RepositoryError(str(e)))

    def save_strength(self, strength: MemoryStrength) -> Result[None, RepositoryError]:
        """Save or update a memory strength record."""
        try:
            self._db.execute(
                """
                INSERT OR REPLACE INTO memory_strength
                    (memory_key, strength, stability, last_decay, recall_count, last_recall,
                     last_utility, interference_count, link_count, emotion_peak, is_ltm,
                     valence)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    strength.memory_key,
                    strength.strength,
                    strength.stability,
                    format_iso(strength.last_decay) if strength.last_decay else None,
                    strength.recall_count,
                    format_iso(strength.last_recall) if strength.last_recall else None,
                    format_iso(strength.last_utility) if strength.last_utility else None,
                    strength.interference_count,
                    strength.link_count,
                    strength.emotion_peak,
                    int(strength.is_ltm),
                    strength.valence,
                ),
            )
            return Success(None)
        except sqlite3.IntegrityError as e:
            msg = str(e)
            if "FOREIGN KEY" in msg:
                logger.warning(
                    "FK violation saving strength for %s (memory may be deleted): %s",
                    strength.memory_key,
                    e,
                )
            else:
                logger.error("Failed to save strength for %s: %s", strength.memory_key, e)
            return Failure(RepositoryError(str(e)))
        except Exception as e:
            logger.error("Failed to save strength for %s: %s", strength.memory_key, e)
            return Failure(RepositoryError(str(e)))

    def get_all_strengths(self) -> Result[list[MemoryStrength], RepositoryError]:
        """Get all memory strength records."""
        try:
            rows = self._db.execute("SELECT * FROM memory_strength").fetchall()
            return Success([self._row_to_strength(r) for r in rows])
        except Exception as e:
            logger.error("Failed to get all strengths: %s", e)
            return Failure(RepositoryError(str(e)))

    def _row_to_strength(self, row) -> MemoryStrength:
        """Convert a database row to a MemoryStrength entity."""
        row_keys = row.keys() if hasattr(row, "keys") else []
        return MemoryStrength(
            memory_key=row["memory_key"],
            strength=row["strength"] or 1.0,
            stability=row["stability"] or 1.0,
            last_decay=self._parse_iso_or_none(row["last_decay"]),
            recall_count=row["recall_count"] or 0,
            last_recall=self._parse_iso_or_none(row["last_recall"]),
            last_utility=self._parse_iso_or_none(row["last_utility"]),
            interference_count=row["interference_count"] or 0,
            link_count=row["link_count"] or 0,
            emotion_peak=row["emotion_peak"] or 0.0,
            is_ltm=bool(row["is_ltm"]) if row["is_ltm"] is not None else False,
            valence=row["valence"] if "valence" in row_keys else 0.0,
        )
