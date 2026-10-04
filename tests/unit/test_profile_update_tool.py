"""B-5: MCP ツール profile_update（profile block 全体リライト）."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from nous.api.mcp._tools_persona import _tool_profile_update
from nous.domain.shared.result import Failure, Success


def _ctx() -> MagicMock:
    ctx = MagicMock()
    ctx.persona = "herta"
    ctx.event_bus = AsyncMock()
    ctx.memory_service.upsert_profile_block.return_value = Success(None)
    return ctx


@pytest.mark.asyncio
async def test_success_rewrites_block():
    ctx = _ctx()
    r = await _tool_profile_update(ctx, "herta", "me", "私はヘルタ。")

    assert r["ok"] is True
    ctx.memory_service.upsert_profile_block.assert_called_once_with("herta", "me", "私はヘルタ。")


@pytest.mark.asyncio
async def test_invalid_target_rejected():
    ctx = _ctx()
    r = await _tool_profile_update(ctx, "herta", "other", "x")

    assert r["ok"] is False
    assert "other" in r["error"]
    ctx.memory_service.upsert_profile_block.assert_not_called()


@pytest.mark.asyncio
async def test_over_limit_rejected_with_3000_in_message():
    ctx = _ctx()
    r = await _tool_profile_update(ctx, "herta", "user", "あ" * 4000)

    assert r["ok"] is False
    assert "3000" in r["error"]
    ctx.memory_service.upsert_profile_block.assert_not_called()


@pytest.mark.asyncio
async def test_suspicious_chars_stripped_before_upsert():
    ctx = _ctx()
    # 私用領域 (U+E000) は 1 文字のみ（全体の 10% 未満）→ 該当文字だけ除去
    body = "自己像" + "あ" * 20 + "\ue000テキスト"
    r = await _tool_profile_update(ctx, "herta", "me", body)

    assert r["ok"] is True
    ctx.memory_service.upsert_profile_block.assert_called_once_with("herta", "me", "自己像" + "あ" * 20 + "テキスト")


@pytest.mark.asyncio
async def test_content_mostly_suspicious_discarded():
    ctx = _ctx()
    r = await _tool_profile_update(ctx, "herta", "me", "自己像\ue000")

    assert r["ok"] is False
    assert "empty" in r["error"]
    ctx.memory_service.upsert_profile_block.assert_not_called()


@pytest.mark.asyncio
async def test_upsert_failure_reported():
    ctx = _ctx()
    ctx.memory_service.upsert_profile_block.return_value = Failure(ValueError("db down"))
    r = await _tool_profile_update(ctx, "herta", "me", "内容")

    assert r["ok"] is False
    assert "db down" in r["error"]


def test_registered_tool_count_is_15():
    """B-5: 既存 14 ツール + profile_update = 15（既存ツール構成は不変）."""
    tools: dict[str, object] = {}

    def mock_tool_decorator():
        def decorator(func):
            tools[func.__name__] = func
            return func

        return decorator

    mock_mcp = MagicMock()
    mock_mcp.tool = mock_tool_decorator

    from nous.api.mcp.tools import register_tools

    register_tools(mock_mcp)

    assert len(tools) == 15
    assert "profile_update" in tools
