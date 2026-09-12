"""One-off migration: attribute historical introspection tool.called rows.

Rows in ``session_events`` with ``event_type='tool.called'`` whose
``metadata_json`` contains ``{"source": "introspection"}`` were recorded with a
missing chat session id ("unknown"). Move them to ``session_id='introspection'``
so the Activity feed shows them under a meaningful group.

persona is taken from ``metadata["persona"]`` **only** when the row's persona is
"unknown"; otherwise the existing persona is kept (never invented).

Note: rows recorded by newer code already carry ``metadata["source"]`` (the
emitter sets it), so they are identifiable; legacy rows with ``metadata_json``
NULL remain a no-op (no marker to match).

Usage::

    .venv\\Scripts\\python.exe scripts/migrate_toolcalled_attribution.py --dry-run
    .venv\\Scripts\\python.exe scripts/migrate_toolcalled_attribution.py

DB location: ``{data_root}/persona/{persona}/memory.sqlite`` (settings.data_root).
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterator

# Allow running as a plain script from any cwd.
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


def _iter_dbs(data_root: Path) -> Iterator[tuple[str, Path]]:
    base = data_root / "persona"
    if not base.exists():
        return
    for child in sorted(base.iterdir()):
        db = child / "memory.sqlite"
        if child.is_dir() and db.is_file():
            yield child.name, db


def _introspection_meta(metadata_json: str | None) -> tuple[bool, str | None]:
    """Return (is_introspection_source, metadata_persona|None)."""
    if not metadata_json:
        return False, None
    try:
        meta = json.loads(metadata_json)
    except (TypeError, ValueError):
        return False, None
    if not isinstance(meta, dict) or meta.get("source") != "introspection":
        return False, None
    persona = meta.get("persona")
    return True, persona if isinstance(persona, str) and persona else None


def _select_targets(conn: sqlite3.Connection) -> list[tuple[int, str]]:
    rows = conn.execute(
        "SELECT id, persona, metadata_json FROM session_events "
        "WHERE event_type = 'tool.called' AND session_id != 'introspection'"
    ).fetchall()
    targets: list[tuple[int, str]] = []
    for row in rows:
        is_intro, meta_persona = _introspection_meta(row["metadata_json"])
        if not is_intro:
            continue
        persona = meta_persona if (row["persona"] == "unknown" and meta_persona) else row["persona"]
        targets.append((row["id"], persona))
    return targets


def migrate_db(db_path: Path, dry_run: bool) -> tuple[int, int]:
    """Return (targets, migrated). No writes when dry_run."""
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        targets = _select_targets(conn)
        if dry_run or not targets:
            return len(targets), 0
        conn.executemany(
            "UPDATE session_events SET session_id = 'introspection', persona = ? WHERE id = ?",
            [(persona, row_id) for row_id, persona in targets],
        )
        conn.commit()
        return len(targets), len(targets)
    finally:
        conn.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="report only, no writes")
    parser.add_argument("--data-root", default=None, help="defaults to settings.data_root")
    args = parser.parse_args(argv)

    if args.data_root:
        data_root = Path(args.data_root)
    else:
        from nous.config.settings import get_settings

        data_root = Path(get_settings().data_root)

    print(f"data_root={data_root} dry_run={args.dry_run}")
    total_targets = total_migrated = 0
    for persona, db in _iter_dbs(data_root):
        targets, migrated = migrate_db(db, args.dry_run)
        print(f"  [{persona}] {db}: targets={targets} migrated={migrated}")
        total_targets += targets
        total_migrated += migrated
    print(f"TOTAL targets={total_targets} migrated={total_migrated} (dry_run={args.dry_run})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
