"""Pact consumer contract tests for memory_create tool."""

from __future__ import annotations

import json

import pytest
import requests
from pact import match


class TestMemoryCreate:
    """Contract tests for memory_create MCP tool."""

    @pytest.mark.contract
    def test_create_memory_success(self, pact, mcp_request):
        """Normal: content='test', importance=0.5 → ok + key (mem_...)."""
        expected = json.dumps({"ok": True, "key": "mem_test123", "auto_emotion": True})
        (
            pact.upon_receiving("memory_create success")
            .with_request("POST", "/")
            .with_body(
                {
                    "jsonrpc": "2.0",
                    "method": "tools/call",
                    "params": {
                        "name": "memory_create",
                        "arguments": {"content": "test", "importance": 0.5},
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
                                    regex=r'\{"ok": true, "key": "mem_\w+", "auto_emotion": true\}',
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
                json=mcp_request("memory_create", {"content": "test", "importance": 0.5}),
                timeout=5,
            )

        assert response.status_code == 200
        body = response.json()
        assert body["jsonrpc"] == "2.0"
        assert not body["result"]["isError"]
        text = json.loads(body["result"]["content"][0]["text"])
        assert text["ok"] is True
        assert text["key"].startswith("mem_")

    @pytest.mark.contract
    def test_create_memory_empty_content(self, pact, mcp_request):
        """Error: content='' → content is required."""
        (
            pact.upon_receiving("memory_create empty content")
            .with_request("POST", "/")
            .with_body(
                {
                    "jsonrpc": "2.0",
                    "method": "tools/call",
                    "params": {
                        "name": "memory_create",
                        "arguments": {"content": ""},
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
                                "text": match.regex("content is required", regex=r".*content is required.*"),
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
                json=mcp_request("memory_create", {"content": ""}, id_val=2),
                timeout=5,
            )

        assert response.status_code == 200
        body = response.json()
        assert body["result"]["isError"]

    @pytest.mark.contract
    def test_create_memory_invalid_importance(self, pact, mcp_request):
        """Validation: importance=1.5 → must be between 0.0 and 1.0."""
        (
            pact.upon_receiving("memory_create invalid importance")
            .with_request("POST", "/")
            .with_body(
                {
                    "jsonrpc": "2.0",
                    "method": "tools/call",
                    "params": {
                        "name": "memory_create",
                        "arguments": {"content": "test", "importance": 1.5},
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
                                "text": match.regex(
                                    "importance must be between 0.0 and 1.0",
                                    regex=r".*importance must be between 0.0 and 1.0.*",
                                ),
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
                json=mcp_request("memory_create", {"content": "test", "importance": 1.5}, id_val=3),
                timeout=5,
            )

        assert response.status_code == 200
        body = response.json()
        assert body["result"]["isError"]

    @pytest.mark.contract
    def test_create_memory_empty_tag(self, pact, mcp_request):
        """Validation: tags=[''] → error."""
        (
            pact.upon_receiving("memory_create empty tag")
            .with_request("POST", "/")
            .with_body(
                {
                    "jsonrpc": "2.0",
                    "method": "tools/call",
                    "params": {
                        "name": "memory_create",
                        "arguments": {"content": "test", "tags": [""]},
                    },
                    "id": match.integer(4),
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
                                "text": match.regex("tag", regex=r".*tag.*"),
                            }
                        ],
                        "isError": True,
                    },
                    "id": match.integer(4),
                },
                "application/json",
            )
        )

        with pact.serve() as server:
            response = requests.post(
                server.url,
                json=mcp_request("memory_create", {"content": "test", "tags": [""]}, id_val=4),
                timeout=5,
            )

        assert response.status_code == 200
        body = response.json()
        assert body["result"]["isError"]
