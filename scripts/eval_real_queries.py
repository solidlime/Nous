"""実クエリ（search_log 由来）に対する検索品質の評価ハーネス。

背景:
- 合成クエリ（``tests/benchmark/data/search_quality_queries_v1.json``）の any-term gold は
  「本番 DB に存在しない語」を含む場合があり、指標として破綻する
  （2026-09-28 実測: 「queued」「お願い」は memories に 0 件。gold の実体は
  「処理」21 件 / 「確認」417 件など、ごく一部の一般語だけだった）
- 本ハーネスは *実際にユーザーが投げたクエリ*（``search_log``）を対象に、
  本番 DB に実在する語のみを gold として評価する（skip: 全語が DB に存在しないクエリ）

使い方（nous コンテナ内、または本番 DB を読める環境で）::

    python3 scripts/eval_real_queries.py --limit 130 --out real_queries.json

    # MCP 経由（tools/call）で測定する場合:
    python3 scripts/eval_real_queries.py --limit 130 --transport mcp \
        --base-url http://localhost:26262 --host-header localhost:26262 --out real_queries_mcp.json

MCP 経由のクライアント実装は scripts/eval_search_quality.py の mcp_search を再利用する（重複実装しない）。

制約:
- SQLite は ``mode=ro``（読み取り専用）で開く。本番データを変更しない。
- API は ``--base-url`` 未指定時、localhost の 8000/8080/26262/26263 を自動検出する。
- gold は「クエリの語（空白区切り）のうち DB に実在する語」の any-term 一致。
  precision@5 は gold 集合の広さに依存する点に注意（一般語が多いクエリは gold が膨らむ）。
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sqlite3
import sys
import urllib.parse
import urllib.request
from pathlib import Path

DEFAULT_DB = "/data/persona/herta/memory.sqlite"
DEFAULT_PERSONA = "herta"
API_PORTS = (8000, 8080, 26262, 26263)


def _load_eval_search_quality():
    """scripts/eval_search_quality.py をパス指定で import し、mcp_search を再利用する。"""
    script = Path(__file__).resolve().parent / "eval_search_quality.py"
    spec = importlib.util.spec_from_file_location("eval_search_quality", script)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["eval_search_quality"] = module
    spec.loader.exec_module(module)
    return module


def detect_base_url() -> str | None:
    """localhost 上の nous API を検出して base URL を返す。"""
    for port in API_PORTS:
        try:
            with urllib.request.urlopen(f"http://localhost:{port}/health", timeout=5):
                return f"http://localhost:{port}"
        except Exception:
            continue
    return None


def fetch_queries(cur: sqlite3.Cursor) -> list[str]:
    """search_log から実クエリを出現回数・新しさ順に取得する。"""
    rows = cur.execute(
        "SELECT query, COUNT(*) c FROM search_log "
        "WHERE TRIM(query) != '' GROUP BY query ORDER BY c DESC, MAX(searched_at) DESC"
    ).fetchall()
    return [r[0] for r in rows]


def search_once(
    module,
    base_url: str,
    persona: str,
    q: str,
    top_k: int,
    transport: str,
    host_header: str | None,
    timeout: int = 180,
) -> list[dict]:
    """1 クエリ検索して REST 形式（{"memory": {"key": ...}} のリスト）に正規化して返す。

    transport: "http" = REST /api/search/{persona}、"mcp" = MCP tools/call (memory_search)。
    正規化により gold 一致ループは経路非依存。
    """
    if transport == "mcp":
        results, _elapsed = module.mcp_search(base_url, persona, q, top_k, timeout, host_header)
        return [{"memory": {"key": r["key"]}, "score": r.get("score")} for r in results]
    url = f"{base_url}/api/search/{persona}?" + urllib.parse.urlencode({"q": q, "limit": top_k})
    headers = {"Host": host_header} if host_header else {}
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data: list = json.loads(r.read().decode()).get("results", [])
    return data


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=DEFAULT_DB, help="memory.sqlite のパス（読み取り専用で開く）")
    parser.add_argument("--base-url", default=None, help="nous API の base URL（未指定時は自動検出）")
    parser.add_argument("--persona", default=DEFAULT_PERSONA)
    parser.add_argument("--limit", type=int, default=130, help="評価するクエリ数（頻度順）")
    parser.add_argument("--top-k", type=int, default=10, help="API から取得する件数")
    parser.add_argument(
        "--transport", choices=["http", "mcp"], default="http", help="検索経路（http=REST / mcp=MCP tools/call）"
    )
    parser.add_argument("--host-header", default=None, help="Host ヘッダ上書き（検証コンテナ用、例: localhost:26262）")
    parser.add_argument("--out", default=None, help="結果 JSON の出力先")
    args = parser.parse_args()

    base = args.base_url or detect_base_url()
    if not base:
        print("NO API on localhost — pass --base-url", file=sys.stderr)
        return 1

    con = sqlite3.connect(f"file:{args.db}?mode=ro", uri=True)
    cur = con.cursor()
    queries = fetch_queries(cur)[: args.limit]
    # MCP クライアント実装は eval_search_quality.mcp_search を再利用（重複実装しない）。
    esq = _load_eval_search_quality()

    gold_cache: dict[str, set[str]] = {}

    def gold_keys(term: str) -> set[str]:
        if term not in gold_cache:
            gold_cache[term] = {
                r[0]
                for r in cur.execute(
                    "SELECT key FROM memories WHERE content LIKE ? AND lifecycle_status != 'tombstoned'",
                    ("%" + term + "%",),
                ).fetchall()
            }
        return gold_cache[term]

    out: list[dict] = []
    for q in queries:
        real = [t for t in q.split() if gold_keys(t)]
        if not real:
            out.append({"q": q[:40], "skip": "no-real-terms"})
            continue
        gold: set[str] = set()
        for t in real:
            gold |= gold_keys(t)
        try:
            res = search_once(
                esq,
                base,
                args.persona,
                q,
                args.top_k,
                args.transport,
                args.host_header,
            )
        except Exception as e:  # noqa: BLE001 — 評価ハーネスは失敗も記録して継続する
            out.append({"q": q[:40], "err": str(e)[:60]})
            continue
        ranks = [i for i, x in enumerate(res, 1) if x.get("memory", {}).get("key") in gold]
        mrr = round(1.0 / ranks[0], 4) if ranks else 0.0
        hit5 = len([r for r in ranks if r <= 5])
        out.append(
            {
                "q": q[:36],
                "ret": len(res),
                "gold": len(gold),
                "hit5": hit5,
                "mrr": mrr,
                "p5": round(hit5 / max(1, min(5, len(res))), 3),
            }
        )
    con.close()

    scored = [r for r in out if "mrr" in r]
    zero = [r for r in scored if r["ret"] == 0]
    summary = {
        "base_url": base,
        "host_header": args.host_header,
        "transport": args.transport,
        "total": len(out),
        "scored": len(scored),
        "skipped": len([r for r in out if "skip" in r]),
        "errors": len([r for r in out if "err" in r]),
        "zero_result": len(zero),
        "mrr_mean": round(sum(r["mrr"] for r in scored) / max(1, len(scored)), 4),
        "p5_mean": round(sum(r["p5"] for r in scored) / max(1, len(scored)), 4),
        "mrr_lt_1": len([r for r in scored if r["mrr"] < 1.0]),
    }

    print(json.dumps({"summary": summary, "results": out}, ensure_ascii=False, indent=1))
    if args.out:
        Path(args.out).write_text(json.dumps({"summary": summary, "results": out}, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
