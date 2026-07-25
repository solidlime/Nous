"""Pact consumer contract tests for memory_update tool."""

from __future__ import annotations

import json

import pytest
import requests
from pact import match


class TestMemoryUpdate:
    """Contract tests for memory_update MCP tool."""

    @pytest.mark.contract
    def test_update_memory_success(self, pact, mcp_request):
        """Normal: memory_key + content → ok + key."""
        expected = json.dumps({"ok": True, "key": "mem_xxx"})
        (
            pact.upon_receiving("memory_update success")
            .with_request("POST", "/")
            .with_body(
                {
                    "jsonrpc": "2.0",
                    "method": "tools/call",
                    "params": {
                        "name": "memory_update",
                        "arguments": {"memory_key": "mem_xxx", "content": "updated"},
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
                                    expected,
                                    regex=r'\{"ok": true, "key": "mem_\w+"\}',
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
                json=mcp_request("memory_update", {"memory_key": "mem_xxx", "content": "updated"}),
                timeout=5,
            )

        assert response.status_code == 200
        body = response.json()
        assert not body["result"]["isError"]
        text = json.loads(body["result"]["content"][0]["text"])
        assert text["ok"] is True
        assert "key" in text

    @pytest.mark.contract
    def test_update_memory_no_key(self, pact, mcp_request):
        """Error: memory_key='' → error."""
        (
            pact.upon_receiving("memory_update no key")
            .with_request("POST", "/")
            .with_body(
                {
                    "jsonrpc": "2.0",
                    "method": "tools/call",
                    "params": {
                        "name": "memory_update",
                        "arguments": {"memory_key": ""},
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
                                    "memory_key is required",
                                    regex=r".*memory_key is required.*",
                                ),
                            }
                        ],
                        "isError": True,
                    },
                    "id": match.integer(2),
                },
                "application/json",
            )
        )

        with pact.serve() as server:
            response = requests.post(
                server.url,
                json=mcp_request("memory_update", {"memory_key": ""}, id_val=2),
                timeout=5,
            )

        assert response.status_code == 200
        body = response.json()
        assert body["result"]["isError"]
