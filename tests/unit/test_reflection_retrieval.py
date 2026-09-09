"""リフレクション記憶の検索降格と注入フィルタ（無関係想起対策）。

reflection タグ付き記憶は主題不定の抽象文 (importance 高め) で、通常検索に
無選別混入する。MemGPT archival 分離相当の対処:
① 検索複合スコアにペナルティ係数 ② 無条件注入にベクトル類似チェック。
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
