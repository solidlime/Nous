#!/usr/bin/env python3
"""検索品質スモーク（CI 用・オフライン）.

固定の小コーパスを一時 SQLite に投入し、実検索エンジンの keyword 経路
（FTS5 + LIKE + RRF）だけを回して `scripts/eval_search_quality.py` の
analyze/summarize で recall@5 / MRR / zero-result を測る。

- サーバー・Qdrant・埋め込みモデル不要（CI でそのまま動く）
- Sudachi 辞書には依存しない: `NOUS_DATA_ROOT` を一時ディレクトリに向けて
  raw-text フォールバックに固定する（ローカルと CI で同じ数値になる）
- 閾値を下回ると exit 1、常に `--out` の .json / .md を書き出す（CI artifact）

使い方:
  uv run python scripts/search_quality_smoke.py            # 既定フィクスチャ
  python scripts/search_quality_smoke.py --out output/search_quality_smoke
"""

from __future__ import annotations

import argparse
import asyncio
import importlib.util
import json
import os
import sys
import tempfile
import time
from datetime import UTC, datetime
from json import loads
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_FIXTURE = REPO_ROOT / "tests" / "benchmark" / "data" / "search_quality_smoke.json"

# 暫定スモーク閾値。コーパス/クエリを増やすときは scripts/eval_search_quality.py の
# 実測（recall@5 / MRR）に合わせて見直す。
MIN_RECALL5 = 0.8
MIN_MRR = 0.7
MAX_ZERO_RESULTS = 0
DEFAULT_LIMIT = 10


def _load_harness():
    """eval_search_quality.py をパス指定で import（scripts/ はパッケージではない）。"""
    path = Path(__file__).with_name("eval_search_quality.py")
    spec = importlib.util.spec_from_file_location("eval_search_quality", path)
    assert spec and spec.loader, f"cannot load {path}"
    module = importlib.util.module_from_spec(spec)
    sys.modules["eval_search_quality"] = module
    spec.loader.exec_module(module)
    return module


def _load_fixture(path: Path) -> tuple[dict[str, str], list[dict]]:
    try:
        fixture = loads(path.read_text(encoding="utf-8"))
        docs = {p["payload"]["key"]: p["payload"]["content"] for p in fixture["corpus"]}
        return docs, fixture["queries"]
    except (OSError, KeyError, ValueError) as e:
        raise SystemExit(f"invalid smoke fixture {path}: {e}") from e


async def run_smoke(fixture_path: Path, limit: int) -> dict:
    docs, queries = _load_fixture(fixture_path)
    harness = _load_harness()

    # 辞書なしの raw-text フォールバックに固定（環境差で数値が変わらないように）。
    os.environ["NOUS_DATA_ROOT"] = tempfile.mkdtemp(prefix="nous-smoke-root-")
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))

    from nous.application.use_cases import SQLiteKeywordSearch
    from nous.domain.memory.entities import Memory
    from nous.domain.search.engine import SearchEngine, SearchQuery
    from nous.domain.search.ranker import RRFRanker
    from nous.infrastructure.sqlite.connection import SQLiteConnection
    from nous.infrastructure.sqlite.memory_repo import SQLiteMemoryRepository

    rows: list[dict] = []
    with tempfile.TemporaryDirectory(prefix="nous-smoke-db-") as data_dir:
        conn = SQLiteConnection(data_dir=data_dir, persona="smoke")
        try:
            conn.initialize_schema()
            repo = SQLiteMemoryRepository(conn)
            now = datetime.now(UTC)
            for key, content in docs.items():
                saved = repo.save(
                    Memory(
                        key=key,
                        content=content,
                        created_at=now,
                        updated_at=now,
                        importance=0.5,
                        emotion="neutral",
                    )
                )
                assert saved.is_ok, f"insert failed for {key}: {saved}"

            engine = SearchEngine(SQLiteKeywordSearch(repo), None, RRFRanker(), memory_repo=repo)
            engine.set_persona("smoke")

            for query in queries:
                t0 = time.time()
                result = await engine.search(SearchQuery(text=query["q"], top_k=limit))
                elapsed = time.time() - t0
                if not result.is_ok:
                    rows.append({**query, "error": str(result.error)})
                    continue
                hits = [{"key": r.memory.key, "score": r.score, "source": r.source} for r in result.value]
                row = harness.analyze(query, hits, docs)
                row["latency_s"] = round(elapsed, 3)
                rows.append(row)
        finally:
            conn.close()

    return {
        "config": {
            "fixture": str(fixture_path),
            "persona": "smoke",
            "limit": limit,
            "transport": "keyword-only (offline)",
            "thresholds": {
                "min_recall@5": MIN_RECALL5,
                "min_mrr": MIN_MRR,
                "max_zero_results": MAX_ZERO_RESULTS,
            },
        },
        "rows": rows,
        "summary": harness.summarize(rows),
        "metric_definitions": harness.metric_definitions(),
    }


def check_gate(summary: dict) -> list[str]:
    failures = []
    recall5 = summary.get("recall@5_mean", 0.0)
    mrr = summary.get("mrr_mean", 0.0)
    zero = summary.get("zero_result_count", 0)
    if recall5 < MIN_RECALL5:
        failures.append(f"recall@5 mean {recall5:.4f} < {MIN_RECALL5}")
    if mrr < MIN_MRR:
        failures.append(f"MRR mean {mrr:.4f} < {MIN_MRR}")
    if zero > MAX_ZERO_RESULTS:
        failures.append(f"zero-result {zero} > {MAX_ZERO_RESULTS}: {summary.get('zero_result_ids')}")
    return failures


def main() -> None:
    ap = argparse.ArgumentParser(description="検索品質スモーク（オフライン）")
    ap.add_argument("--fixture", default=str(DEFAULT_FIXTURE))
    ap.add_argument("--out", default="output/search_quality_smoke", help="出力ベース名（.json/.md）")
    ap.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
    args = ap.parse_args()

    result = asyncio.run(run_smoke(Path(args.fixture), args.limit))
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.with_suffix(".json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    harness = _load_harness()
    out.with_suffix(".md").write_text(harness.format_markdown(result, str(out)), encoding="utf-8")

    summary = result["summary"]
    print(
        f"queries={summary['num_queries']} errors={summary['num_errors']} "
        f"zero={summary['zero_result_count']} "
        f"recall@5={summary.get('recall@5_mean', 0):.3f} mrr={summary.get('mrr_mean', 0):.3f}"
    )
    print(f"wrote {out.with_suffix('.json')} / {out.with_suffix('.md')}")

    failures = check_gate(summary)
    if failures:
        for failure in failures:
            print(f"FAIL: {failure}", file=sys.stderr)
        raise SystemExit(1)
    print("search quality smoke: OK")


if __name__ == "__main__":
    main()
