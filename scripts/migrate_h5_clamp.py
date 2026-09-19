#!/usr/bin/env python3
"""v4.0 one-shot migration for audit H5 (emotion-inflated stability).

Enables SessionConfig.h5_stability_clamp_enabled and runs a single decay
worker cycle so _h5_stability_clamp_once clamps every non-LTM memory row
whose stability exceeds 1.0 (inflated by the removed emotion gain) back to
the emotion-free default. Idempotent — running twice is harmless.

Usage:
    uv run python scripts/migrate_h5_clamp.py            # execute
    uv run python scripts/migrate_h5_clamp.py --dry-run  # count only
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

os.environ.setdefault("NOUS_H5_STABILITY_CLAMP", "1")


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="count affected rows without writing")
    parser.add_argument("--persona", default=None, help="persona to migrate (default: server default)")
    args = parser.parse_args()

    from nous.application.use_cases import AppContextRegistry
    from nous.application.workers.decay_worker import DecayWorker
    from nous.config.settings import Settings

    settings = Settings()
    # Persist the flag so the clamp stays enabled until the next restart
    # clears it; one clamp pass is enough either way (idempotent).
    settings.forgetting.h5_stability_clamp_enabled = True
    AppContextRegistry.configure(settings)

    persona = args.persona or settings.default_persona or "default"
    ctx = AppContextRegistry.get(persona)

    worker = DecayWorker(ctx)
    if args.dry_run:
        result = ctx.memory_repo.get_all_strengths()
        rows = result.value if result.is_ok else []
        affected = [s for s in rows if not s.is_ltm and s.stability > 1.0]
        print(f"dry-run: {len(affected)} row(s) would be clamped (of {len(rows)})")
        return 0

    worker._h5_stability_clamp_once()
    print("H5 clamp migration done")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
