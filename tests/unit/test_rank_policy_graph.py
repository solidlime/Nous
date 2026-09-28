"""H6 修正（案B）: rank_policy 経路で graph 信号（entity match + PPR/SA）を
composite に統合する挙動の検証。

① graph_boost_weight=0 で regression（graph 計算自体を skip・composite 不変）
② graph_boost_weight=0.1 で entity match 候補に +0.1 が反映
③ SA activation cap（min(act * 2.0, 1.0) * weight ≤ 0.1）
④ reflection_penalty が graph boost を含む全体 composite に global 適用
⑤ entity_service / link_repo 無しは fail-open（graph_signal 空・base+rel で継続）
⑥ rank_policy 経路でも reranker は skip 継続
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import numpy as np
import pytest

from nous.domain.memory.entities import Memory
from nous.domain.search.engine import SearchEngine, SearchQuery
from nous.domain.search.policy import RankPolicy
from nous.domain.shared.result import Success
from nous.domain.shared.time_utils import compute_recency_decay, get_now

if TYPE_CHECKING:
    from datetime import datetime


def _mem(
    key: str,
    content: str,
    tags: list[str] | None = None,
    importance: float = 0.5,
    created_at: datetime | None = None,
) -> Memory:
    now = created_at if created_at is not None else get_now()
    return Memory(
        key=key,
        content=content,
        created_at=now,
        updated_at=now,
        importance=importance,
        tags=tags or [],
    )


class _VecEncoder:
    """async_encode_batch を話すテスト用エンコーダ（ContentEncoder 構造互換）。"""

    def __init__(
        self,
        query_vec: np.ndarray,
        content_vecs: dict[str, np.ndarray] | None = None,
        fallback: np.ndarray | None = None,
    ) -> None:
        self.query_vec = query_vec
        self.content_vecs = content_vecs or {}
        self.fallback = fallback if fallback is not None else np.array([0.0, 1.0])

    async def async_encode_batch(self, texts: list[str], *, is_query: bool = False) -> np.ndarray:
        if is_query:
            return np.array([self.query_vec for _ in texts])
        return np.array([self.content_vecs.get(t, self.fallback) for t in texts])


def _engine(
    pairs: list[tuple[Memory, float]],
    *,
    entity_service=None,
    link_repo=None,
    encoder=None,
    reranker=None,
) -> SearchEngine:
    strat = MagicMock()
    strat.search.return_value = Success(pairs)
    retriever = None
    content_vecs = getattr(encoder, "content_vecs", None) if encoder is not None else None
    if content_vecs:
        # 候補 re-encode は廃止済み — encoder の content_vecs を key→vec フェイクに変換
        key_vecs = {m.key: content_vecs[m.content] for m, _ in pairs if m.content in content_vecs}

        async def _retrieve(keys: list[str]) -> dict[str, np.ndarray]:
            return {k: key_vecs[k] for k in keys if k in key_vecs}

        retriever = _retrieve
    return SearchEngine(
        keyword_search=strat,
        entity_service=entity_service,
        link_repo=link_repo,
        reranker=reranker,
        embedding_provider=(lambda: encoder) if encoder is not None else (lambda: None),
        vector_retriever=retriever,
    )


def _entity_service(linked: dict[str, list[str]], query_entities: list[tuple[str, float]]) -> MagicMock:
    svc = MagicMock()
    svc.extractor.extract.return_value = query_entities
    svc.find_related_memories.side_effect = lambda eid, limit=20: Success(linked.get(eid, []))
    return svc


# ---------------------------------------------------------------------------
# ① regression: graph_boost_weight=0 は現行 composite と完全一致
# ---------------------------------------------------------------------------


class TestGraphBoostWeightZeroRegression:
    @pytest.mark.asyncio
    async def test_zero_weight_skips_graph_and_keeps_composite(self):
        fixed = get_now()
        decay = compute_recency_decay(fixed)
        m1 = _mem("m1", "内容1", importance=0.5, created_at=fixed)
        m2 = _mem("m2", "内容2", importance=0.9, created_at=fixed)
        entity_service = _entity_service({"alice": ["m1"]}, [("alice", 0.9)])
        link_repo = MagicMock()
        link_repo.get_links_for_keys.return_value = {"m1": [{"target": "m2", "weight": 1.0}]}
        encoder = _VecEncoder(
            np.array([1.0, 0.0]),
            {"内容1": np.array([1.0, 0.0]), "内容2": np.array([0.0, 1.0])},
        )
        engine = _engine([(m1, 0.9), (m2, 0.8)], entity_service=entity_service, link_repo=link_repo, encoder=encoder)
        result = await engine.search(
            SearchQuery(text="alice の話", top_k=5, rank_policy=RankPolicy(graph_boost_weight=0.0, lexical_weight=0.0))
        )
        assert result.is_ok
        # weight=0 では graph 信号を計算しない（無駄な SQL/PPR を払わない）
        entity_service.extractor.extract.assert_not_called()
        link_repo.get_links_for_keys.assert_not_called()
        by_key = {r.memory.key: r for r in result.value}
        # composite = base + relevance_weight * rel のみ（graph 加算なし）
        assert by_key["m1"].score == pytest.approx(0.3 * decay + 0.3 * 0.5 + 0.4 * 1.0, abs=1e-6)
        assert by_key["m2"].score == pytest.approx(0.3 * decay + 0.3 * 0.9 + 0.4 * 0.0, abs=1e-6)
        assert by_key["m1"].graph_boost == 0.0
        assert by_key["m2"].graph_boost == 0.0


# ---------------------------------------------------------------------------
# ② entity match → composite に +graph_boost_weight
# ---------------------------------------------------------------------------


class TestEntityMatchIntegration:
    @pytest.mark.asyncio
    async def test_entity_match_adds_graph_boost(self):
        fixed = get_now()
        decay = compute_recency_decay(fixed)
        m1 = _mem("m1", "内容1", importance=0.5, created_at=fixed)
        m2 = _mem("m2", "内容2", importance=0.5, created_at=fixed)
        entity_service = _entity_service({"alice": ["m1"]}, [("alice", 0.9)])
        link_repo = MagicMock()
        link_repo.get_links_for_keys.return_value = {}
        encoder = _VecEncoder(
            np.array([1.0, 0.0]),
            {"内容1": np.array([0.0, 1.0]), "内容2": np.array([0.0, 1.0])},
        )
        engine = _engine([(m1, 0.9), (m2, 0.8)], entity_service=entity_service, link_repo=link_repo, encoder=encoder)
        result = await engine.search(
            SearchQuery(text="alice の話", top_k=5, rank_policy=RankPolicy(graph_boost_weight=0.1, lexical_weight=0.0))
        )
        assert result.is_ok
        entity_service.extractor.extract.assert_called_once()
        by_key = {r.memory.key: r for r in result.value}
        base = 0.3 * decay + 0.3 * 0.5
        # entity match は signal 1.0 → +0.1。rel はどちらも 0.
        assert by_key["m1"].graph_boost == pytest.approx(0.1, abs=1e-6)
        assert by_key["m1"].score == pytest.approx(base + 0.1, abs=1e-6)
        assert by_key["m2"].graph_boost == 0.0
        assert by_key["m2"].score == pytest.approx(base, abs=1e-6)


# ---------------------------------------------------------------------------
# ③ SA activation cap
# ---------------------------------------------------------------------------


class TestSpreadingActivationCap:
    @pytest.mark.asyncio
    async def test_sa_activation_is_capped(self, monkeypatch):
        fixed = get_now()
        m1 = _mem("m1", "内容1", importance=0.5, created_at=fixed)
        m2 = _mem("m2", "内容2", importance=0.5, created_at=fixed)
        link_repo = MagicMock()
        link_repo.get_links_for_keys.return_value = {"m1": [{"target": "m2", "weight": 1.0}]}

        class _FakeSpreadingActivation:
            def __init__(self, **kwargs) -> None:
                pass

            def propagate(self, seeds, links, persona=None):
                return {"m2": 10.0}  # 異常に大きい activation でも cap される

        monkeypatch.setattr("nous.domain.search.spreading_activation.SpreadingActivation", _FakeSpreadingActivation)
        encoder = _VecEncoder(
            np.array([1.0, 0.0]),
            {"内容1": np.array([1.0, 0.0]), "内容2": np.array([1.0, 0.0])},
        )
        engine = _engine([(m1, 0.9), (m2, 0.8)], link_repo=link_repo, encoder=encoder)
        result = await engine.search(SearchQuery(text="q", top_k=5, rank_policy=RankPolicy(graph_boost_weight=0.1)))
        assert result.is_ok
        by_key = {r.memory.key: r for r in result.value}
        # min(10.0 * 2.0, 1.0) * 0.1 = 0.1（cap）
        assert by_key["m2"].graph_boost == pytest.approx(0.1, abs=1e-6)
        assert by_key["m1"].graph_boost == 0.0


# ---------------------------------------------------------------------------
# ④ reflection penalty は graph boost を含む全体 composite に適用
# ---------------------------------------------------------------------------


class TestReflectionPenaltyWithGraph:
    @pytest.mark.asyncio
    async def test_penalty_applies_to_full_composite_with_graph(self):
        fixed = get_now()
        decay = compute_recency_decay(fixed)
        plain = _mem("p1", "普通の記憶", importance=0.5, created_at=fixed)
        refl = _mem("r1", "reflection文", tags=["reflection"], importance=0.5, created_at=fixed)
        entity_service = _entity_service({"alice": ["r1"]}, [("alice", 0.9)])
        link_repo = MagicMock()
        link_repo.get_links_for_keys.return_value = {}
        encoder = _VecEncoder(
            np.array([1.0, 0.0]),
            {"普通の記憶": np.array([1.0, 0.0]), "reflection文": np.array([1.0, 0.0])},
        )
        engine = _engine(
            [(plain, 0.9), (refl, 0.8)], entity_service=entity_service, link_repo=link_repo, encoder=encoder
        )
        result = await engine.search(
            SearchQuery(
                text="alice の話",
                top_k=5,
                rank_policy=RankPolicy(graph_boost_weight=0.1, reflection_penalty=0.5, lexical_weight=0.0),
            )
        )
        assert result.is_ok
        by_key = {r.memory.key: r for r in result.value}
        base = 0.3 * decay + 0.3 * 0.5
        # plain: 加算なし → base + 0.4*1.0
        assert by_key["p1"].score == pytest.approx(base + 0.4, abs=1e-6)
        # refl: (base + 0.4*1.0 + 0.1) * 0.5（graph boost を含む全体に penalty）
        assert by_key["r1"].score == pytest.approx((base + 0.4 + 0.1) * 0.5, abs=1e-6)


# ---------------------------------------------------------------------------
# ⑤ fail-open: entity_service / link_repo 無し
# ---------------------------------------------------------------------------


class TestGraphFailOpen:
    @pytest.mark.asyncio
    async def test_no_services_keeps_composite(self):
        fixed = get_now()
        decay = compute_recency_decay(fixed)
        m1 = _mem("m1", "内容1", importance=0.5, created_at=fixed)
        encoder = _VecEncoder(np.array([1.0, 0.0]), {"内容1": np.array([1.0, 0.0])})
        engine = _engine([(m1, 0.9)], encoder=encoder)
        result = await engine.search(
            SearchQuery(text="q", top_k=5, rank_policy=RankPolicy(graph_boost_weight=0.1, lexical_weight=0.0))
        )
        assert result.is_ok
        assert result.value[0].graph_boost == 0.0
        assert result.value[0].score == pytest.approx(0.3 * decay + 0.3 * 0.5 + 0.4 * 1.0, abs=1e-6)

    @pytest.mark.asyncio
    async def test_entity_service_exception_fails_open(self):
        """entity 抽出が例外でも検索は継続（graph signal なし）。"""
        fixed = get_now()
        m1 = _mem("m1", "内容1", importance=0.5, created_at=fixed)
        entity_service = MagicMock()
        entity_service.extractor.extract.side_effect = RuntimeError("boom")
        link_repo = MagicMock()
        link_repo.get_links_for_keys.return_value = {}
        encoder = _VecEncoder(np.array([1.0, 0.0]), {"内容1": np.array([1.0, 0.0])})
        engine = _engine([(m1, 0.9)], entity_service=entity_service, link_repo=link_repo, encoder=encoder)
        result = await engine.search(SearchQuery(text="q", top_k=5, rank_policy=RankPolicy(graph_boost_weight=0.1)))
        assert result.is_ok
        assert result.value[0].graph_boost == 0.0


# ---------------------------------------------------------------------------
# ⑥ reranker は rank_policy 経路でも skip 継続
# ---------------------------------------------------------------------------


class TestRerankerSkipMaintained:
    @pytest.mark.asyncio
    async def test_reranker_skipped_on_policy_path(self):
        fixed = get_now()
        m1 = _mem("m1", "内容1", importance=0.5, created_at=fixed)
        reranker = MagicMock()
        reranker.enabled = True
        reranker.is_loaded = True
        reranker.rerank.return_value = [("m1", 9.9)]
        entity_service = _entity_service({"alice": ["m1"]}, [("alice", 0.9)])
        link_repo = MagicMock()
        link_repo.get_links_for_keys.return_value = {}
        encoder = _VecEncoder(np.array([1.0, 0.0]), {"内容1": np.array([1.0, 0.0])})
        engine = _engine(
            [(m1, 0.9)],
            entity_service=entity_service,
            link_repo=link_repo,
            encoder=encoder,
            reranker=reranker,
        )
        result = await engine.search(
            SearchQuery(text="alice の話", top_k=5, rank_policy=RankPolicy(graph_boost_weight=0.1))
        )
        assert result.is_ok
        reranker.rerank.assert_not_called()
        # graph 信号の収集のため entity_service / link_repo は呼ばれる
        entity_service.extractor.extract.assert_called_once()
        link_repo.get_links_for_keys.assert_called_once()
