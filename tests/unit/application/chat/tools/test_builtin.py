"""Tests for execute_tool() MCP routing gate (__ 判定)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nous.application.chat.tools.builtin import execute_tool


@pytest.fixture
def mock_ctx():
    """Minimal AppContext mock."""
    ctx = MagicMock()
    ctx.persona = "test_persona"
    ctx.event_bus = AsyncMock()
    return ctx


@pytest.fixture
def mock_config():
    """Minimal ChatConfig mock with default MCP servers."""
    cfg = MagicMock()
    cfg.mcp_servers = [
        {
            "name": "opensandbox",
            "transport": "http",
            "url": "http://opensandbox-mcp:8000/mcp",
            "enabled": True,
        },
        {
            "name": "playwright",
            "transport": "http",
            "url": "http://playwright:8931/sse",
            "enabled": True,
        },
    ]
    return cfg


@pytest.fixture
def mock_config_no_mcp():
    """ChatConfig with empty MCP servers list."""
    cfg = MagicMock()
    cfg.mcp_servers = []
    return cfg


# ===================================================================
# __ routing gate
# ===================================================================


class TestExecuteToolMcpRouting:
    """execute_tool() の __ ルーティング動作検証."""

    @pytest.mark.asyncio
    async def test_routes_to_mcp_pool(self, mock_ctx, mock_config):
        """__ を含むツール名 → MCPClientPool.call_tool() が呼ばれる"""
        mock_pool = AsyncMock()
        mock_pool.call_tool.return_value = {"result": "code output", "isError": False}

        with patch(
            "nous.infrastructure.mcp_client.pool.MCPClientPool",
            return_value=mock_pool,
        ):
            result = await execute_tool(
                mock_ctx,
                mock_config,
                "opensandbox__execute_code",
                {"code": "print('hello')", "language": "python"},
            )

        mock_pool.call_tool.assert_called_once_with(
            "opensandbox__execute_code",
            {"code": "print('hello')", "language": "python"},
        )
        assert result == {"result": "code output", "isError": False}

    @pytest.mark.asyncio
    async def test_returns_error_when_mcp_returns_error_dict(self, mock_ctx, mock_config):
        """MCP pool が error を含む dict を返した → status: error"""
        mock_pool = AsyncMock()
        mock_pool.call_tool.return_value = {"error": "MCP server not found: opensandbox"}

        with patch(
            "nous.infrastructure.mcp_client.pool.MCPClientPool",
            return_value=mock_pool,
        ):
            result = await execute_tool(
                mock_ctx,
                mock_config,
                "opensandbox__execute_code",
                {"code": "print('hello')"},
            )

        assert result == {
            "status": "error",
            "message": "MCP server not found: opensandbox",
        }

    @pytest.mark.asyncio
    async def test_no_mcp_servers_configured(self, mock_ctx, mock_config_no_mcp):
        """MCP サーバーが未設定 (mcp_servers=[]) → status: error"""
        result = await execute_tool(
            mock_ctx,
            mock_config_no_mcp,
            "opensandbox__execute_code",
            {"code": "print('hello')"},
        )

        assert result["status"] == "error"
        assert "MCP server not found" in result["message"]

    @pytest.mark.asyncio
    async def test_exception_during_mcp_call(self, mock_ctx, mock_config):
        """MCP pool.call_tool() が例外を送出 → status: error"""
        mock_pool = AsyncMock()
        mock_pool.call_tool.side_effect = RuntimeError("Connection refused")

        with patch(
            "nous.infrastructure.mcp_client.pool.MCPClientPool",
            return_value=mock_pool,
        ):
            result = await execute_tool(
                mock_ctx,
                mock_config,
                "opensandbox__execute_code",
                {"code": "print('hello')"},
            )

        assert result["status"] == "error"
        assert "Connection refused" in result["message"]

    @pytest.mark.asyncio
    async def test_builtin_tool_still_works(self, mock_ctx, mock_config):
        """__ を含まないツール名は従来通り builtin dispatch を通る"""
        from nous.application.chat.tools.builtin import _BUILTIN_DISPATCH

        original = _BUILTIN_DISPATCH.get("search")

        try:
            mock_handler = AsyncMock(return_value={"status": "ok", "results": []})
            _BUILTIN_DISPATCH["search"] = mock_handler

            result = await execute_tool(mock_ctx, mock_config, "search", {"query": "test"})

            mock_handler.assert_called_once_with(mock_ctx, mock_config, {"query": "test"})
            assert result == {"status": "ok", "results": []}
        finally:
            if original:
                _BUILTIN_DISPATCH["search"] = original
            else:
                _BUILTIN_DISPATCH.pop("search", None)

    @pytest.mark.asyncio
    async def test_unknown_tool_without_underscore(self, mock_ctx, mock_config):
        """__ なし・未登録のツール → 'Unknown tool'"""
        result = await execute_tool(mock_ctx, mock_config, "nonexistent_tool", {})

        assert result["status"] == "error"
        assert "Unknown tool" in result["message"]
