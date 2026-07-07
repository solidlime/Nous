from __future__ import annotations

from contextlib import suppress


def upgrade(db) -> None:
    """Add source_type, confidence, derived_from for Bartlett source monitoring."""
    with suppress(Exception):
        db.execute("ALTER TABLE memories ADD COLUMN source_type TEXT NOT NULL DEFAULT 'user_stated'")
    with suppress(Exception):
        db.execute("ALTER TABLE memories ADD COLUMN confidence REAL DEFAULT 1.0")
    with suppress(Exception):
        db.execute("ALTER TABLE memories ADD COLUMN derived_from TEXT")

    # Normalize NULLs to default
    db.execute("UPDATE memories SET source_type = 'user_stated' WHERE source_type IS NULL")
    db.execute("UPDATE memories SET confidence = 1.0 WHERE confidence IS NULL")

    db.commit()
