"""リフレクション記憶の検索降格と注入フィルタ（無関係想起対策）。

reflection タグ付き記憶は主題不定の抽象文 (importance 高め) で、通常検索に
無選別混入する。MemGPT archival 分離相当の対処:
① 検索複合スコアにペナルティ係数 (relevance は絶対コサイン) ② 無条件注入に
相対閾値フィルタ (max_sim - margin AND floor)。
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


def _mem(key: str, content: str, tags: list[str] | None = None, importance: float = 0.9) -> Memory:
    return Memory(
        key=key,
        content=content,
        created_at=get_now(),
        updated_at=get_now(),
        importance=importance,
        tags=tags or [],
    )


def _result(mem: Memory) -> SearchResult:
    return SearchResult(memory=mem, score=0.9, source="semantic")


def _ctx_with(results: list[SearchResult]) -> MagicMock:
    ctx = MagicMock()
    ctx.search_engine.search = AsyncMock(return_value=Success(results))
    return ctx


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


class TestReflectionRetrievalPenalty:
    @pytest.mark.asyncio
    async def test_reflection_ranked_below_equal_memory(self):
        """同スコアの通常記憶より reflection が降格すること（デフォルト penalty=0.5）。"""
        from nous.application.chat.pipeline.memory_retriever import _search_memories

        plain = _mem("m1", "よく使う道具の話")
        refl = _mem("m2", "私は最近の振る舞いを反省している", tags=["reflection"])
        ctx = _ctx_with([_result(refl), _result(plain)])
        _f, debug, mems = await _search_memories(ctx, "クエリ", None, ChatConfig())
        assert debug["results"][0]["content"] == "よく使う道具の話"
        assert mems[0] is plain

    @pytest.mark.asyncio
    async def test_penalty_1_is_noop(self):
        """penalty=1.0 → 無効化: RRF 順のまま（reflection 先頭）。"""
        from nous.application.chat.pipeline.memory_retriever import _search_memories

        refl = _mem("m2", "reflection文です", tags=["reflection"])
        plain = _mem("m1", "普通の記憶")
        ctx = _ctx_with([_result(refl), _result(plain)])
        config = ChatConfig(reflection_retrieval_penalty=1.0)
        _f, debug, _m = await _search_memories(ctx, "q", None, config)
        assert debug["results"][0]["content"] == "reflection文です"


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
    """memory_retriever の relevance: RRF → 絶対コサイン類似度。

    旧 RRF (上限≈0.13) では importance+recency 支配で新鮮な無関係事実が
    常時首位だった。絶対コサインで relevance_w が実質的に効く。
    """

    @staticmethod
    def _cos_ctx(results: list[SearchResult], content_vecs: dict[str, object]) -> MagicMock:
        ctx = _ctx_with(results)
        ctx._embedding = MagicMock()

        def _encode(text: str, is_query: bool = False):
            if is_query:
                return np.array([1.0, 0.0])
            return content_vecs[text]

        ctx._embedding.encode = MagicMock(side_effect=_encode)
        return ctx

    @pytest.mark.asyncio
    async def test_cosine_beats_fresh_importance(self):
        """関連度高×低importance が 無関係×高importance・新鮮 を上回る。"""
        from nous.application.chat.pipeline.memory_retriever import _search_memories

        fresh_unrelated = _mem("m1", "無関係トピックの話", importance=1.0)
        relevant = _mem("m2", "関連する記憶", importance=0.1)
        ctx = self._cos_ctx(
            [_result(fresh_unrelated), _result(relevant)],
            {"無関係トピックの話": np.array([0.0, 1.0]), "関連する記憶": np.array([0.9, 0.1])},
        )
        _f, debug, mems = await _search_memories(ctx, "クエリ", None, ChatConfig())
        # rel: 0.3*1.0 + 0.3*0.1 + 0.4*0.9 = 0.69 > unrelated: 0.3*1.0 + 0.3*1.0 + 0 = 0.6
        assert mems[0] is relevant
        assert debug["results"][0]["content"] == "関連する記憶"
        assert debug["results"][0]["cosine"] == pytest.approx(0.9, abs=1e-3)

    @pytest.mark.asyncio
    async def test_no_embedding_relevance_zero_fail_open(self):
        """埋め込み無し → relevance 0.0 で継続（fail-open、rec+imp のみでランク）。"""
        from nous.application.chat.pipeline.memory_retriever import _search_memories

        mem1 = _mem("m1", "記憶その1", importance=0.9)
        mem2 = _mem("m2", "記憶その2", importance=0.2)
        ctx = _ctx_with([_result(mem2), _result(mem1)])
        ctx._embedding = None
        _f, debug, mems = await _search_memories(ctx, "クエリ", None, ChatConfig())
        assert mems[0] is mem1
        assert debug["results"][0]["cosine"] == 0.0

    @pytest.mark.asyncio
    async def test_two_query_merge_takes_max(self):
        """2クエリの relevance は max 統合（加算しない）。"""
        from nous.application.chat.pipeline.memory_retriever import _search_memories

        mem = _mem("m1", "関連する記憶")
        ctx = _ctx_with([_result(mem)])
        ctx._embedding = MagicMock()
        ctx._embedding.encode = MagicMock(side_effect=lambda text, is_query=False: np.array([1.0, 0.0]))
        # user_message と last_assistant の両方で cos 0.9 → max 0.9 (0.9+0.9 ではない)
        _f, debug, _m = await _search_memories(ctx, "クエリ", "前回の応答", ChatConfig())
        assert debug["results"][0]["cosine"] == pytest.approx(1.0, abs=1e-3)
