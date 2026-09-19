"""SearchEngine RankPolicy（複合スコア最終段）のユニットテスト。

案件1（#003 方針 a）: 複合スコア（recency + importance + cos + reflection penalty）
を SearchEngine の最終段（post-filter 後、top_k 切りの直前）として実装する。
本ファイルは engine 側 policy の全挙動を検証する:

① policy による composite 順 ② RRF 下位 → policy 上位の回帰 ③ 取得プール拡大
④ provider=None fail-open ⑤ reflection penalty（0.5 適用 / 1.0 noop）
⑥ cache キーへの policy 包含と cache hit 時の policy 適用 ⑦ encoder 例外 fail-open
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

import numpy as np
import pytest

from nous.domain.memory.entities import Memory
from nous.domain.search.engine import SearchEngine, SearchQuery, SearchResult
from nous.domain.search.policy import RankPolicy
from nous.domain.shared.result import Success
from nous.domain.shared.time_utils import compute_recency_decay, get_now


def _mem(
    key: str,
    content: str,
    tags: list[str] | None = None,
    importance: float = 0.9,
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


class _RaisingEncoder:
    """async_encode_batch が常に失敗するエンコーダ（⑦用）。"""

    async def async_encode_batch(self, texts: list[str], *, is_query: bool = False) -> np.ndarray:
        raise RuntimeError("encoder boom")


def _make_engine(
    pairs: list[tuple[Memory, float]],
    encoder: object | None = None,
) -> SearchEngine:
    strat = MagicMock()
    strat.search.return_value = Success(pairs)
    provider = (lambda: encoder) if encoder is not None else (lambda: None)
    return SearchEngine(keyword_search=strat, embedding_provider=provider)


def _engine_with_encoder(
    pairs: list[tuple[Memory, float]],
    query_vec: np.ndarray | None = None,
    content_vecs: dict[str, np.ndarray] | None = None,
) -> SearchEngine:
    qv = query_vec if query_vec is not None else np.array([1.0, 0.0])
    return _make_engine(pairs, _VecEncoder(qv, content_vecs or {}))


def _cos(result: SearchResult) -> float:
    return float(result.cosine or 0.0)


# ---------------------------------------------------------------------------
# ① composite 順（created_at 固定）
# ---------------------------------------------------------------------------


class TestPolicyCompositeOrder:
    @pytest.mark.asyncio
    async def test_ranking_matches_weighted_formula(self):
        """created_at 固定 → recency 同点。composite = 0.3r + 0.3imp + 0.4rel 順になる。"""
        fixed = get_now() - timedelta(days=10)
        decay = compute_recency_decay(fixed)
        m_low = _mem("m1", "関連なし低重要", importance=0.1, created_at=fixed)
        m_mid = _mem("m2", "ぼちぼち関連", importance=0.9, created_at=fixed)
        m_high = _mem("m3", "ドンピシャ関連", importance=0.5, created_at=fixed)
        engine = _engine_with_encoder(
            [(m_low, 0.9), (m_mid, 0.8), (m_high, 0.7)],
            content_vecs={
                "関連なし低重要": np.array([0.0, 1.0]),
                "ぼちぼち関連": np.array([0.4, 0.6]),
                "ドンピシャ関連": np.array([1.0, 0.0]),
            },
        )
        result = await engine.search(SearchQuery(text="クエリ", top_k=3, rank_policy=RankPolicy()))
        assert result.is_ok
        keys = [r.memory.key for r in result.value]
        assert keys == ["m3", "m2", "m1"]

        by_key = {r.memory.key: r for r in result.value}
        assert by_key["m3"].score == pytest.approx(0.3 * decay + 0.3 * 0.5 + 0.4 * 1.0, abs=1e-6)
        assert by_key["m2"].score == pytest.approx(0.3 * decay + 0.3 * 0.9 + 0.4 * 0.4, abs=1e-6)
        assert by_key["m1"].score == pytest.approx(0.3 * decay + 0.3 * 0.1 + 0.4 * 0.0, abs=1e-6)
        # 生コサイン（clamp されていない）が cosine に載る
        assert _cos(by_key["m3"]) == pytest.approx(1.0, abs=1e-6)

    @pytest.mark.asyncio
    async def test_relevance_is_not_clamped(self):
        """負のコサインもそのまま composite に反映され、cosine に原値が載る。"""
        fixed = get_now()
        mem = _mem("m1", "逆方向の内容", importance=0.5, created_at=fixed)
        decay = compute_recency_decay(fixed)
        engine = _engine_with_encoder(
            [(mem, 0.7)],
            content_vecs={"逆方向の内容": np.array([-1.0, 0.0])},
        )
        result = await engine.search(SearchQuery(text="クエリ", top_k=3, rank_policy=RankPolicy()))
        assert result.is_ok
        assert _cos(result.value[0]) == pytest.approx(-1.0, abs=1e-6)
        assert result.value[0].score == pytest.approx(0.3 * decay + 0.15 + 0.4 * -1.0, abs=1e-6)


# ---------------------------------------------------------------------------
# ② 回帰: RRF 下位だが cos=1.0 の記憶が policy で top_k に入る（本件の核）
# ---------------------------------------------------------------------------


class TestRegressionRrfBottomCosTop:
    @pytest.mark.asyncio
    async def test_cos_one_memory_enters_top_k(self):
        """候補 20 件中、engine（RRF）順で最下位の記憶も cos=1.0 なら top_k 先頭。"""
        fixed = get_now()
        pairs: list[tuple[Memory, float]] = []
        content_vecs: dict[str, np.ndarray] = {}
        for i in range(19):
            key = f"c{i:02d}"
            content = f"無関係な話題 {i}"
            pairs.append((_mem(key, content, importance=0.5, created_at=fixed), 0.9 - 0.01 * i))
            content_vecs[content] = np.array([0.0, 1.0])
        winner = _mem("winner", "ドンピシャな記憶", importance=0.5, created_at=fixed)
        pairs.append((winner, 0.71))  # RRF/engine 順では最下位
        content_vecs["ドンピシャな記憶"] = np.array([1.0, 0.0])

        engine = _engine_with_encoder(pairs, content_vecs=content_vecs)
        result = await engine.search(SearchQuery(text="クエリ", top_k=5, rank_policy=RankPolicy()))
        assert result.is_ok
        assert len(result.value) == 5
        assert result.value[0].memory.key == "winner"
        assert _cos(result.value[0]) == pytest.approx(1.0, abs=1e-6)
        # 他の候補は relevance 0 で composite が同点 → engine 順のまま後続
        assert {r.memory.key for r in result.value[1:]} == {f"c{i:02d}" for i in range(4)}

    @pytest.mark.asyncio
    async def test_entry_is_insensitive_to_engine_rank(self):
        """同一候補プールで engine 順を入れ替えても policy の top_k 集合は不変。"""
        fixed = get_now()
        a = _mem("a", "関連する内容", importance=0.5, created_at=fixed)
        b = _mem("b", "無関係な内容", importance=0.5, created_at=fixed)
        q = SearchQuery(text="クエリ", top_k=1, rank_policy=RankPolicy())
        r1 = await _engine_with_encoder(
            [(a, 0.9), (b, 0.8)],
            content_vecs={"関連する内容": np.array([1.0, 0.0]), "無関係な内容": np.array([0.0, 1.0])},
        ).search(q)
        r2 = await _engine_with_encoder(
            [(b, 0.9), (a, 0.8)],
            content_vecs={"関連する内容": np.array([1.0, 0.0]), "無関係な内容": np.array([0.0, 1.0])},
        ).search(q)
        assert r1.is_ok and r2.is_ok
        assert r1.value[0].memory.key == "a"
        assert r2.value[0].memory.key == "a"


# ---------------------------------------------------------------------------
# ③ 取得プール拡大（policy 指定時のみ）
# ---------------------------------------------------------------------------


class TestPoolExpansion:
    @pytest.mark.asyncio
    async def test_keyword_limit_expands_to_fetch_k_with_policy(self):
        """top_k=5 + policy → fetch_k=15。keyword strategy が limit=15 で呼ばれる。"""
        fixed = get_now()
        pairs = [(_mem(f"m{i}", f"内容 {i}", importance=0.5, created_at=fixed), 0.9) for i in range(15)]
        strat = MagicMock()
        strat.search.return_value = Success(pairs)
        engine = SearchEngine(keyword_search=strat, embedding_provider=lambda: _VecEncoder(np.array([1.0, 0.0])))
        result = await engine.search(SearchQuery(text="拡大", top_k=5, rank_policy=RankPolicy()))
        assert result.is_ok
        assert strat.search.call_args.kwargs["limit"] == 15

    @pytest.mark.asyncio
    async def test_fetch_k_capped_at_60(self):
        """top_k=25 + policy → fetch_k=min(75,60)=60。"""
        fixed = get_now()
        pairs = [(_mem(f"m{i}", f"内容 {i}", importance=0.5, created_at=fixed), 0.9) for i in range(60)]
        strat = MagicMock()
        strat.search.return_value = Success(pairs)
        engine = SearchEngine(keyword_search=strat, embedding_provider=lambda: _VecEncoder(np.array([1.0, 0.0])))
        result = await engine.search(SearchQuery(text="拡大", top_k=25, rank_policy=RankPolicy()))
        assert result.is_ok
        assert strat.search.call_args.kwargs["limit"] == 60

    @pytest.mark.asyncio
    async def test_fetch_k_floor_15(self):
        """top_k=1 + policy → fetch_k=max(3,15)=15。"""
        fixed = get_now()
        strat = MagicMock()
        strat.search.return_value = Success([(_mem("m0", "内容", importance=0.5, created_at=fixed), 0.9)])
        engine = SearchEngine(keyword_search=strat, embedding_provider=lambda: _VecEncoder(np.array([1.0, 0.0])))
        result = await engine.search(SearchQuery(text="拡大", top_k=1, rank_policy=RankPolicy()))
        assert result.is_ok
        assert strat.search.call_args.kwargs["limit"] == 15

    @pytest.mark.asyncio
    async def test_no_expansion_without_policy(self):
        """policy なし → 従来どおり limit=top_k。"""
        fixed = get_now()
        pairs = [(_mem(f"m{i}", f"内容 {i}", importance=0.5, created_at=fixed), 0.9) for i in range(15)]
        strat = MagicMock()
        strat.search.return_value = Success(pairs)
        engine = SearchEngine(keyword_search=strat)
        result = await engine.search(SearchQuery(text="拡大", top_k=5))
        assert result.is_ok
        assert strat.search.call_args.kwargs["limit"] == 5

    @pytest.mark.asyncio
    async def test_fts_pool_doubles_with_policy(self):
        """memory_repo あり: FTS が top_k=2*fetch_k で呼ばれる。"""
        fixed = get_now()
        mem = _mem("m0", "内容", importance=0.5, created_at=fixed)
        strat = MagicMock()
        strat.search.return_value = Success([(mem, 0.9)])
        memory_repo = MagicMock()
        memory_repo.search_fts.return_value = Success([(mem, 0.85)])
        engine = SearchEngine(
            keyword_search=strat,
            memory_repo=memory_repo,
            embedding_provider=lambda: _VecEncoder(np.array([1.0, 0.0])),
        )
        result = await engine.search(SearchQuery(text="拡大", top_k=5, rank_policy=RankPolicy()))
        assert result.is_ok
        assert memory_repo.search_fts.call_args.kwargs["top_k"] == 30


# ---------------------------------------------------------------------------
# ④ fail-open: provider=None → rec/imp のみ、cosine=0.0
# ---------------------------------------------------------------------------


class TestFailOpenNoProvider:
    @pytest.mark.asyncio
    async def test_no_provider_ranks_by_recency_importance(self):
        """provider なし → 全件 cosine=0.0、rec+imp のみで順位付け。"""
        fixed = get_now()
        decay = compute_recency_decay(fixed)
        m_hi = _mem("m1", "高重要", importance=0.9, created_at=fixed)
        m_lo = _mem("m2", "低重要", importance=0.2, created_at=fixed)
        engine = _make_engine([(m_lo, 0.9), (m_hi, 0.5)], encoder=None)
        result = await engine.search(SearchQuery(text="q", top_k=5, rank_policy=RankPolicy()))
        assert result.is_ok
        assert [r.memory.key for r in result.value] == ["m1", "m2"]
        for r in result.value:
            assert r.cosine == 0.0
        assert result.value[0].score == pytest.approx(0.3 * decay + 0.3 * 0.9, abs=1e-6)


# ---------------------------------------------------------------------------
# ⑤ reflection penalty（0.5 適用 / 1.0 は noop）
# ---------------------------------------------------------------------------


class TestReflectionPenaltyEngine:
    @pytest.mark.asyncio
    async def test_reflection_ranked_below_equal_memory(self):
        """同条件（同一 created_at・importance・rel）なら reflection が降格する。"""
        fixed = get_now()
        plain = _mem("p1", "よく使う道具の話", importance=0.9, created_at=fixed)
        refl = _mem("r1", "私は最近の振る舞いを反省している", tags=["reflection"], importance=0.9, created_at=fixed)
        engine = _engine_with_encoder(
            [(refl, 0.9), (plain, 0.9)],
            content_vecs={
                "よく使う道具の話": np.array([1.0, 0.0]),
                "私は最近の振る舞いを反省している": np.array([1.0, 0.0]),
            },
        )
        result = await engine.search(SearchQuery(text="q", top_k=5, rank_policy=RankPolicy(reflection_penalty=0.5)))
        assert result.is_ok
        assert [r.memory.key for r in result.value] == ["p1", "r1"]
        assert result.value[1].score == pytest.approx(result.value[0].score * 0.5, abs=1e-6)

    @pytest.mark.asyncio
    async def test_penalty_1_is_noop(self):
        """penalty=1.0 → 無効化: engine 順のまま（reflection 先頭）。"""
        fixed = get_now()
        refl = _mem("r1", "reflection文です", tags=["reflection"], importance=0.9, created_at=fixed)
        plain = _mem("p1", "普通の記憶", importance=0.9, created_at=fixed)
        engine = _engine_with_encoder(
            [(refl, 0.95), (plain, 0.9)],
            content_vecs={"reflection文です": np.array([1.0, 0.0]), "普通の記憶": np.array([1.0, 0.0])},
        )
        result = await engine.search(SearchQuery(text="q", top_k=5, rank_policy=RankPolicy(reflection_penalty=1.0)))
        assert result.is_ok
        assert [r.memory.key for r in result.value] == ["r1", "p1"]


# ---------------------------------------------------------------------------
# ⑥ cache: policy がキーに含まれる／cache hit でも policy 適用 + truncate
# ---------------------------------------------------------------------------


class TestPolicyCache:
    @pytest.mark.asyncio
    async def test_policy_included_in_cache_key(self):
        """rank_policy 違いの query は別キャッシュキーになる。"""
        fixed = get_now()
        strat = MagicMock()
        strat.search.return_value = Success([(_mem("m0", "内容", importance=0.5, created_at=fixed), 0.9)])
        engine = SearchEngine(keyword_search=strat)
        q1 = SearchQuery(text="cache me", mode="hybrid", top_k=5, rank_policy=RankPolicy())
        q2 = SearchQuery(text="cache me", mode="hybrid", top_k=5, rank_policy=RankPolicy(relevance_weight=1.0))
        k1 = engine._query_cache_key(q1, "hybrid")
        k2 = engine._query_cache_key(q2, "hybrid")
        assert k1 is not None and k2 is not None
        assert k1 != k2
        assert k1[-1] is q1.rank_policy

    @pytest.mark.asyncio
    async def test_cache_hit_still_applies_policy_and_truncates(self):
        """cache hit でも policy が適用され（cosine 付き）、top_k に切られる。"""
        fixed = get_now()
        pairs = [(_mem(f"m{i}", f"内容 {i}", importance=0.5, created_at=fixed), 0.9 - 0.01 * i) for i in range(20)]
        content_vecs = {f"内容 {i}": np.array([1.0, 0.0] if i == 19 else [0.0, 1.0]) for i in range(20)}
        strat = MagicMock()
        strat.search.return_value = Success(pairs)
        encoder = _VecEncoder(np.array([1.0, 0.0]), content_vecs)
        engine = SearchEngine(keyword_search=strat, embedding_provider=lambda: encoder)
        q = SearchQuery(text="cache me", mode="hybrid", top_k=5, rank_policy=RankPolicy())

        r1 = await engine.search(q)
        r2 = await engine.search(q)

        assert strat.search.call_count == 1, "second identical query should hit the cache"
        assert r1.is_ok and r2.is_ok
        assert len(r2.value) == 5
        assert [r.memory.key for r in r2.value] == [r.memory.key for r in r1.value]
        assert r2.value[0].memory.key == "m19"
        assert _cos(r2.value[0]) == pytest.approx(1.0, abs=1e-6)


# ---------------------------------------------------------------------------
# ⑦ encoder 例外 → fail-open（rec/imp のみで継続）
# ---------------------------------------------------------------------------


class TestEncoderExceptionFailOpen:
    @pytest.mark.asyncio
    async def test_encoder_raise_keeps_results_with_zero_cosine(self):
        """エンコード失敗でも検索は成功し、relevance=0.0 で rec/imp 順に継続。"""
        fixed = get_now()
        m_hi = _mem("m1", "高重要", importance=0.9, created_at=fixed)
        m_lo = _mem("m2", "低重要", importance=0.2, created_at=fixed)
        engine = _make_engine([(m_lo, 0.9), (m_hi, 0.5)], encoder=_RaisingEncoder())
        result = await engine.search(SearchQuery(text="q", top_k=5, rank_policy=RankPolicy()))
        assert result.is_ok
        assert [r.memory.key for r in result.value] == ["m1", "m2"]
        assert all(r.cosine == 0.0 for r in result.value)


# ---------------------------------------------------------------------------
# TestCosineRelevance（caller から移設）: 絶対コサインが効くこと
# ---------------------------------------------------------------------------


class TestCosineRelevanceEngine:
    @pytest.mark.asyncio
    async def test_cosine_beats_fresh_importance(self):
        """関連度高×低importance が 無関係×高importance・新鮮 を上回る。"""
        fixed = get_now()
        fresh_unrelated = _mem("m1", "無関係トピックの話", importance=1.0, created_at=fixed)
        relevant = _mem("m2", "関連する記憶", importance=0.1, created_at=fixed)
        engine = _engine_with_encoder(
            [(fresh_unrelated, 0.95), (relevant, 0.9)],
            content_vecs={
                "無関係トピックの話": np.array([0.0, 1.0]),
                "関連する記憶": np.array([0.9, 0.1]),
            },
        )
        result = await engine.search(SearchQuery(text="クエリ", top_k=5, rank_policy=RankPolicy()))
        assert result.is_ok
        # rel: 0.3*~1 + 0.3*0.1 + 0.4*0.9 = 0.69 > unrelated: 0.3*~1 + 0.3*1.0 + 0 = 0.6
        assert result.value[0].memory.key == "m2"
        assert _cos(result.value[0]) == pytest.approx(0.9, abs=1e-3)

    @pytest.mark.asyncio
    async def test_no_embedding_relevance_zero_fail_open(self):
        """provider なし → relevance 0.0 で継続（fail-open、rec+imp のみでランク）。"""
        fixed = get_now()
        m1 = _mem("m1", "記憶その1", importance=0.9, created_at=fixed)
        m2 = _mem("m2", "記憶その2", importance=0.2, created_at=fixed)
        engine = _make_engine([(m2, 0.9), (m1, 0.5)], encoder=None)
        result = await engine.search(SearchQuery(text="q", top_k=5, rank_policy=RankPolicy()))
        assert result.is_ok
        assert result.value[0].memory.key == "m1"
        assert result.value[0].cosine == 0.0


# ---------------------------------------------------------------------------
# TestCompositeScoreFormula（caller から衣替え）: 重みの効き方を engine で検証
# ---------------------------------------------------------------------------


class TestCompositeScoreFormulaEngine:
    """rank_policy 重み（rw/iw/relw）の効き方——旧 caller 計算と等価であること。"""

    @pytest.mark.asyncio
    async def test_weights_sum_to_correct_total(self):
        """既定重みで recency≈1, importance=1, rel=1 → composite ≈ 1.0。"""
        fixed = get_now()
        mem = _mem("m1", "全要素最高", importance=1.0, created_at=fixed)
        engine = _engine_with_encoder(
            [(mem, 0.5)],
            content_vecs={"全要素最高": np.array([1.0, 0.0])},
        )
        result = await engine.search(SearchQuery(text="q", top_k=5, rank_policy=RankPolicy()))
        assert result.is_ok
        assert result.value[0].score == pytest.approx(1.0, abs=1e-3)

    @pytest.mark.asyncio
    async def test_relevance_dominates_with_high_weight(self):
        """relevance 重み高い → 関連度が順位を支配。"""
        fixed = get_now()
        hi_rel = _mem("m1", "ドンピシャ", importance=0.1, created_at=fixed)
        lo_rel = _mem("m2", "関係薄い", importance=0.9, created_at=fixed)
        engine = _engine_with_encoder(
            [(hi_rel, 0.5), (lo_rel, 0.9)],
            content_vecs={"ドンピシャ": np.array([1.0, 0.0]), "関係薄い": np.array([0.1, 0.9])},
        )
        result = await engine.search(SearchQuery(text="q", top_k=5, rank_policy=RankPolicy(0.1, 0.1, 0.8)))
        assert result.is_ok
        assert result.value[0].memory.key == "m1"

    @pytest.mark.asyncio
    async def test_recency_dominates_with_high_weight(self):
        """recency 重み高い → 新鮮な記憶が上位。"""
        fresh = _mem("m1", "ついさっき", importance=0.1)
        old = _mem("m2", "昔の話", importance=0.9, created_at=get_now() - timedelta(days=1000))
        engine = _engine_with_encoder(
            [(fresh, 0.5), (old, 0.9)],
            content_vecs={"ついさっき": np.array([0.0, 1.0]), "昔の話": np.array([0.0, 1.0])},
        )
        result = await engine.search(SearchQuery(text="q", top_k=5, rank_policy=RankPolicy(0.8, 0.1, 0.1)))
        assert result.is_ok
        assert result.value[0].memory.key == "m1"

    @pytest.mark.asyncio
    async def test_zero_scores_give_near_zero(self):
        """importance=0, rel=0, created_at 超過去 → composite ≈ 0。"""
        mem = _mem("m1", "無関係な古い記憶", importance=0.0, created_at=datetime.now(UTC) - timedelta(days=1000))
        engine = _engine_with_encoder(
            [(mem, 0.5)],
            content_vecs={"無関係な古い記憶": np.array([0.0, 1.0])},
        )
        result = await engine.search(SearchQuery(text="q", top_k=5, rank_policy=RankPolicy()))
        assert result.is_ok
        assert result.value[0].score < 0.01

    @pytest.mark.asyncio
    async def test_custom_weight_precision(self):
        """既知入力の composite が手計算と一致（rw=0.3, iw=0.3, relw=0.4）。"""
        fixed = get_now() - timedelta(days=5)
        decay = compute_recency_decay(fixed)
        mem = _mem("m1", "既知内容", importance=0.5, created_at=fixed)
        engine = _engine_with_encoder(
            [(mem, 0.5)],
            content_vecs={"既知内容": np.array([0.8, 0.2])},
        )
        result = await engine.search(SearchQuery(text="q", top_k=5, rank_policy=RankPolicy()))
        assert result.is_ok
        expected = 0.3 * decay + 0.3 * 0.5 + 0.4 * 0.8
        assert result.value[0].score == pytest.approx(expected, abs=1e-6)
