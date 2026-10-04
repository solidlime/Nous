"""チャット経路の検索ログ記録（search_log テーブル）の unit test。

MCP memory_search だけが log_search を呼んでいたため、チャットパイプラインの
実クエリが評価素材として残らなかった。検索の直後に 2 クエリ分を記録する。
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


def _ctx(mems_per_query: int = 2) -> MagicMock:
    ctx = MagicMock()
    results = [
        SearchResult(memory=_mem(f"m{i}"), score=1.0 - i * 0.01, source="semantic") for i in range(mems_per_query)
    ]
    ctx.search_engine.search = AsyncMock(return_value=Success(results))
    ctx.memory_service.log_search = MagicMock(return_value=Success(None))
    return ctx


@pytest.mark.asyncio
async def test_log_search_called_for_each_query():
    from nous.application.chat.pipeline.memory_retriever import _search_memories

    ctx = _ctx()
    await _search_memories(ctx, "ユーザーメッセージ", "直前の応答", ChatConfig(), top_k=5)

    calls = ctx.memory_service.log_search.call_args_list
    assert [c.args[0] for c in calls] == ["ユーザーメッセージ", "直前の応答"]
    assert all(c.args[1] == "hybrid" for c in calls)
    # result_count は当該クエリの検索ヒット件数
    assert all(c.args[2] == 2 for c in calls)


@pytest.mark.asyncio
async def test_single_query_logged_once():
    from nous.application.chat.pipeline.memory_retriever import _search_memories

    ctx = _ctx()
    await _search_memories(ctx, "ユーザーメッセージ", None, ChatConfig(), top_k=5)
    assert ctx.memory_service.log_search.call_count == 1


@pytest.mark.asyncio
async def test_log_search_failure_does_not_break_search():
    """log_search が例外を投げても検索結果は返る（best-effort）。"""
    from nous.application.chat.pipeline.memory_retriever import _search_memories

    ctx = _ctx()
    ctx.memory_service.log_search = MagicMock(side_effect=RuntimeError("db locked"))
    _text, _dbg, mems = await _search_memories(ctx, "q", None, ChatConfig(), top_k=5)
    assert len(mems) == 2


@pytest.mark.asyncio
async def test_log_search_skipped_when_memory_service_missing():
    """memory_service を持たない ctx でも落ちない。"""
    from nous.application.chat.pipeline.memory_retriever import _search_memories

    ctx = _ctx()
    del ctx.memory_service
    _text, _dbg, mems = await _search_memories(ctx, "q", None, ChatConfig(), top_k=5)
    assert len(mems) == 2
