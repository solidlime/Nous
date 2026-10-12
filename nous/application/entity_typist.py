"""Entity typist backfill runner.

DISTINCT entities のバッチ型付け。enrich 相乗りではなく entities を主軸にする
理由: enrich ゲート（importance == 0.5）に覆蓋されず、対象が memory 数ではなく
entity 数で頭打ちになり、新規対応と既存データ backfill が同じコードで済む。

LLM は fail-open。型を書けなかった entity は metadata.typed_by を持たず、
次回の実行対象として残る（推測で型を書かない）。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from nous.infrastructure.sqlite.entity_repo import SQLiteEntityRepository

logger = logging.getLogger(__name__)

#: typist が書く provenance（trust 順序で最上位）。
TYPED_BY_LLM = "llm"


@dataclass
class TypistReport:
    """1 回の backfill 実行結果。"""

    examined: int = 0
    typed: int = 0
    skipped: int = 0
    batches: int = 0
    applied: dict[str, str] = field(default_factory=dict)


async def run_entity_typist(
    repo: SQLiteEntityRepository,
    typist: Any,
    *,
    limit: int = 500,
    batch_size: int = 20,
) -> TypistReport:
    """未型付け entity を代表記憶スニペット付きでバッチ型付けし、trust 付きで書く。"""
    rows = repo.list_entities_without_typed_by(limit=limit)
    report = TypistReport(examined=len(rows))
    if not rows:
        return report

    snippets = repo.get_representative_snippets([r["id"] for r in rows], per_entity=2)
    items = [
        {
            "id": r["id"],
            "current_type": r.get("entity_type") or "unknown",
            "snippets": snippets.get(r["id"], []),
        }
        for r in rows
    ]
    report.batches = (len(items) + batch_size - 1) // batch_size

    try:
        typed = await typist.type_many(items, batch_size=batch_size) or {}
    except Exception:
        logger.warning("entity typist run failed (fail-open)", exc_info=True)
        typed = {}

    for eid, etype in typed.items():
        result = repo.update_entity_type(eid, etype, TYPED_BY_LLM)
        # is_ok だけでは下位信頼源による拒否（value=False）を数えてしまう。
        if result.is_ok and bool(getattr(result, "value", False)):
            report.typed += 1
            report.applied[eid] = etype
    report.skipped = report.examined - report.typed
    return report
