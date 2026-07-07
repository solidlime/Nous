from __future__ import annotations

from contextlib import suppress


def upgrade(db) -> None:
    """Add kind column for episodic/semantic/procedural/prospective memory types."""
    with suppress(Exception):
        db.execute("ALTER TABLE memories ADD COLUMN kind TEXT NOT NULL DEFAULT 'semantic'")
    with suppress(Exception):
        db.execute("ALTER TABLE memories ADD COLUMN episodic_time TEXT")
    with suppress(Exception):
        db.execute("ALTER TABLE memories ADD COLUMN episodic_place TEXT")
    with suppress(Exception):
        db.execute("ALTER TABLE memories ADD COLUMN episodic_people TEXT")
    with suppress(Exception):
        db.execute("CREATE INDEX IF NOT EXISTS idx_memories_kind ON memories(kind)")

    # Normalize NULLs to default
    db.execute("UPDATE memories SET kind = 'semantic' WHERE kind IS NULL")

    db.commit()
