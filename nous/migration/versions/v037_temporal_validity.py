from __future__ import annotations

from contextlib import suppress


def upgrade(db) -> None:
    """Add valid_from / valid_until columns to memories table for bi-temporal model.

    Existing rows implicitly get NULL = "valid since beginning of time, still valid".
    See nous/domain/memory/entities.py Memory.valid_from / valid_until.
    """
    with suppress(Exception):
        db.execute("ALTER TABLE memories ADD COLUMN valid_from TEXT")

    with suppress(Exception):
        db.execute("ALTER TABLE memories ADD COLUMN valid_until TEXT")

    db.commit()
