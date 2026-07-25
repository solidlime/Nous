"""Pact consumer contract tests for memory_delete tool."""

from __future__ import annotations

import pytest
import requests
from pact import match


class TestMemoryDelete:
    """Contract tests for memory_delete MCP tool."""

    @pytest.mark.contract
    def test_delete_memory_by_key(self, pact, mcp_request):
        """Key specified → ok."""
        (
            pact.upon_receiving("memory_delete by key")
            .with_request("POST", "/")
            .with_body(
                {
                    "jsonrpc": "2.0",
                    "method": "tools/call",
                    "params": {
                        "name": "memory_delete",
                        "arguments": {"memory_key": "mem_xxx"},
                    },
                    "id": match.integer(1),
                },
                "application/json",
            )
            .will_respond_with(200)
            .with_body(
                {
                    "jsonrpc": "2.0",
                    "result": {
                        "content": [
                            {
                                "type": "text",
                                "text": match.regex(
                                    "Memory tombstoned",
                                    regex=r"Memory tombstoned: mem_\w+",
                                ),
                            }
                        ],
                        "isError": False,
                    },
                    "id": match.integer(1),
                },
                "application/json",
            )
        )

        with pact.serve() as server:
            response = requests.post(
                server.url,
                json=mcp_request("memory_delete", {"memory_key": "mem_xxx"}),
                timeout=5,
            )

        assert response.status_code == 200
        body = response.json()
        assert not body["result"]["isError"]
        text = body["result"]["content"][0]["text"]
        assert "Memory tombstoned" in text

    @pytest.mark.contract
    def test_delete_memory_by_query(self, pact, mcp_request):
        """Query specified → ok with deleted count."""
        (
            pact.upon_receiving("memory_delete by query")
            .with_request("POST", "/")
            .with_body(
                {
                    "jsonrpc": "2.0",
                    "method": "tools/call",
                    "params": {
                        "name": "memory_delete",
                        "arguments": {"query": "test"},
                    },
                    "id": match.integer(2),
                },
                "application/json",
            )
            .will_respond_with(200)
            .with_body(
                {
                    "jsonrpc": "2.0",
                    "result": {
                        "content": [
                            {
                                "type": "text",
                                "text": match.regex(
                                    "Memory tombstoned",
                                    regex=r"Memory tombstoned: mem_\w+",
                                ),
                            }
                        ],
                        "isError": False,
                    },
                    "id": match.integer(2),
                },
                "application/json",
            )
        )

        with pact.serve() as server:
            response = requests.post(
                server.url,
                json=mcp_request("memory_delete", {"query": "test"}, id_val=2),
                timeout=5,
            )

        assert response.status_code == 200
        body = response.json()
        assert not body["result"]["isError"]
