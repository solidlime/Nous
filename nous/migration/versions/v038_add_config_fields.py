from __future__ import annotations

from contextlib import suppress


def upgrade(db) -> None:
    """Add context_use_llm_summary, episode_consolidation_enabled,
    episode_search_enabled columns to chat_settings table.

    Existing rows get DEFAULT 1 for all three columns.
    """
    with suppress(Exception):
        db.execute(
            "ALTER TABLE chat_settings ADD COLUMN context_use_llm_summary "
            "INTEGER DEFAULT 1"
        )

    with suppress(Exception):
        db.execute(
            "ALTER TABLE chat_settings ADD COLUMN episode_consolidation_enabled "
            "INTEGER DEFAULT 1"
        )

    with suppress(Exception):
        db.execute(
            "ALTER TABLE chat_settings ADD COLUMN episode_search_enabled "
            "INTEGER DEFAULT 1"
        )

    db.commit()
