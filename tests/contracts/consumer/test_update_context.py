"""Pact consumer contract tests for update_context tool."""

from __future__ import annotations

import pytest
import requests
from pact import match


class TestUpdateContext:
    """Contract tests for update_context MCP tool."""

    @pytest.mark.contract
    def test_update_context_with_emotion(self, pact, mcp_request):
        """Normal: emotion + context_note → ok + result."""
        (
            pact.upon_receiving("update_context with emotion")
            .with_request("POST", "/")
            .with_body(
                {
                    "jsonrpc": "2.0",
                    "method": "tools/call",
                    "params": {
                        "name": "update_context",
                        "arguments": {
                            "emotion": "happy",
                            "context_note": "test",
                        },
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
                                    "Context updated",
                                    regex=r"Context updated: .+",
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
                json=mcp_request(
                    "update_context",
                    {"emotion": "happy", "context_note": "test"},
                ),
                timeout=5,
            )

        assert response.status_code == 200
        body = response.json()
        assert not body["result"]["isError"]
        assert "Context updated" in body["result"]["content"][0]["text"]

    @pytest.mark.contract
    def test_update_context_no_params(self, pact, mcp_request):
        """All parameters omitted → ok (default values)."""
        (
            pact.upon_receiving("update_context no params")
            .with_request("POST", "/")
            .with_body(
                {
                    "jsonrpc": "2.0",
                    "method": "tools/call",
                    "params": {
                        "name": "update_context",
                        "arguments": {},
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
                                    "No changes made",
                                    regex=r"No changes made.*",
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
                json=mcp_request("update_context", {}, id_val=2),
                timeout=5,
            )

        assert response.status_code == 200
        body = response.json()
        assert not body["result"]["isError"]
        text = body["result"]["content"][0]["text"]
        assert "No changes made" in text
