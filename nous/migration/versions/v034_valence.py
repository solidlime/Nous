from __future__ import annotations

from contextlib import suppress


def upgrade(db) -> None:
    """Add valence column for emotion-congruent recall (Bower 1981)."""
    with suppress(Exception):
        db.execute("ALTER TABLE memory_strength ADD COLUMN valence REAL DEFAULT 0.0")

    # Normalize NULLs to default
    db.execute("UPDATE memory_strength SET valence = 0.0 WHERE valence IS NULL")

    db.commit()
