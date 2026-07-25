"""Pact consumer contract tests for goal_manage tool."""

from __future__ import annotations

import pytest
import requests
from pact import match


class TestGoalManage:
    """Contract tests for goal_manage MCP tool."""

    @pytest.mark.contract
    def test_goal_manage_create(self, pact, mcp_request):
        """Operation create → ok + key."""
        (
            pact.upon_receiving("goal_manage create")
            .with_request("POST", "/")
            .with_body(
                {
                    "jsonrpc": "2.0",
                    "method": "tools/call",
                    "params": {
                        "name": "goal_manage",
                        "arguments": {
                            "operation": "create",
                            "content": "test goal",
                            "scope": "self",
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
                                    "Goal created: mem_goal_001",
                                    regex=r"Goal created: mem_\w+",
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
                    "goal_manage",
                    {"operation": "create", "content": "test goal", "scope": "self"},
                ),
                timeout=5,
            )

        assert response.status_code == 200
        body = response.json()
        assert not body["result"]["isError"]
        text = body["result"]["content"][0]["text"]
        assert "Goal created" in text

    @pytest.mark.contract
    def test_goal_manage_list(self, pact, mcp_request):
        """Operation list → goals list."""
        (
            pact.upon_receiving("goal_manage list")
            .with_request("POST", "/")
            .with_body(
                {
                    "jsonrpc": "2.0",
                    "method": "tools/call",
                    "params": {
                        "name": "goal_manage",
                        "arguments": {
                            "operation": "list",
                            "scope": "self",
                        },
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
                                    "Active goals",
                                    regex=r"Active goals \(scope=self\):\n.*",
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
                json=mcp_request("goal_manage", {"operation": "list", "scope": "self"}, id_val=2),
                timeout=5,
            )

        assert response.status_code == 200
        body = response.json()
        assert not body["result"]["isError"]
        assert "Active goals" in body["result"]["content"][0]["text"]

    @pytest.mark.contract
    def test_goal_manage_invalid_operation(self, pact, mcp_request):
        """Unknown operation → error."""
        (
            pact.upon_receiving("goal_manage invalid operation")
            .with_request("POST", "/")
            .with_body(
                {
                    "jsonrpc": "2.0",
                    "method": "tools/call",
                    "params": {
                        "name": "goal_manage",
                        "arguments": {
                            "operation": "invalid",
                        },
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
                                    "Unknown operation",
                                    regex=r".*Unknown operation.*",
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
                json=mcp_request("goal_manage", {"operation": "invalid"}, id_val=3),
                timeout=5,
            )

        assert response.status_code == 200
        body = response.json()
        assert body["result"]["isError"]
