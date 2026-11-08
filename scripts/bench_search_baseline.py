"""検索の品質・速度ベースライン測定（kanban #23）.

本番 DB の ``search_log``（実際にユーザーが投げたクエリ）を使い、HTTP 検索 API を
叩いて「精度の代理指標」と「レイテンシ」を測る。改善前後で同じクエリ集合を使う。

精度の代理指標（gold ラベルが無いので決定的な代理）:
- ``term_hit@k``: 上位 k 件のうち、本文がクエリの実質語（2 文字以上の語）を
  1 つ以上含む割合。語を含む記憶が上に来ているほど高い。

使い方::

    python scripts/bench_search_baseline.py --base-url http://nas:26262 \
        --persona herta --limit 40 --out /tmp/search_baseline.json

DB は直接読まず、コンテナ内の sqlite からクエリ一覧を取る場合は
``--queries`` に JSON 配列ファイルを渡す（``dump_queries`` 相当は呼び出し側で用意）。
"""

from __future__ import annotations

import argparse
import json
import statistics
import time
import urllib.parse
import urllib.request
from typing import Any


def _words(query: str) -> list[str]:
    """クエリを実質語に分解する（記号・空白区切り、2 文字未満は捨てる）。"""
    raw = "".join(ch if ch.isalnum() else " " for ch in query).split()
    return [w for w in raw if len(w) >= 2]


def _read_json_file(path: str) -> Any:
    """JSON ファイルを読む（失敗はメッセージ付きで落とす）。"""
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except OSError as exc:
        raise SystemExit(f"cannot read {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise SystemExit(f"invalid JSON in {path}: {exc}") from exc


def _validate_base_url(base_url: str) -> str:
    """http/https 以外を弾く（urllib に file:// 等を渡さない）。"""
    parsed = urllib.parse.urlparse(base_url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise SystemExit(f"invalid base url: {base_url!r} (http/https only)")
    return base_url.rstrip("/")


def _get_json(url: str, timeout: float) -> dict[str, Any]:
    with urllib.request.urlopen(url, timeout=timeout) as resp:  # noqa: S310 - local HTTP
        data: dict[str, Any] = json.loads(resp.read().decode("utf-8"))
        return data


def measure(
    base_url: str,
    persona: str,
    queries: list[str],
    limit: int,
    timeout: float,
    extra_params: dict[str, str] | None = None,
) -> dict:
    rows: list[dict[str, Any]] = []
    for query in queries:
        words = _words(query)
        params = {"q": query, "limit": limit, **(extra_params or {})}
        url = f"{base_url.rstrip('/')}/api/search/{persona}?" + urllib.parse.urlencode(params)
        started = time.perf_counter()
        try:
            payload = _get_json(url, timeout)
            latency_ms = (time.perf_counter() - started) * 1000.0
        except Exception as exc:  # ネットワーク失敗は記録して続行
            rows.append({"query": query, "error": str(exc)})
            continue
        results = payload.get("results") or []
        hits = 0
        for item in results[:limit]:
            memory = item.get("memory") or {}
            text = f"{memory.get('content', '')} {' '.join(memory.get('tags') or [])}"
            if any(word.lower() in text.lower() for word in words):
                hits += 1
        rows.append(
            {
                "query": query,
                "words": words,
                "latency_ms": round(latency_ms, 1),
                "returned": len(results),
                "term_hits": hits,
                "term_hit_at_k": (hits / len(results)) if results else 0.0,
            }
        )
    ok = [r for r in rows if "error" not in r]
    latencies = [float(r["latency_ms"]) for r in ok]
    precisions = [float(r["term_hit_at_k"]) for r in ok]
    return {
        "queries": len(rows),
        "errors": len(rows) - len(ok),
        "term_hit_at_k_mean": round(statistics.fmean(precisions), 4) if precisions else 0.0,
        "latency_p50_ms": round(statistics.median(latencies), 1) if latencies else 0.0,
        "latency_p90_ms": round(
            statistics.quantiles(latencies, n=10)[8]
            if len(latencies) >= 10
            else (max(latencies) if latencies else 0.0),
            1,
        ),
        "latency_mean_ms": round(statistics.fmean(latencies), 1) if latencies else 0.0,
        "rows": rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://nas:26262")
    parser.add_argument("--persona", default="herta")
    parser.add_argument("--queries", required=True, help="JSON 配列（クエリ文字列）ファイル")
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--max-queries", type=int, default=60)
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--param", action="append", default=[], metavar="KEY=VALUE", help="追加クエリパラメータ")
    parser.add_argument("--out", default=None)
    args = parser.parse_args()

    raw_queries = _read_json_file(args.queries)
    seen: set[str] = set()
    queries: list[str] = []
    for q in raw_queries:
        if not isinstance(q, str):
            continue
        q = q.strip()
        if not q or q in seen or not _words(q):
            continue
        seen.add(q)
        queries.append(q)
        if len(queries) >= args.max_queries:
            break

    extra: dict[str, str] = {}
    for item in args.param:
        key, _, value = item.partition("=")
        if not key:
            raise SystemExit(f"invalid --param: {item!r}")
        extra[key] = value
    report = measure(_validate_base_url(args.base_url), args.persona, queries, args.limit, args.timeout, extra)
    summary = {k: v for k, v in report.items() if k != "rows"}
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if args.out:
        try:
            with open(args.out, "w", encoding="utf-8") as fh:
                json.dump(report, fh, ensure_ascii=False, indent=2)
        except OSError as exc:
            raise SystemExit(f"cannot write {args.out}: {exc}") from exc
        print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
