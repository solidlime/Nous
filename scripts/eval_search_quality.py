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
            # memory_search の引数名は top_k（"limit" は pydantic に extra ignore され
            # 暗黙で top_k=5 になっていた過去バグを修正）。
            "params": {"name": "memory_search", "arguments": {"query": q, "top_k": limit}},
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
    m["hit@10"] = 1.0 if any(r["key"] in gold_any for r in results[:10]) else 0.0
    # 広い gold（any-term）の MRR / precision@5（全クエリを対象にできる主要指標）。
    # gold_any が空なら評価不能 = None。p5_any は既存 precision@5 と同値（後方互換のため別名で併記）。
    if gold_any:
        m["mrr_any"] = 1.0 / ranks_any[0] if ranks_any else 0.0
        m["p5_any"] = m["precision@5"]
    else:
        m["mrr_any"] = None
        m["p5_any"] = None
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
        "metric_definitions": metric_definitions(),
    }


def summarize(rows: list[dict]) -> dict:
    """rows を集計する。

    精度系（hit@5 / precision@5）は全クエリ対象、
    網羅系（recall@5/10, MRR）は all-term gold が存在するクエリのみ対象。
    """
    ok = [m for m in rows if "error" not in m]
    zero_result = [m for m in ok if m.get("returned", 0) == 0]
    errors = [m for m in rows if "error" in m]
    rec_ok = [m for m in ok if m.get("recall@5") is not None]  # AT: all-term gold あり
    any_ok = [m for m in ok if m.get("gold_count", 0) >= 1]  # ALL: any-term gold あり

    s = {
        "num_queries": len(rows),
        "num_errors": len(errors),
        "zero_result_count": len(zero_result),
        "zero_result_ids": [m["id"] for m in zero_result],
        "num_evaluable_all_term": len(rec_ok),
        "num_evaluable_any_term": len(any_ok),
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

    # --- 部分集合別サマリ（どの集合の指標かを構造的に明示）-------------------
    # ALL = any-term gold（gold_any>=1 の全クエリ）/ AT = all-term gold ありクエリ。
    if any_ok:
        any_term_summary = {
            "n": len(any_ok),
            "hit@5_mean": round(statistics.mean(m["hit@5"] for m in any_ok), 4),
            "hit@10_mean": round(statistics.mean(m["hit@10"] for m in any_ok), 4),
            "mrr_mean": round(statistics.mean(m["mrr_any"] for m in any_ok), 4),
            "p5_mean": round(statistics.mean(m["p5_any"] for m in any_ok), 4),
        }
    else:
        any_term_summary = {"n": 0}
    s["any_term"] = any_term_summary
    if rec_ok:
        s["all_term"] = {
            "n": len(rec_ok),
            "mrr_mean": s["mrr_mean"],
            "recall@5_mean": s["recall@5_mean"],
            "recall@10_mean": s["recall@10_mean"],
        }
    else:
        s["all_term"] = {"n": 0}
    s["totals"] = {
        "n_queries": len(rows),
        "n_with_any_gold": len(any_ok),
        "n_with_all_gold": len(rec_ok),
        "zero_result_count": len(zero_result),
        "error_count": len(errors),
    }
    # 既存キーの別名（後方互換: 旧キーは削除しない）
    for src, dst in (
        ("mrr_mean", "any_term_mrr_mean"),
        ("hit@5_mean", "any_term_hit@5_mean"),
        ("hit@10_mean", "any_term_hit@10_mean"),
        ("p5_mean", "any_term_p5_mean"),
    ):
        if src in any_term_summary:
            s[dst] = any_term_summary[src]
    if rec_ok:
        s["all_term_mrr_mean"] = s["mrr_mean"]
        s["all_term_recall@5_mean"] = s["recall@5_mean"]
        s["all_term_recall@10_mean"] = s["recall@10_mean"]
    return s


def metric_definitions() -> dict:
    """出力 JSON の各指標キーが「どのクエリ集合を対象に何を意味するか」を説明する辞書（docs 用）。"""
    return {
        "hit@5_mean": "全クエリ（エラー除く）の hit@5 平均。any-term gold で上位5件に関連が1件以上ある割合",
        "precision@5_mean": "全クエリ（エラー除く）の precision@5 平均。any-term gold での上位5件の適合率",
        "recall@5_mean": "AT（all-term gold あり）クエリのみの recall@5 平均",
        "recall@10_mean": "AT（all-term gold あり）クエリのみの recall@10 平均",
        "mrr_mean": "AT（all-term gold あり）クエリのみの MRR 平均（後方互換キー）",
        "all_term_mrr_mean": "mrr_mean の別名（AT=all-term gold ありクエリのみの MRR 平均）",
        "all_term_recall@5_mean": "recall@5_mean の別名（AT）",
        "all_term_recall@10_mean": "recall@10_mean の別名（AT）",
        "any_term_mrr_mean": "ALL（gold_any>=1 の全クエリ）の MRR 平均。全クエリを対象とする主要指標",
        "any_term_hit@5_mean": "ALL（gold_any>=1 の全クエリ）の hit@5 平均",
        "any_term_hit@10_mean": "ALL（gold_any>=1 の全クエリ）の hit@10 平均",
        "any_term_p5_mean": "ALL（gold_any>=1 の全クエリ）の precision@5 平均",
        "any_term.n": "ALL の対象クエリ数（gold_any>=1）",
        "all_term.n": "AT の対象クエリ数（all-term gold あり）",
        "totals.n_queries": "クエリ総数",
        "totals.n_with_any_gold": "any-term gold (gold_any>=1) を持つクエリ数（ALL）",
        "totals.n_with_all_gold": "all-term gold を持つクエリ数（AT）",
        "totals.zero_result_count": "検索結果が0件だったクエリ数",
        "totals.error_count": "エラーになったクエリ数",
    }


def format_markdown(result: dict, out: str) -> str:
    """Markdown レポートを生成する。"""
    rows = result["rows"]
    cfg = result["config"]
    s = result["summary"]
    al = s.get("any_term", {})
    at = s.get("all_term", {})

    def fmt(v: float | None, spec: str = ".2f") -> str:
        return "-" if v is None else format(v, spec)

    lines = [
        f"# nous 検索評価 {out}",
        "",
        f"- persona: {cfg['persona']}, limit: {cfg['limit']}",
        f"- 実行時刻: {time.strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        "## 部分集合別サマリ",
        "",
        "| subset | 対象クエリ集合 | n | hit@5 | hit@10 | MRR | P@5 | R@5 | R@10 |",
        "|---|---|---|---|---|---|---|---|---|",
        f"| ALL (any-term) | gold_any>=1 の全クエリ | {al.get('n', 0)} | {fmt(al.get('hit@5_mean'), '.3f')} | "
        f"{fmt(al.get('hit@10_mean'), '.3f')} | {fmt(al.get('mrr_mean'), '.3f')} | {fmt(al.get('p5_mean'), '.3f')} | - | - |",
        f"| AT (all-term) | all-term gold あり | {at.get('n', 0)} | - | - | {fmt(at.get('mrr_mean'), '.3f')} | "
        f"- | {fmt(at.get('recall@5_mean'), '.3f')} | {fmt(at.get('recall@10_mean'), '.3f')} |",
        "",
        "## クエリ別",
        "",
        "| id | cat | query | gold_any | gold_all | ret | P@5 | hit@5 | hit@10 | MRR(AT) | MRR_any(ALL) | R@5 | R@10 | lat(s) |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for m in rows:
        if "error" in m:
            lines.append(f"| {m['id']} | {m['cat']} | {m['q']} | - | - | - | - | - | - | - | - | - | - | ERR |")
            continue

        lines.append(
            f"| {m['id']} | {m['cat']} | {m['q']} | {m['gold_count']} | {m['gold_all_count']} | "
            f"{m['returned']} | {m['precision@5']:.2f} | {m['hit@5']:.0f} | {m['hit@10']:.0f} | "
            f"{fmt(m.get('mrr'), '.3f')} | {fmt(m.get('mrr_any'), '.3f')} | "
            f"{fmt(m.get('recall@5'))} | {fmt(m.get('recall@10'))} | {m['latency_s']} |"
        )
    lines += [
        "",
        "## 集計",
        f"- hit@5 平均: {s.get('hit@5_mean', 0):.3f}（上位5件に関連が1件以上ある割合）",
        f"- precision@5 平均: {s.get('precision@5_mean', 0):.3f}（広い gold）",
        f"- MRR 平均 (ALL/any-term): {fmt(al.get('mrr_mean'), '.3f')}（gold_any>=1 の {al.get('n', 0)} クエリ）",
        f"- MRR 平均 (AT/all-term): {fmt(at.get('mrr_mean'), '.3f')}（all-term gold ありの {at.get('n', 0)} クエリ）",
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
    ap.add_argument(
        "--transport", choices=["http", "mcp"], default="http", help="検索経路（http=REST / mcp=MCP tools/call）"
    )
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
        mrr_any = m.get("mrr_any")
        r5 = m.get("recall@5")
        r10 = m.get("recall@10")
        mrr_s = "  -  " if mrr is None else f"{mrr:.3f}"
        mrr_any_s = "  -  " if mrr_any is None else f"{mrr_any:.3f}"
        r5_s = "  - " if r5 is None else f"{r5:.2f}"
        r10_s = "  - " if r10 is None else f"{r10:.2f}"
        print(
            f"{m['id']:16} gold={m['gold_count']:4}/{m['gold_all_count']:<3} ret={m['returned']:3} "
            f"P@5={m['precision@5']:.2f} hit={m['hit@5']:.0f} "
            f"mrr={mrr_s} mrr_any={mrr_any_s} r@5={r5_s} r@10={r10_s} lat={m['latency_s']}s"
        )

    with open(f"{args.out}.json", "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    with open(f"{args.out}.md", "w", encoding="utf-8") as f:
        f.write(format_markdown(result, args.out))
    print(f"\nwrote {args.out}.json / {args.out}.md")


if __name__ == "__main__":
    main()
