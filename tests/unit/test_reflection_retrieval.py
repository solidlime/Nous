"""リフレクション記憶の検索降格と注入フィルタ（無関係想起対策）。

reflection タグ付き記憶は主題不定の抽象文 (importance 高め) で、通常検索に
無選別混入する。MemGPT archival 分離相当の対処:
① 複合スコアの reflection ペナルティ係数——適用は SearchEngine の RankPolicy 段
   （真の recall 経路）に移設: ``tests/unit/test_search_rank_policy.py``。
   caller（memory_retriever）は config 値から RankPolicy を組み立てて渡すだけ。
② 無条件注入に相対閾値フィルタ (max_sim - margin AND floor)。
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import numpy as np
import pytest

from nous.domain.chat_config import ChatConfig
from nous.domain.memory.entities import Memory
from nous.domain.search.engine import SearchResult
from nous.domain.shared.result import Success
from nous.domain.shared.time_utils import get_now


def _mem(
    key: str,
    content: str,
    tags: list[str] | None = None,
    importance: float = 0.9,
    created_at=None,
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


def _state() -> SimpleNamespace:
    return SimpleNamespace(
        persona="herta",
        emotion="",
        emotion_intensity=0.0,
        mental_state="",
        physical_state="",
        environment="",
        relationship_status="",
        user_info={},
        persona_info={},
    )


def _ctx_with_reflections(reflections: list[Memory], vecs: dict, config) -> MagicMock:
    """context_loader 用 ctx: reflection タグのみ返し、埋め込みは固定ベクトル辞書。"""
    ctx = MagicMock()
    ctx.connection.get_memory_db.side_effect = Exception("no db in unit test")

    def _by_tags(tags):
        if "reflection" in tags:
            return Success(reflections)
        return Success([])

    ctx.memory_service.get_by_tags = MagicMock(side_effect=_by_tags)
    ctx._embedding = MagicMock()
    ctx._embedding.encode = MagicMock(side_effect=lambda text, is_query=False: vecs[text])
    ctx._config = config
    return ctx


class TestReflectionPenaltyConfig:
    def test_penalty_clamped_01_to_1(self):
        from nous.domain.session_config import SessionConfig

        assert SessionConfig(reflection_retrieval_penalty=0.05).reflection_retrieval_penalty == 0.1
        assert SessionConfig(reflection_retrieval_penalty=2.0).reflection_retrieval_penalty == 1.0

    def test_similarity_threshold_clamped_0_to_1(self):
        from nous.domain.session_config import SessionConfig

        assert SessionConfig(reflection_injection_min_similarity=-0.1).reflection_injection_min_similarity == 0.0
        assert SessionConfig(reflection_injection_min_similarity=1.5).reflection_injection_min_similarity == 1.0

    def test_injection_margin_clamped_0_to_1(self):
        from nous.domain.session_config import SessionConfig

        assert SessionConfig(reflection_injection_margin=-0.5).reflection_injection_margin == 0.0
        assert SessionConfig(reflection_injection_margin=2.0).reflection_injection_margin == 1.0
        assert SessionConfig().reflection_injection_margin == 0.08


class TestRetrieverPassesRankPolicy:
    """caller（memory_retriever）は config 値で RankPolicy を組み立てて渡す。

    複合スコア計算本体は engine 側（test_search_rank_policy.py）に移設済み。
    """

    @pytest.mark.asyncio
    async def test_config_values_build_and_pass_rank_policy(self):
        """config の retrieval_* 重みと penalty が SearchQuery.rank_policy に載る。"""
        from nous.application.chat.pipeline.memory_retriever import _search_memories

        captured: list = []

        async def _search(q, *a, **kw):
            captured.append(q)
            return Success([])

        ctx = MagicMock()
        ctx.search_engine.search = AsyncMock(side_effect=_search)
        config = ChatConfig(
            retrieval_recency_weight=0.2,
            retrieval_importance_weight=0.3,
            retrieval_relevance_weight=0.5,
            reflection_retrieval_penalty=0.7,
        )
        _f, debug, mems = await _search_memories(ctx, "クエリ", None, config)
        assert captured
        q = captured[0]
        assert q.rank_policy is not None
        assert q.rank_policy.recency_weight == pytest.approx(0.2)
        assert q.rank_policy.importance_weight == pytest.approx(0.3)
        assert q.rank_policy.relevance_weight == pytest.approx(0.5)
        assert q.rank_policy.reflection_penalty == pytest.approx(0.7)
        # 真の recall 経路の契約は維持（RIF + valid_at）
        assert q.apply_rif is True
        assert q.valid_at is not None


class TestReflectionInjectionSimilarity:
    @pytest.mark.asyncio
    async def test_low_similarity_reflection_dropped(self):
        """類似度が閾値未満の reflection は注入から落ち、高いものは残る。"""
        from nous.application.chat.pipeline.context_loader import _build_context_section

        refs = [_mem("r1", "related"), _mem("r2", "unrelated")]
        vecs = {
            "ユーザーの発言": np.array([1.0, 0.0]),
            "related": np.array([1.0, 0.0]),
            "unrelated": np.array([0.0, 1.0]),
        }
        ctx = _ctx_with_reflections(refs, vecs, ChatConfig())
        turn_ctx = SimpleNamespace(user_message="ユーザーの発言")
        section = await _build_context_section(ctx, _state(), turn_ctx)
        assert "related" in section
        assert "unrelated" not in section

    @pytest.mark.asyncio
    async def test_zero_threshold_keeps_all(self):
        """閾値 0.0 → 無効（現行動作: 全 reflection 注入、埋め込みを呼ばない）。"""
        from nous.application.chat.pipeline.context_loader import _build_context_section

        refs = [_mem("r1", "related"), _mem("r2", "unrelated")]
        vecs: dict = {}
        ctx = _ctx_with_reflections(refs, vecs, ChatConfig(reflection_injection_min_similarity=0.0))
        turn_ctx = SimpleNamespace(user_message="ユーザーの発言")
        section = await _build_context_section(ctx, _state(), turn_ctx)
        assert "related" in section
        assert "unrelated" in section
        assert not ctx._embedding.encode.called

    @pytest.mark.asyncio
    async def test_no_embedding_fails_open(self):
        """埋め込みモデル無し → 現行動作（fail-open、全部注入）。"""
        from nous.application.chat.pipeline.context_loader import _build_context_section

        refs = [_mem("r1", "related"), _mem("r2", "unrelated")]
        ctx = _ctx_with_reflections(refs, {}, ChatConfig())
        ctx._embedding = None
        turn_ctx = SimpleNamespace(user_message="ユーザーの発言")
        section = await _build_context_section(ctx, _state(), turn_ctx)
        assert "related" in section
        assert "unrelated" in section


class TestReflectionInjectionMargin:
    """相対閾値: sim >= (max_sim - margin) AND sim >= floor。

    絶対コサインでは関連 (0.82-0.92) / 無関係 (0.73-0.84) の分布が重なるため、
    候補集合内の最大値との差で分離する。
    """

    def _vecs(self) -> dict:
        return {
            "ユーザーの発言": np.array([1.0, 0.0]),
            "best": np.array([0.9, 0.1]),  # cos 0.9
            "middle": np.array([0.8, 0.2]),  # cos 0.8
            "weak": np.array([0.5, 0.5]),  # cos 0.5
        }

    @pytest.mark.asyncio
    async def test_relative_margin_drops_second_tier(self):
        """floor は超えるが max-0.08 未満の候補は落とす。"""
        from nous.application.chat.pipeline.context_loader import _build_context_section

        refs = [_mem("r1", "best"), _mem("r2", "middle"), _mem("r3", "weak")]
        ctx = _ctx_with_reflections(refs, self._vecs(), ChatConfig(reflection_injection_margin=0.08))
        turn_ctx = SimpleNamespace(user_message="ユーザーの発言")
        section = await _build_context_section(ctx, _state(), turn_ctx)
        assert "best" in section
        # middle (0.8) は floor 0.45 以上だが max-0.08=0.82 未満 → 落ちる
        assert "middle" not in section
        assert "weak" not in section

    @pytest.mark.asyncio
    async def test_margin_1_ignores_relative_gate(self):
        """margin=1.0 → 相対ゲート無効、floor のみ効く。"""
        from nous.application.chat.pipeline.context_loader import _build_context_section

        refs = [_mem("r1", "best"), _mem("r2", "middle"), _mem("r3", "weak")]
        ctx = _ctx_with_reflections(refs, self._vecs(), ChatConfig(reflection_injection_margin=1.0))
        turn_ctx = SimpleNamespace(user_message="ユーザーの発言")
        section = await _build_context_section(ctx, _state(), turn_ctx)
        assert "best" in section
        assert "middle" in section
        assert "weak" in section

    @pytest.mark.asyncio
    async def test_single_candidate_floor_only(self):
        """候補1件は相対比較が自明に真 → floor のみ（旧絶対閾値と同一挙動）。"""
        from nous.application.chat.pipeline.context_loader import _build_context_section

        refs = [_mem("r1", "middle")]
        ctx = _ctx_with_reflections(refs, self._vecs(), ChatConfig(reflection_injection_margin=0.08))
        turn_ctx = SimpleNamespace(user_message="ユーザーの発言")
        section = await _build_context_section(ctx, _state(), turn_ctx)
        assert "middle" in section  # 0.8 >= floor 0.45 かつ max=自分 → 残る


class TestCosineRelevance:
    """caller 側のマージ: 2クエリ結果を memory.key で dedupe し max score を採用。

    relevance（絶対コサイン）の計算と複合スコアは engine の RankPolicy 段に
    移設済み（test_search_rank_policy.py）。
    """

    @pytest.mark.asyncio
    async def test_two_query_merge_takes_max(self):
        """2クエリ（user_message / last_assistant）のスコアは max 統合（加算しない）。"""
        from nous.application.chat.pipeline.memory_retriever import _search_memories

        mem = _mem("m1", "関連する記憶")

        async def _search(q, *a, **kw):
            if q.text == "クエリ":
                return Success([SearchResult(memory=mem, score=1.4, source="hybrid", cosine=1.0)])
            return Success([SearchResult(memory=mem, score=0.9, source="hybrid", cosine=0.5)])

        ctx = MagicMock()
        ctx.search_engine.search = AsyncMock(side_effect=_search)
        _f, debug, mems = await _search_memories(ctx, "クエリ", "前回の応答", ChatConfig())
        # max score 側（cos 1.0）が採用され、cos 0.5 と加算されたりしない
        assert debug["results"][0]["score"] == pytest.approx(1.4, abs=1e-3)
        assert debug["results"][0]["cosine"] == pytest.approx(1.0, abs=1e-3)
        assert mems[0] is mem
