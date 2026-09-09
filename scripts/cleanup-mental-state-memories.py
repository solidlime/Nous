#!/usr/bin/env python
"""Tombstone legacy mental_state/physical_state memories.

背景: memory_extractor がかつて mental_state/physical_state を毎ターン
create_memory で恒久記憶化していた。現在は persona state フィールドに
移行済みのため、既存の揮発状態レコードを tombstone で排除する。

- デフォルトは DRY-RUN（対象全件を表示、削除しない）。--yes で実行。
- 削除は repo の tombstone 契約に従う（lifecycle_status='tombstoned' への
  UPDATE。物理 DELETE は行わない）。

Usage:
    python scripts/cleanup-mental-state-memories.py            # dry-run
    python scripts/cleanup-mental-state-memories.py --yes      # execute
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import UTC, datetime
from pathlib import Path

DEFAULT_DB = Path("data/persona/herta/memory.sqlite")

# (tag, content_prefix) のペアで対象を特定
TARGETS = [
    ("mental_state", "mental_state: "),
    ("physical_state", "physical_state: "),
]


def find_targets(db_path: Path) -> list[tuple[str, str, str]]:
    """Return (key, content, lifecycle_status) of matching active memories."""
    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute("SELECT key, content, tags, lifecycle_status FROM memories").fetchall()
    finally:
        conn.close()
    targets: list[tuple[str, str, str]] = []
    for key, content, tags_raw, lifecycle in rows:
        if lifecycle == "tombstoned":
            continue
        try:
            tags = json.loads(tags_raw) if tags_raw else []
        except (TypeError, json.JSONDecodeError):
            tags = []
        for tag, prefix in TARGETS:
            if tag in tags and isinstance(content, str) and content.startswith(prefix):
                targets.append((key, content, lifecycle))
                break
    return targets


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB, help="path to memory.sqlite")
    parser.add_argument("--yes", action="store_true", help="execute tombstone (default: dry-run)")
    args = parser.parse_args()

    if not args.db.exists():
        print(f"DB not found: {args.db}", file=sys.stderr)
        return 1

    targets = find_targets(args.db)
    if not targets:
        print("No matching memories. Nothing to do.")
        return 0

    print(f"{'[DRY-RUN]' if not args.yes else '[EXECUTE]'} {len(targets)} memories in {args.db}:")
    for key, content, lifecycle in targets:
        print(f"  {key}  (lifecycle={lifecycle})  {content[:80]}")

    if not args.yes:
        print("\nDry-run. Re-run with --yes to tombstone these memories.")
        return 0

    conn = sqlite3.connect(args.db)
    try:
        now = datetime.now(UTC).isoformat()
        for key, _, _ in targets:
            conn.execute(
                "UPDATE memories SET lifecycle_status = 'tombstoned', updated_at = ? WHERE key = ?",
                (now, key),
            )
        conn.commit()
        print(f"Tombstoned {len(targets)} memories.")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
