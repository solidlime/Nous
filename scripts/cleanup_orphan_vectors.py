"""Qdrant に残った孤立記憶ベクトル（orphan points）の一括掃除。

背景（2026-11-21）: wiki 編纂 worker の ``async_drop_memories`` が空 prefix で
存在しないコレクションを叩いて 404 → SQLite 行は消えたのにベクトルだけが
``memory_<persona>`` に残る孤児化が発生した（本体修正済み）。過去に残った
孤立 point は検索に混入しない代わりに容量を無駄に食うので、本スクリプトで
「SQLite memories テーブルに対応行が無い point」を削除する。

使い方（コンテナ内で実行）::

    python scripts/cleanup_orphan_vectors.py --persona herta          # dry-run
    python scripts/cleanup_orphan_vectors.py --persona herta --apply  # 実削除

    python scripts/cleanup_orphan_vectors.py                          # 全 persona dry-run
"""

from __future__ import annotations

import argparse
import asyncio
import sqlite3
import sys
from pathlib import Path

from nous.config.settings import get_settings


async def _collect_point_keys(mgr, collection: str) -> dict[str, str]:
    """collection を scroll して {point_id: payload key} を返す。"""
    client = await mgr.get_client()
    result: dict[str, str] = {}
    offset = None
    while True:
        records, offset = await client.scroll(
            collection_name=collection,
            limit=256,
            offset=offset,
            with_payload=True,
            with_vectors=False,
        )
        for rec in records:
            result[str(rec.id)] = str((rec.payload or {}).get("key", ""))
        if offset is None:
            break
    return result


async def _delete_points(mgr, collection: str, point_ids: list) -> None:
    from typing import cast

    from qdrant_client.models import ExtendedPointId, PointIdsList

    client = await mgr.get_client()
    for i in range(0, len(point_ids), 100):
        batch = cast("list[ExtendedPointId]", point_ids[i : i + 100])
        await client.delete(
            collection_name=collection,
            points_selector=PointIdsList(points=batch),
        )


def _sqlite_keys(db_path: Path) -> set[str]:
    """memories テーブルに存在する全 key（tombstone 含む — 行がある限り孤児ではない）。"""
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        rows = con.execute("SELECT key FROM memories").fetchall()
    finally:
        con.close()
    return {str(k) for (k,) in rows}


async def cleanup_persona(mgr, settings, persona: str, apply: bool) -> tuple[int, int]:
    """1 persona 分の掃除。(全 point 数, 削除した孤児数) を返す。"""

    collection = f"{settings.qdrant.collection_prefix}{persona}"
    try:
        points = await _collect_point_keys(mgr, collection)
    except Exception as e:
        print(f"  [{persona}] collection '{collection}' 読み取り失敗（スキップ）: {e}")
        return (0, 0)

    db_path = Path(settings.data_root) / "persona" / persona / "db" / "memory.sqlite"
    if not db_path.exists():
        print(f"  [{persona}] SQLite DB が無い（{db_path}）— 全 point を孤児扱いにするのは危険なのでスキップ")
        return (len(points), 0)
    sqlite_keys = _sqlite_keys(db_path)

    orphans = [(pid, key) for pid, key in points.items() if key not in sqlite_keys]
    print(f"  [{persona}] points={len(points)} sqlite_rows={len(sqlite_keys)} orphans={len(orphans)}")
    for pid, key in orphans[:20]:
        print(f"    orphan: {key or '(payload に key 無し)'} ({pid})")
    if len(orphans) > 20:
        print(f"    … ほか {len(orphans) - 20} 件")

    if apply and orphans:
        await _delete_points(mgr, collection, [pid for pid, _ in orphans])
        print(f"  [{persona}] 削除実行: {len(orphans)} point")
    return (len(points), len(orphans))


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--persona", nargs="*", help="対象 persona（省略時は全 persona）")
    parser.add_argument("--apply", action="store_true", help="実削除（省略時は dry-run）")
    args = parser.parse_args()

    settings = get_settings()
    personas = args.persona or [p.name for p in (Path(settings.data_root) / "persona").iterdir() if p.is_dir()]
    if not personas:
        print("対象 persona が無い")
        return 1

    from nous.application import use_cases

    mgr = use_cases.QdrantClientManager(settings.qdrant.url, settings.qdrant.api_key)
    await mgr.connect()
    if not await mgr.health_check():
        print(f"Qdrant ({settings.qdrant.url}) に接続できない")
        return 1

    print(("APPLY" if args.apply else "DRY-RUN") + f" — prefix='{settings.qdrant.collection_prefix}'")
    total_orphans = 0
    try:
        for persona in personas:
            total_orphans += (await cleanup_persona(mgr, settings, persona, args.apply))[1]
    finally:
        close = getattr(mgr, "close", None)
        if close is not None:
            result = close()
            if asyncio.iscoroutine(result):
                await result
    print(
        f"合計孤児: {total_orphans}" + ("（削除済み）" if args.apply else "（dry-run のため未削除 — --apply で実行）")
    )
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
