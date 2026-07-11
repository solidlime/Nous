"""Tests for persona router cleanup functions.

Focuses on _cleanup_opensandbox_sandboxes best-effort behavior.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from nous.api.http.routers.persona import _cleanup_opensandbox_sandboxes, _parse_mcp_response


class TestParseMcpResponse:
    """Tests for _parse_mcp_response."""

    def test_plain_json(self) -> None:
        text = '{"jsonrpc":"2.0","result":{"sandboxes":[]},"id":1}'
        result = _parse_mcp_response(text)
        assert result["id"] == 1

    def test_sse_streaming(self) -> None:
        text = 'event: result\ndata: {"jsonrpc":"2.0","result":{"sandboxes":[]},"id":1}\n'
        result = _parse_mcp_response(text)
        assert result["id"] == 1

    def test_sse_first_data_wins(self) -> None:
        """First data: line wins (MCP single-response protocol)."""
        text = 'event: ping\ndata: {"status":"ok"}\n\nevent: result\ndata: {"jsonrpc":"2.0","result":["a"],"id":2}\n'
        result = _parse_mcp_response(text)
        assert result["status"] == "ok"

    def test_no_data_prefix_fallback(self) -> None:
        """Plain JSON without data: prefix is parsed directly."""
        text = '{"jsonrpc":"2.0","result":{"id":"sbx-1"},"id":1}'
        result = _parse_mcp_response(text)
        assert result["result"]["id"] == "sbx-1"


class TestCleanupOpenSandboxSandboxes:
    """Tests for _cleanup_opensandbox_sandboxes best-effort semantics."""

    @pytest.mark.asyncio
    async def test_successful_cleanup(self) -> None:
        """Cleanup lists and deletes all sandboxes."""
        mock_client = MagicMock(spec=httpx.AsyncClient)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        # Mock sandbox_list response with two sandboxes
        list_resp = MagicMock()
        list_resp.text = '{"jsonrpc":"2.0","result":[{"id":"sbx-1"},{"id":"sbx-2"}],"id":1}'
        mock_client.post = AsyncMock(return_value=list_resp)

        with patch("httpx.AsyncClient", return_value=mock_client):
            await _cleanup_opensandbox_sandboxes("test-persona")

        assert mock_client.post.call_count == 3  # 1 list + 2 delete
        calls = mock_client.post.call_args_list
        # First call: sandbox_list
        assert calls[0][1]["json"]["method"] == "tools/call"
        assert calls[0][1]["json"]["params"]["name"] == "sandbox_list"
        # Second call: sandbox_kill sbx-1
        assert calls[1][1]["json"]["params"]["name"] == "sandbox_kill"
        assert calls[1][1]["json"]["params"]["arguments"]["sandbox_id"] == "sbx-1"
        # Third call: sandbox_kill sbx-2
        assert calls[2][1]["json"]["params"]["name"] == "sandbox_kill"
        assert calls[2][1]["json"]["params"]["arguments"]["sandbox_id"] == "sbx-2"

    @pytest.mark.asyncio
    async def test_empty_sandbox_list(self) -> None:
        """No sandboxes to delete → nothing crashes."""
        mock_client = MagicMock(spec=httpx.AsyncClient)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        list_resp = MagicMock()
        list_resp.text = '{"jsonrpc":"2.0","result":[],"id":1}'
        mock_client.post = AsyncMock(return_value=list_resp)

        with patch("httpx.AsyncClient", return_value=mock_client):
            await _cleanup_opensandbox_sandboxes("test-persona")

        # Only the list call should have been made
        assert mock_client.post.call_count == 1

    @pytest.mark.asyncio
    async def test_network_error_is_silent(self) -> None:
        """Network errors are caught and logged, not propagated."""
        with patch("httpx.AsyncClient", side_effect=RuntimeError("connection refused")):
            # Should not raise
            await _cleanup_opensandbox_sandboxes("test-persona")

    @pytest.mark.asyncio
    async def test_parse_error_is_silent(self) -> None:
        """Invalid response from sandbox_list is caught."""
        mock_client = MagicMock(spec=httpx.AsyncClient)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        list_resp = MagicMock()
        list_resp.text = "not-json"
        mock_client.post = AsyncMock(return_value=list_resp)

        with patch("httpx.AsyncClient", return_value=mock_client):
            # Should not raise
            await _cleanup_opensandbox_sandboxes("test-persona")

    @pytest.mark.asyncio
    async def test_sandbox_kill_failure_continues(self) -> None:
        """If one sandbox_kill fails, other deletions continue."""
        mock_client = MagicMock(spec=httpx.AsyncClient)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        list_resp = MagicMock()
        list_resp.text = '{"jsonrpc":"2.0","result":[{"id":"sbx-ok"},{"id":"sbx-fail"}],"id":1}'

        async def _mock_post(url, **kwargs) -> MagicMock:  # noqa: ARG001
            if kwargs.get("json", {}).get("params", {}).get("arguments", {}).get("sandbox_id") == "sbx-fail":
                raise RuntimeError("kill failed")
            resp = MagicMock()
            resp.text = '{"jsonrpc":"2.0","result":{},"id":1}'
            return resp

        mock_client.post = _mock_post

        with patch("httpx.AsyncClient", return_value=mock_client):
            await _cleanup_opensandbox_sandboxes("test-persona")
