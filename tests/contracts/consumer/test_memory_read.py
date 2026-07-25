"""Pact consumer contract tests for memory_read tool."""

from __future__ import annotations

import json

import pytest
import requests
from pact import match


class TestMemoryRead:
    """Contract tests for memory_read MCP tool."""

    @pytest.mark.contract
    def test_read_memory_by_key(self, pact, mcp_request):
        """Key specified → text response with memory details."""
        (
            pact.upon_receiving("memory_read by key")
            .with_request("POST", "/")
            .with_body(
                {
                    "jsonrpc": "2.0",
                    "method": "tools/call",
                    "params": {
                        "name": "memory_read",
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
                                    "Key: mem_xxx\nContent: test\nImportance: 0.5\nEmotion: neutral (intensity: 0.5)\nTags: []\nCreated: 2026-01-01",
                                    regex=r"Key: mem_\w+\nContent: .+\nImportance: .+",
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
                json=mcp_request("memory_read", {"memory_key": "mem_xxx"}),
                timeout=5,
            )

        assert response.status_code == 200
        body = response.json()
        assert body["jsonrpc"] == "2.0"
        assert not body["result"]["isError"]
        text = body["result"]["content"][0]["text"]
        assert "Key:" in text
        assert "Content:" in text

    @pytest.mark.contract
    def test_read_memory_list(self, pact, mcp_request):
        """No key → JSON list response."""
        list_response = json.dumps(
            {
                "ok": True,
                "memories": [
                    {
                        "key": "mem_001",
                        "content": "test memory",
                        "importance": 0.5,
                        "emotion": "neutral",
                        "tags": ["test"],
                        "created_at": "2026-01-01 00:00:00",
                    }
                ],
                "total_count": 1,
            }
        )
        (
            pact.upon_receiving("memory_read list")
            .with_request("POST", "/")
            .with_body(
                {
                    "jsonrpc": "2.0",
                    "method": "tools/call",
                    "params": {
                        "name": "memory_read",
                        "arguments": {"limit": 5},
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
                                    list_response,
                                    regex=r'\{"ok": true, "memories": \[\{.*"key": "mem_\w+".*\], "total_count": \d+\}',
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
                json=mcp_request("memory_read", {"limit": 5}, id_val=2),
                timeout=5,
            )

        assert response.status_code == 200
        body = response.json()
        assert body["jsonrpc"] == "2.0"
        text = json.loads(body["result"]["content"][0]["text"])
        assert text["ok"] is True
        assert "memories" in text
