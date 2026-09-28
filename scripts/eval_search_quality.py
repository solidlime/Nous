#!/usr/bin/env python3
"""nous 検索精度評価ハーネス (v1)

実機 nous の HTTP API にクエリを投げ、コーパスから自動生成した正解集合と比較して
recall@k / MRR / precision@k を計算する。純粋な HTTP クライアントとして動作し、
nous パッケージには依存しない。

使い方:
  uv run python scripts/eval_search_quality.py --base-url http://nas:26262 \
      --persona herta --corpus herta_corpus.json --queries queries_v1.json \
      --limit 20 --out baseline_v1

  # MCP 経由（検証コンテナでは --host-header localhost:26262 を付ける）
  uv run python scripts/eval_search_quality.py --base-url http://nas:26264 --transport mcp \
      --host-header localhost:26262 --persona herta --corpus herta_corpus.json \
      --queries queries_v1.json --limit 20 --out verify_mcp

正解集合の定義:
  - 通常カテゴリ: content にクエリのいずれかの term を含む記憶 (any-term)
  - generic_np: content にいずれかの term を含む記憶を「妥当」とし precision@k を測る

計測関数 (load_corpus / load_queries / api_search / gold_any_term / analyze /
run_eval / summarize) はテストから import して再利用する。
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
import urllib.parse
import urllib.request


def load_corpus(path: str) -> dict[str, str]:
    """コーパス JSON を読み、key -> content の辞書を返す。"""
    with open(path, encoding="utf-8") as f:
        corpus = json.load(f)
    return {p["payload"]["key"]: p["payload"]["content"] for p in corpus}


def load_queries(path: str) -> dict:
    """クエリセット JSON をそのまま読み込む。"""
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def api_search(
    base_url: str,
    persona: str,
    q: str,
    limit: int,
    timeout: int = 30,
    host_header: str | None = None,
) -> tuple[list[dict], float]:
    """実機検索 API を叩き (結果リスト, 経過秒) を返す。

    host_header: 検証コンテナなど Host 検証があるサーバー向けの Host 上書き。
    """
    url = f"{base_url}/api/search/{persona}?q={urllib.parse.quote(q)}&limit={limit}"
    headers = {"Host": host_header} if host_header else {}
    req = urllib.request.Request(url, headers=headers)
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.load(resp)
    elapsed = time.time() - t0
    out = [
        {"key": r["memory"]["key"], "score": r.get("score"), "source": r.get("source")} for r in data.get("results", [])
    ]
    return out, elapsed


def mcp_search(
    base_url: str,
    persona: str,
    q: str,
    limit: int,
    timeout: int = 30,
    host_header: str | None = None,
) -> tuple[list[dict], float]:
    """MCP (streamable HTTP) 経由で memory_search を叩き (結果リスト, 経過秒) を返す。

    persona は X-Persona ヘッダで指定する（nous MCP middleware の仕様）。
    応答は result.content[].text に JSON 文字列 {"ok": true, "data": {"memories": [...]}}
    が入る。source は経路判別のため固定値 "mcp" を入れる。
    """
    payload = json.dumps(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": "memory_search", "arguments": {"query": q, "limit": limit}},
        }
    ).encode()
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
        "X-Persona": persona,
    }
    if host_header:
        headers["Host"] = host_header
    req = urllib.request.Request(f"{base_url}/mcp", data=payload, headers=headers, method="POST")
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.load(resp)
    elapsed = time.time() - t0
    if "error" in data:
        raise RuntimeError(f"MCP error: {data['error']}")
    text = ""
    for part in data.get("result", {}).get("content", []):
        if part.get("type") == "text":
            text = part["text"]
            break
    envelope = json.loads(text) if text else {}
    memories = envelope.get("data", {}).get("memories", []) if envelope.get("ok", True) else []
    out = [{"key": m["key"], "score": m.get("score"), "source": "mcp"} for m in memories]
    return out, elapsed


def gold_any_term(docs: dict[str, str], terms: list[str]) -> set[str]:
    """content にいずれかの term を含む記憶 key 集合（any-term 正解＝広い gold）。

    recall の分母が巨大になる（例: 汎用語でコーパスの 28%）ため、
    広い gold では precision / hit を主指標にする。
    """
    terms_l = [t.lower() for t in terms]
    return {k for k, c in docs.items() if any(t in c.lower() for t in terms_l)}


def gold_all_term(docs: dict[str, str], terms: list[str]) -> set[str]:
    """content に全 term を含む記憶 key 集合（all-term 正解＝狭い gold）。

    網羅性（recall）と順位（MRR）はこの狭い gold で測る。
    gold が空（コーパスに全語を含む記憶なし）のクエリは recall/MRR を None とし、
    集計から除外する（precision / hit のみで評価）。
    """
    terms_l = [t.lower() for t in terms]
    return {k for k, c in docs.items() if all(t in c.lower() for t in terms_l)}


def analyze(query: dict, results: list[dict], docs: dict[str, str]) -> dict:
    """1 クエリの計測値を計算する（広い gold=精度系 / 狭い gold=網羅系）。"""
    cat = query["cat"]
    terms = query["q"].split()
    gold_any = gold_any_term(docs, terms)
    gold_all = gold_all_term(docs, terms)
    ranks_any = [i for i, r in enumerate(results, 1) if r["key"] in gold_any]
    ranks_all = [i for i, r in enumerate(results, 1) if r["key"] in gold_all]

    n = len(results)
    m = {
        "id": query["id"],
        "cat": cat,
        "q": query["q"],
        "gold_count": len(gold_any),
        "gold_all_count": len(gold_all),
        "returned": n,
        "relevant_returned": len(ranks_any),
        "first_rank": ranks_any[0] if ranks_any else None,
        "scores": [r["score"] for r in results],
        "sources": [r["source"] for r in results],
        "top_keys": [r["key"] for r in results[:10]],
    }
    # 広い gold（any-term）: 精度系
    m["precision@5"] = sum(1 for r in results[:5] if r["key"] in gold_any) / max(1, min(5, n))
    m["precision@10"] = sum(1 for r in results[:10] if r["key"] in gold_any) / max(1, min(10, n))
    m["hit@5"] = 1.0 if any(r["key"] in gold_any for r in results[:5]) else 0.0
    # 狭い gold（all-term）: 網羅系（gold 空なら評価不能 = None）
    if gold_all:
        m["recall@5"] = len([r for r in ranks_all if r <= 5]) / len(gold_all)
        m["recall@10"] = len([r for r in ranks_all if r <= 10]) / len(gold_all)
        m["mrr"] = 1.0 / ranks_all[0] if ranks_all else 0.0
    else:
        m["recall@5"] = None
        m["recall@10"] = None
        m["mrr"] = None
    return m


def run_eval(
    base_url: str,
    persona: str,
    queries_path: str,
    corpus_path: str,
    limit: int = 20,
    timeout: int = 30,
    host_header: str | None = None,
    transport: str = "http",
) -> dict:
    """評価を最後まで実行し、config / rows / summary を含む辞書を返す。

    transport: "http" = REST /api/search、"mcp" = MCP tools/call。
    """
    docs = load_corpus(corpus_path)
    qset = load_queries(queries_path)
    search_fn = mcp_search if transport == "mcp" else api_search

    rows = []
    for query in qset["queries"]:
        try:
            results, elapsed = search_fn(base_url, persona, query["q"], limit, timeout, host_header)
        except Exception as e:  # noqa: BLE001 - 1 クエリの失敗で全体を止めない
            rows.append({"id": query["id"], "cat": query["cat"], "q": query["q"], "error": str(e)})
            print(f"ERR {query['id']}: {e}", file=sys.stderr)
            continue
        m = analyze(query, results, docs)
        m["latency_s"] = round(elapsed, 3)
        rows.append(m)

    return {
        "config": {
            "base_url": base_url,
            "persona": persona,
            "corpus": corpus_path,
            "queries": queries_path,
            "limit": limit,
            "host_header": host_header,
            "transport": transport,
        },
        "rows": rows,
        "summary": summarize(rows),
    }


def summarize(rows: list[dict]) -> dict:
    """rows を集計する。

    精度系（hit@5 / precision@5）は全クエリ対象、
    網羅系（recall@5/10, MRR）は all-term gold が存在するクエリのみ対象。
    """
    ok = [m for m in rows if "error" not in m]
    zero_result = [m for m in ok if m.get("returned", 0) == 0]
    errors = [m for m in rows if "error" in m]
    rec_ok = [m for m in ok if m.get("recall@5") is not None]

    s = {
        "num_queries": len(rows),
        "num_errors": len(errors),
        "zero_result_count": len(zero_result),
        "zero_result_ids": [m["id"] for m in zero_result],
        "num_evaluable_all_term": len(rec_ok),
    }
    if ok:
        s["hit@5_mean"] = round(statistics.mean(m.get("hit@5", 0.0) for m in ok), 4)
        s["precision@5_mean"] = round(statistics.mean(m.get("precision@5", 0.0) for m in ok), 4)
        lat = sorted(m["latency_s"] for m in ok)
        s["latency_median_s"] = round(statistics.median(lat), 3)
        s["latency_p95_s"] = round(lat[min(len(lat) - 1, int(round(0.95 * (len(lat) - 1))))], 3)
        s["latency_max_s"] = round(lat[-1], 3)
    if rec_ok:
        s["recall@5_mean"] = round(statistics.mean(m["recall@5"] for m in rec_ok), 4)
        s["recall@10_mean"] = round(statistics.mean(m["recall@10"] for m in rec_ok), 4)
        s["mrr_mean"] = round(statistics.mean(m["mrr"] for m in rec_ok), 4)
    return s


def format_markdown(result: dict, out: str) -> str:
    """Markdown レポートを生成する。"""
    rows = result["rows"]
    cfg = result["config"]
    s = result["summary"]
    lines = [
        f"# nous 検索評価 {out}",
        "",
        f"- persona: {cfg['persona']}, limit: {cfg['limit']}",
        f"- 実行時刻: {time.strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        "| id | cat | query | gold_any | gold_all | ret | P@5 | hit@5 | MRR | R@5 | R@10 | lat(s) |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for m in rows:
        if "error" in m:
            lines.append(f"| {m['id']} | {m['cat']} | {m['q']} | - | - | - | - | - | - | - | - | ERR |")
            continue

        def fmt(v: float | None, spec: str = ".2f") -> str:
            return "-" if v is None else format(v, spec)

        lines.append(
            f"| {m['id']} | {m['cat']} | {m['q']} | {m['gold_count']} | {m['gold_all_count']} | "
            f"{m['returned']} | {m['precision@5']:.2f} | {m['hit@5']:.0f} | "
            f"{fmt(m.get('mrr'), '.3f')} | {fmt(m.get('recall@5'))} | {fmt(m.get('recall@10'))} | {m['latency_s']} |"
        )
    lines += [
        "",
        "## 集計",
        f"- hit@5 平均: {s.get('hit@5_mean', 0):.3f}（上位5件に関連が1件以上ある割合）",
        f"- precision@5 平均: {s.get('precision@5_mean', 0):.3f}（広い gold）",
        f"- MRR 平均: {s.get('mrr_mean', 0):.3f}（狭い gold、{s.get('num_evaluable_all_term', 0)} クエリ）",
        f"- recall@5 平均: {s.get('recall@5_mean', 0):.3f}（狭い gold）",
        f"- recall@10 平均: {s.get('recall@10_mean', 0):.3f}（狭い gold）",
        f"- 遅延 中央値: {s.get('latency_median_s', 0):.3f}s / p95: {s.get('latency_p95_s', 0):.3f}s / 最大: {s.get('latency_max_s', 0):.3f}s",
        f"- zero-result: {s['zero_result_count']} 件",
    ]
    return "\n".join(lines) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser(description="nous 検索精度評価ハーネス")
    ap.add_argument("--base-url", default="http://nas:26262")
    ap.add_argument("--persona", default="herta")
    ap.add_argument("--corpus", default="herta_corpus.json")
    ap.add_argument("--queries", default="queries_v1.json")
    ap.add_argument("--limit", type=int, default=20)
    ap.add_argument("--out", default="eval_result")
    ap.add_argument("--host-header", default=None, help="Host ヘッダ上書き（検証コンテナ用、例: localhost:26264）")
    ap.add_argument("--transport", choices=["http", "mcp"], default="http", help="検索経路（http=REST / mcp=MCP tools/call）")
    args = ap.parse_args()

    result = run_eval(
        args.base_url,
        args.persona,
        args.queries,
        args.corpus,
        args.limit,
        host_header=args.host_header,
        transport=args.transport,
    )

    for m in result["rows"]:
        if "error" in m:
            continue
        mrr = m.get("mrr")
        r5 = m.get("recall@5")
        r10 = m.get("recall@10")
        mrr_s = "  -  " if mrr is None else f"{mrr:.3f}"
        r5_s = "  - " if r5 is None else f"{r5:.2f}"
        r10_s = "  - " if r10 is None else f"{r10:.2f}"
        print(
            f"{m['id']:16} gold={m['gold_count']:4}/{m['gold_all_count']:<3} ret={m['returned']:3} "
            f"P@5={m['precision@5']:.2f} hit={m['hit@5']:.0f} "
            f"mrr={mrr_s} r@5={r5_s} r@10={r10_s} lat={m['latency_s']}s"
        )

    with open(f"{args.out}.json", "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    with open(f"{args.out}.md", "w", encoding="utf-8") as f:
        f.write(format_markdown(result, args.out))
    print(f"\nwrote {args.out}.json / {args.out}.md")


if __name__ == "__main__":
    main()
