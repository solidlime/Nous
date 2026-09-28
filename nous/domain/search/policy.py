"""RankPolicy: 真の recall 経路（chat）専用の最終スコア段。

rank_policy は SearchEngine の最終段（post-filter 後）で複合スコア
（recency + importance + relevance + reflection penalty）を適用する。
``SearchQuery.rank_policy=None`` の経路（exploration / dup_check / reflection /
admin 検索など）は従来どおり RRF/減衰段で完結し、本ポリシーは一切作用しない。

frozen dataclass: ``SearchQuery`` のキャッシュキーにそのまま入れられるよう
hashable であることが必須（``_query_cache_key`` が ``RankPolicy`` をキー要素
として扱う）。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RankPolicy:
    """複合スコアの重みと reflection 降格係数。

    composite = recency_weight * recency_decay(created_at)
              + importance_weight * importance
              + relevance_weight * raw_cosine(rel)
              + graph_boost_weight * graph_signal
    （reflection タグあり & reflection_penalty != 1.0 のとき composite *= penalty）

    ``graph_signal`` は entity match（1.0）と PPR/spreading activation
    （min(act * 2.0, 1.0)）の合算（engine 側で計算）。``graph_boost_weight=0``
    で graph 寄与を完全に無効化でき、H6 修正前の composite と一致する。
    """

    recency_weight: float = 0.3
    importance_weight: float = 0.3
    relevance_weight: float = 0.4
    reflection_penalty: float = 1.0
    graph_boost_weight: float = 0.1  # entity/PPR graph 信号の composite 加算上限
