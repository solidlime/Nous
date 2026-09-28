"""hybrid + rank_policy の end-to-end 統合テスト（oracle BLOCK F1 対応）。

負条件: これらのテストは、RRF/乗数 ranker 連鎖が SearchResult の付加フィールド
（cosine / lexical_score / similarity_flag）を落としていた過去の実装では**赤**
だった（完全一致 keyword 候補の lexical_score が composite に届かず、cosine 優勢の
無関係候補を追い越せなかった）。部品単体のユニットテストでは検出できなかった断絶。
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from nous.domain.memory.entities import Memory
from nous.domain.search.engine import SearchEngine, SearchQuery
from nous.domain.search.policy import RankPolicy
from nous.domain.search.ranker import (
    ForgettingCurveRanker,
    RRFRanker,
    SearchResult,
    TopicAffinityRanker,
)
from nous.domain.shared.result import Success


def _mem(key: str, content: str) -> Memory:
    now = datetime.now(UTC)
    return Memory(key=key, content=content, created_at=now, updated_at=now, importance=0.5)


def _hybrid_engine() -> SearchEngine:
    """kw=完全一致 1 件 / sem=cosine 優勢の無関係 1 件の hybrid engine。"""
    mem_kw = _mem("kw_hit", "機能確認テスト 記憶読み書きの往復確認")
    mem_sem = _mem("sem_unrel", "まったく無関係な記憶の内容")

    kw = MagicMock()
    kw.search.return_value = Success([(mem_kw, 1.0)])
    sem = AsyncMock()
    sem.search.return_value = Success([(mem_sem, 0.95)])

    engine = SearchEngine(
        keyword_search=kw,
        semantic_search=sem,
        memory_repo=MagicMock(),  # search_fts なし → FTS 段は skip
        ranker=RRFRanker(k=60),
    )
    return engine


# ---------------------------------------------------------------------------
# 統合: hybrid + rank_policy end-to-end
# ---------------------------------------------------------------------------


class TestHybridPolicyE2E:
    @pytest.mark.asyncio
    async def test_word_match_beats_high_cosine_irrelevant(self):
        """keyword 完全一致候補が cosine 優勢の無関係候補を追い越す。"""
        engine = _hybrid_engine()
        query = SearchQuery(
            text="機能確認テスト 記憶読み書きの往復確認",
            top_k=5,
            # lexical_weight を支配的にして語一致信号を主役にする
            # （既定 weight 下では rel 0.4*0.95 = 0.38 が lexical 0.25 を上回る）。
            rank_policy=RankPolicy(lexical_weight=1.0, relevance_weight=0.2),
        )
        result = await engine.search(query)
        assert result.is_ok
        assert isinstance(result, Success)
        top = result.value[0]
        assert top.memory.key == "kw_hit"

    @pytest.mark.asyncio
    async def test_keyword_weight_zero_restores_semantic_order(self):
        """lexical_weight=0（後方互換）では cosine 優勢候補が再び勝つ。"""
        engine = _hybrid_engine()
        query = SearchQuery(
            text="機能確認テスト 記憶読み書きの往復確認",
            top_k=5,
            rank_policy=RankPolicy(lexical_weight=0.0, relevance_weight=1.0),
        )
        result = await engine.search(query)
        assert result.is_ok
        assert isinstance(result, Success)
        assert result.value[0].memory.key == "sem_unrel"

    @pytest.mark.asyncio
    async def test_no_policy_is_backward_compatible(self):
        """rank_policy=None の経路は従来どおり（RIF・entity boost を含む既存挙動）。"""
        engine = _hybrid_engine()
        query = SearchQuery(text="機能確認テスト 記憶読み書きの往復確認", top_k=5)
        result = await engine.search(query)
        assert result.is_ok
        assert isinstance(result, Success)
        assert len(result.value) >= 1

    @pytest.mark.asyncio
    async def test_fields_carried_through_fusion_chain(self):
        """融合融合後の上位 candidate に cosine / lexical_score / similarity_flag が届く。"""
        engine = _hybrid_engine()
        query = SearchQuery(
            text="機能確認テスト 記憶読み書きの往復確認",
            top_k=5,
            rank_policy=RankPolicy(),
        )
        result = await engine.search(query)
        assert result.is_ok
        assert isinstance(result, Success)
        by_key = {r.memory.key: r for r in result.value}
        # keyword 由来候補は re-encode されるので cosine は None でもよいが、
        # lexical_score は必ず生存している（F1: RRF 連鎖で strip されない）
        assert by_key["kw_hit"].lexical_score is not None
        assert by_key["kw_hit"].lexical_score > 0.0


# ---------------------------------------------------------------------------
# Ranker 単体: 各 ranker が付加フィールドを落とさない
# ---------------------------------------------------------------------------


class _StrLookup:
    async def __call__(self, key: str) -> tuple[float, float]:  # pragma: no cover
        return (1.0, 0.0)


class TestRankersPreserveAuxFields:
    def _candidates(self) -> list[SearchResult]:
        return [
            SearchResult(
                memory=_mem("kw_hit", "機能確認テスト 記憶読み書きの往復確認"),
                score=0.5,
                source="fts",
                cosine=0.3,
                lexical_score=1.0,
                similarity_flag=False,
            ),
            SearchResult(
                memory=_mem("sem_unrel", "まったく無関係な記憶の内容"),
                score=0.7,
                source="semantic",
                cosine=0.9,
                lexical_score=None,
                similarity_flag=True,
            ),
        ]

    def _assert_preserved(self, out: list[SearchResult]) -> None:
        by_key = {r.memory.key: r for r in out}
        assert by_key["kw_hit"].lexical_score == pytest.approx(1.0)
        assert by_key["kw_hit"].cosine == pytest.approx(0.3)
        assert by_key["sem_unrel"].similarity_flag is True
        assert by_key["sem_unrel"].cosine == pytest.approx(0.9)

    def test_rrf_preserves_fields(self):
        ranker = RRFRanker(k=60)
        query = SearchQuery(text="機能確認テスト")
        out = ranker.rank(self._candidates(), query)
        self._assert_preserved(out)

    def test_forgetting_curve_preserves_fields(self):
        ranker = ForgettingCurveRanker(strength_lookup=lambda key: (0.5, 0.0))
        query = SearchQuery(text="q")
        out = ranker.rank(self._candidates(), query)
        self._assert_preserved(out)

    def test_topic_affinity_preserves_fields(self):
        ranker = TopicAffinityRanker()
        query = SearchQuery(text="普通の問い合わせテキスト")
        out = ranker.rank(self._candidates(), query)
        self._assert_preserved(out)
