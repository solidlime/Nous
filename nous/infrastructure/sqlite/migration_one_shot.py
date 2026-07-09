"""One-shot migration: context_state speech/physical/mental -> memories.
TEMPORARY -- remove in next release after migration completes.
"""

from __future__ import annotations

import json
import sqlite3  # noqa: TC003  -- runtime usage for sqlite3.Connection
from datetime import datetime, timezone

_STATE_MIGRATION_MAP: dict[str, tuple[list[str], str]] = {
    "speech_style": (["speech_style", "speech"], "speech_style"),
    "physical_state": (["physical_state", "body"], "physical_state"),
    "mental_state": (["mental_state", "mind"], "mental_state"),
}


def migrate_context_state_to_memories(conn: sqlite3.Connection, persona: str) -> int:
    """Migrate existing context_state entries to memories.

    Creates one memory per state key (if value exists).
    Memories are created with last_consumed_at=NOW so they won't auto-inject
    on the first get_context call (user gets to see them in WebUI first).

    Returns count of migrated records.
    """
    count = 0
    now = datetime.now(timezone.utc).isoformat()  # noqa: UP017  -- explicit UTC

    for state_key, (tags, content_prefix) in _STATE_MIGRATION_MAP.items():
        row = conn.execute(
            "SELECT value, updated_at FROM context_state "
            "WHERE persona = ? AND key = ? "
            "ORDER BY updated_at DESC LIMIT 1",
            (persona, state_key),
        ).fetchone()

        if not row or not row[0]:
            continue

        # Check if already migrated (avoid duplicates)
        existing = conn.execute(
            "SELECT 1 FROM memories WHERE tags LIKE ? LIMIT 1",
            (f'%"{state_key}"%',),
        ).fetchone()
        if existing:
            continue

        memory_key = f"mig_one_shot_{persona}_{state_key}"
        conn.execute(
            "INSERT INTO memories (key, content, tags, importance, created_at, last_consumed_at) "
            "VALUES (?, ?, ?, 0.6, ?, ?)",
            (
                memory_key,
                f"{content_prefix}: {row[0]}",
                json.dumps(tags),
                row[1] or now,
                now,  # consumed -> won't auto-inject on first get_context
            ),
        )
        count += 1

    return count
