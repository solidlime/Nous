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
              + lexical_weight * lexical_score
    （reflection タグあり & reflection_penalty != 1.0 のとき composite *= penalty）

    ``graph_signal`` は entity match（1.0）と PPR/spreading activation
    （min(act * 2.0, 1.0)）の合算（engine 側で計算）。``graph_boost_weight=0``
    で graph 寄与を完全に無効化でき、H6 修正前の composite と一致する。

    ``lexical_score`` は keyword/fts 由来候補が持つ 0-1 の語一致スコア
    （semantic 単独候補は 0.0 扱い）。``lexical_weight=0.0`` で語一致寄与を
    完全に無効化でき、lexical 修正前の composite と一致する。
    """

    recency_weight: float = 0.3
    importance_weight: float = 0.3
    relevance_weight: float = 0.4
    reflection_penalty: float = 1.0
    graph_boost_weight: float = 0.1  # entity/PPR graph 信号の composite 加算上限
    lexical_weight: float = 0.25  # keyword/fts 語一致信号の composite 加算上限

    @classmethod
    def from_weight_args(
        cls,
        importance_weight: float,
        recency_weight: float,
        vector_weight: float,
        keyword_weight: float,
    ) -> RankPolicy:
        """memory_search 系 tool 引数（RRF 重み）→ RankPolicy の共通写像。

        MCP（``_tools_memory._tool_memory_search``）と REST
        （``/api/search/{persona}``）の両経路が同一の写像を使い、経路間の
        重み不一致を防ぐ。写像: vector→relevance、keyword→lexical、
        importance/recency はそのまま。graph_boost_weight はクラス既定
        （0.1）を維持。
        """
        return cls(
            importance_weight=importance_weight,
            recency_weight=recency_weight,
            relevance_weight=vector_weight,
            lexical_weight=keyword_weight,
        )
