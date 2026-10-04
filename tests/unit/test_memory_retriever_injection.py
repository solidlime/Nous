"""注入済み記憶の排除（ASIST memoryIds 方式）の unit test。

同一セッション内で既にプロンプトに注入した記憶は、次ターン以降の検索から
除外する。順位は変えず「上位から未注入のみを選ぶ」ので MRR は悪化しない。
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from nous.domain.chat_config import ChatConfig
from nous.domain.memory.entities import Memory
from nous.domain.search.engine import SearchResult
from nous.domain.shared.result import Success
from nous.domain.shared.time_utils import get_now


def _mem(key: str) -> Memory:
    now = get_now()
    return Memory(key=key, content=f"content-{key}", created_at=now, updated_at=now, importance=0.9)


def _ctx_with(mems: list[Memory]) -> MagicMock:
    ctx = MagicMock()
    results = [SearchResult(memory=m, score=1.0 - i * 0.01, source="semantic") for i, m in enumerate(mems)]
    ctx.search_engine.search = AsyncMock(return_value=Success(results))
    return ctx


@pytest.mark.asyncio
async def test_already_injected_keys_excluded():
    from nous.application.chat.pipeline.memory_retriever import _search_memories

    ctx = _ctx_with([_mem("a"), _mem("b")])
    injected: set[str] = {"a"}
    _text, _dbg, mems = await _search_memories(ctx, "q", None, ChatConfig(), top_k=5, injected_keys=injected)
    assert [m.key for m in mems] == ["b"]


@pytest.mark.asyncio
async def test_uninjected_keys_pass_and_are_recorded():
    from nous.application.chat.pipeline.memory_retriever import _search_memories

    ctx = _ctx_with([_mem("a"), _mem("b")])
    injected: set[str] = set()
    _text, _dbg, mems = await _search_memories(ctx, "q", None, ChatConfig(), top_k=5, injected_keys=injected)
    assert [m.key for m in mems] == ["a", "b"]
    # 注入決定した key は set に記録される（次ターンの除外材料）
    assert injected == {"a", "b"}


@pytest.mark.asyncio
async def test_top_k_applied_after_exclusion_without_refill():
    """除外で top_k 未満になっても 2 巡検索しない（減件のまま）。"""
    from nous.application.chat.pipeline.memory_retriever import _search_memories

    ctx = _ctx_with([_mem("a"), _mem("b")])
    _text, _dbg, mems = await _search_memories(ctx, "q", None, ChatConfig(), top_k=5, injected_keys={"a"})
    # 候補2件から除外して1件 — top_k(5) 未満だが補充検索はしない
    assert [m.key for m in mems] == ["b"]
    assert ctx.search_engine.search.await_count == 1


@pytest.mark.asyncio
async def test_second_call_excludes_first_call_keys():
    """同一 session の set を共有すると 2 巡目に 1 巡目の key が現れない。"""
    from nous.application.chat.pipeline.memory_retriever import _search_memories

    ctx = _ctx_with([_mem("a"), _mem("b")])
    injected: set[str] = set()
    _t1, _d1, first = await _search_memories(ctx, "q", None, ChatConfig(), top_k=5, injected_keys=injected)
    assert [m.key for m in first] == ["a", "b"]
    _t2, _d2, second = await _search_memories(ctx, "q", None, ChatConfig(), top_k=5, injected_keys=injected)
    assert second == []


@pytest.mark.asyncio
async def test_injected_keys_none_keeps_legacy_behavior():
    """injected_keys 未指定（既存呼び出し）は従来通り全件返す。"""
    from nous.application.chat.pipeline.memory_retriever import _search_memories

    ctx = _ctx_with([_mem("a"), _mem("b")])
    _text, _dbg, mems = await _search_memories(ctx, "q", None, ChatConfig(), top_k=5)
    assert [m.key for m in mems] == ["a", "b"]


def test_tree_session_owns_injected_key_set():
    from nous.application.chat.tree_session import TreeSessionWindow

    assert TreeSessionWindow()._injected_memory_keys == set()


@pytest.mark.asyncio
async def test_prepare_passes_session_set_to_search():
    """PrepareStep が session の注入済み set を検索へ伝える（配線確認）。"""
    from contextlib import nullcontext
    from types import SimpleNamespace
    from unittest.mock import patch as _patch

    from nous.application.chat.pipeline.context import ChatTurnContext
    from nous.application.chat.pipeline.prepare import PrepareStep
    from nous.domain.persona.entities import PersonaState

    captured: dict = {}

    async def _fake_search(_ctx, _user, _last, _config, **kwargs):
        captured.update(kwargs)
        return "", {}, []

    state = PersonaState(persona="t")
    ctx = MagicMock()
    ctx.persona = "t"
    ctx.persona_service.get_context.return_value = Success(state)
    injected: set[str] = set()
    session = SimpleNamespace(pending_memory_task=None, _messages=[], _injected_memory_keys=injected)
    config = SimpleNamespace(
        context_compression_mode="light",
        memory_preload_count=3,
        episode_search_enabled=False,
        show_message_timestamps=False,
        memory_digest_count=0,
    )
    with (
        _patch("nous.application.chat.pipeline.prepare._search_memories", _fake_search),
        _patch("nous.application.chat.pipeline.prepare._build_context_section", AsyncMock(return_value="")),
        nullcontext(),
    ):
        await PrepareStep().run(ctx, session, ChatTurnContext(session_id="s", user_message="hi"), config)
    assert captured.get("injected_keys") is injected
