#!/usr/bin/env python3
"""v4.0 one-shot migration for audit H7: backfill ``project_path:<abs>`` tags.

Enumerates memories that carry a ``project:<slug>`` tag and, for those whose
content contains an absolute-path line (e.g. ``- パス: /root/workspace/Nous``),
adds a ``project_path:<abs パス>`` tag. Project identity can then be decided by
a structured tag match instead of natural-language path parsing (slug split
prevention), which is what make-project / session-start rely on.

Add-only, no deletion, idempotent — memories that already carry a
``project_path:`` tag are skipped. Uses the memory service API (no raw SQL).

Caveats — always review the dry-run output before ``--apply``:

- Only the **first** absolute-path line of a content is used. A memory listing
  several paths gets tagged with the first one only.
- Content that *mentions another project's path* (e.g. "that project lives in
  /root/X") can be mis-tagged. Dry-run prints every target before any write.
- Tag corrections afterwards are possible by hand via ``memory_update``
  (add/remove tags), so the migration itself is reversible.

Usage:
    uv run python scripts/migrate_project_path_tags.py            # dry-run (default)
    uv run python scripts/migrate_project_path_tags.py --apply    # write
    uv run python scripts/migrate_project_path_tags.py --apply --persona <name>
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import re
import sys
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from nous.application.use_cases import AppContext

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

logger = logging.getLogger("migrate_project_path_tags")

# ``パス: <abs>`` 行。先頭の箇条書き記号・全角/半角コロンを許容し、
# パスは空白・日本語句読点までを取る。
_PATH_LINE_RE = re.compile(r"^\s*-?\s*パス\s*[:：]\s*(/[^\s、。，,;；]+)")


def extract_project_path(content: str | None) -> str | None:
    """content 内の絶対パス行から abs パスを抽出する（無ければ None）。"""
    if not content:
        return None
    for line in content.splitlines():
        match = _PATH_LINE_RE.search(line)
        if match:
            path = match.group(1).rstrip("/")
            return path or "/"
    return None


def backfill_persona(ctx: AppContext, apply: bool) -> tuple[int, int, int]:
    """Return (targets, added, skipped). No writes when ``apply`` is False.

    targets: バックフィル対象（project タグあり・abs パス抽出可・未タグ）
    added:   実際にタグを追加した件数（dry-run では 0）
    skipped: 既に project_path タグ付き / abs パス無し
    """
    result = ctx.memory_service.get_by_tags(["project:"])
    if not result.is_ok:
        raise RuntimeError(f"get_by_tags failed: {result.error}")

    targets = added = skipped = 0
    for mem in result.value or []:
        tags = list(mem.tags or [])
        if any(tag.startswith("project_path:") for tag in tags):
            skipped += 1
            continue
        path = extract_project_path(mem.content)
        if not path:
            skipped += 1
            continue
        tag = f"project_path:{path}"
        if tag in tags:  # 冪等: 万一既存でも追加しない
            skipped += 1
            continue
        targets += 1
        if not apply:
            continue
        update = ctx.memory_service.update_memory(mem.key, tags=[*tags, tag])
        if update.is_ok:
            added += 1
        else:
            logger.warning("backfill failed key=%s: %s", mem.key, update.error)
    return targets, added, skipped


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="write the tags (default: dry-run)")
    parser.add_argument("--persona", default=None, help="persona to migrate (default: server default)")
    args = parser.parse_args()

    from nous.application.use_cases import AppContextRegistry
    from nous.config.settings import Settings

    settings = Settings()
    AppContextRegistry.configure(settings)
    persona = args.persona or settings.default_persona or "default"
    ctx = AppContextRegistry.get(persona)

    targets, added, skipped = backfill_persona(ctx, apply=args.apply)
    print(f"persona={persona} dry_run={not args.apply} targets={targets} added={added} skipped={skipped}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
