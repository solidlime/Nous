"""Pact consumer contract tests for memory_search tool."""

from __future__ import annotations

import json

import pytest
import requests
from pact import match


class TestMemorySearch:
    """Contract tests for memory_search MCP tool."""

    @pytest.mark.contract
    def test_search_memory_query(self, pact, mcp_request):
        """Query specified → search results."""
        search_response = json.dumps(
            {
                "ok": True,
                "memories": [
                    {
                        "key": "mem_001",
                        "content": "test result",
                        "importance": 0.8,
                        "tags": ["test"],
                        "emotion": "joy",
                        "score": 0.95,
                    }
                ],
                "total_count": 1,
            }
        )
        (
            pact.upon_receiving("memory_search with query")
            .with_request("POST", "/")
            .with_body(
                {
                    "jsonrpc": "2.0",
                    "method": "tools/call",
                    "params": {
                        "name": "memory_search",
                        "arguments": {"query": "test"},
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
                                    search_response,
                                    regex=r'\{"ok": true, "memories": \[\{.*"key": "mem_\w+".*\], "total_count": \d+\}',
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
                json=mcp_request("memory_search", {"query": "test"}),
                timeout=5,
            )

        assert response.status_code == 200
        body = response.json()
        text = json.loads(body["result"]["content"][0]["text"])
        assert text["ok"] is True
        assert "memories" in text

    @pytest.mark.contract
    def test_search_memory_with_filters(self, pact, mcp_request):
        """Filters: tags + min_importance → filtered results."""
        filtered_response = json.dumps(
            {
                "ok": True,
                "memories": [
                    {
                        "key": "mem_002",
                        "content": "goal memory",
                        "importance": 0.7,
                        "tags": ["goal"],
                        "emotion": "neutral",
                        "score": 0.85,
                    }
                ],
                "total_count": 1,
            }
        )
        (
            pact.upon_receiving("memory_search with filters")
            .with_request("POST", "/")
            .with_body(
                {
                    "jsonrpc": "2.0",
                    "method": "tools/call",
                    "params": {
                        "name": "memory_search",
                        "arguments": {"query": "test", "tags": ["goal"], "min_importance": 0.5},
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
                                    filtered_response,
                                    regex=r'\{"ok": true, "memories": \[.*\], "total_count": \d+\}',
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
                json=mcp_request(
                    "memory_search",
                    {"query": "test", "tags": ["goal"], "min_importance": 0.5},
                    id_val=2,
                ),
                timeout=5,
            )

        assert response.status_code == 200
        body = response.json()
        assert not body["result"]["isError"]

    @pytest.mark.contract
    def test_search_memory_empty_query(self, pact, mcp_request):
        """Error: query='' → error."""
        (
            pact.upon_receiving("memory_search empty query")
            .with_request("POST", "/")
            .with_body(
                {
                    "jsonrpc": "2.0",
                    "method": "tools/call",
                    "params": {
                        "name": "memory_search",
                        "arguments": {"query": ""},
                    },
                    "id": match.integer(3),
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
                                "text": match.regex("query", regex=r".*[Qq]uery.*"),
                            }
                        ],
                        "isError": True,
                    },
                    "id": match.integer(3),
                },
                "application/json",
            )
        )

        with pact.serve() as server:
            response = requests.post(
                server.url,
                json=mcp_request("memory_search", {"query": ""}, id_val=3),
                timeout=5,
            )

        assert response.status_code == 200
        body = response.json()
        assert body["result"]["isError"]
