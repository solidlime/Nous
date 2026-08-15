#!/usr/bin/env python3
"""Latency benchmark for nous hot paths (embedding / reranker / Sudachi NER).

Measures per-call latency on CPU:
  - embedding encode: single & batch-10, query & document prefixes
  - reranker: 5 / 10 / 20 candidate pairs
  - Sudachi NER: ~500-char Japanese text

Cold = first call including model load; warm = 3 subsequent calls.
Usage: python scripts/bench_latency.py
"""

from __future__ import annotations

import os
import statistics
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from nous.domain.memory.sudachi_extractor import SudachiExtractor
from nous.infrastructure.embedding.model import EmbeddingModel
from nous.infrastructure.embedding.reranker import RerankerModel

TEXT = (
    "昨夜、東京の新宿区にある自宅で、山田太郎さんと来月の企画会議の準備を進めていました。"
    "資料には京都大学の研究結果が引用されており、株式会社ヘルタの技術戦略と照らし合わせながら、"
    "次期システムの要件定義をまとめていました。会議では大阪支社の田中花子さんも参加し、"
    "生成AIを活用した文書検索機能の実装方針について議論しました。特に日本語テキストの形態素解析と"
    "固有表現抽出の精度が重要だと指摘され、実験環境でのベンチマーク結果を次回の定例会で報告することになりました。"
    "またリリース後の運用監視では、レスポンスタイムの遅延が発生した場合に備えて、モデルの推論時間と"
    "データベースのクエリ時間をそれぞれ独立に計測する方針を採っています。"
)
QUERY = "生成AIを活用した日本語文書検索の実装方針"


def _ms(t0: float) -> float:
    return (time.perf_counter() - t0) * 1000.0


def _measure_load(make) -> float:
    obj = make()
    t0 = time.perf_counter()
    obj._ensure_loaded()
    return _ms(t0)


def _bench(make, call, rounds: int = 3) -> tuple[float, list[float]]:
    obj = make()
    t0 = time.perf_counter()
    call(obj)
    cold = _ms(t0)
    warm = []
    for _ in range(rounds):
        t0 = time.perf_counter()
        call(obj)
        warm.append(_ms(t0))
    return cold, warm


def _fmt(cold: float, warm: list[float]) -> str:
    return f"{cold:9.1f} {statistics.mean(warm):9.1f} {min(warm):8.1f} {max(warm):8.1f}"


def main() -> None:
    print(f"nproc = {os.cpu_count()}  (python {sys.version.split()[0]})")
    print()

    loads = {
        "embedding": _measure_load(lambda: EmbeddingModel()),
        "reranker": _measure_load(lambda: RerankerModel()),
        "sudachi": _measure_load(lambda: SudachiExtractor()),
    }
    print("=== モデルロード時間 (ONNX session / dict) ===")
    for name, ms_ in loads.items():
        print(f"  {name:10s} {ms_:9.1f} ms")
    print()

    rows: list[tuple[str, float, list[float]]] = []

    def add(label, make, call):
        cold, warm = _bench(make, call)
        rows.append((label, cold, warm))

    # embedding: single / batch-10, query / document
    add(
        "embed encode 1 (query)",
        lambda: EmbeddingModel(),
        lambda m: m.encode(TEXT, is_query=True),
    )
    add(
        "embed encode 1 (doc)",
        lambda: EmbeddingModel(),
        lambda m: m.encode(TEXT),
    )
    add(
        "embed encode_batch 10 (query)",
        lambda: EmbeddingModel(),
        lambda m: m.encode_batch([TEXT] * 10, is_query=True),
    )
    add(
        "embed encode_batch 10 (doc)",
        lambda: EmbeddingModel(),
        lambda m: m.encode_batch([TEXT] * 10),
    )

    # reranker: 5 / 10 / 20 candidate pairs
    cands = [TEXT[i : i + 180] for i in range(0, len(TEXT) - 150, 30)]
    for n in (5, 10, 20):
        keys = [f"k{i}" for i in range(n)]
        results = [(k, 0.5) for k in keys]
        contents = {k: cands[i % len(cands)] for i, k in enumerate(keys)}
        add(
            f"rerank {n} candidates",
            lambda: RerankerModel(),
            lambda r, res=results, cont=contents, k=n: r.rerank(QUERY, res, cont, top_k=k),
        )

    # Sudachi NER
    add("sudachi NER (~500 chars)", SudachiExtractor, lambda s: s.extract(TEXT))

    print("=== 各処理の実測時間 (ms) — cold=ロード込み初回 / warm=3回平均 min max ===")
    print(f"{'item':28s} {'cold':>9s} {'warm_avg':>9s} {'min':>8s} {'max':>8s}")
    for label, cold, warm in rows:
        print(f"{label:28s} {_fmt(cold, warm)}")

    print()
    print("=== 1回あたりの実測 (warm 平均, ms) 一覧 ===")
    for label, _, warm in rows:
        print(f"  {label:28s} {statistics.mean(warm):9.1f} ms")


if __name__ == "__main__":
    main()
