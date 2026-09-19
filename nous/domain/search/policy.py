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
    （reflection タグあり & reflection_penalty != 1.0 のとき composite *= penalty）
    """

    recency_weight: float = 0.3
    importance_weight: float = 0.3
    relevance_weight: float = 0.4
    reflection_penalty: float = 1.0
