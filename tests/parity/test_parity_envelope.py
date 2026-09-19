"""Red-first parity tests — audit C1: envelope contract / success heuristic.

Records the current asymmetry: MCP memory tools return a plain-text String
("No memory found ...", "Error: ...", ``str(dict)``) instead of a structured
``{ok, data, error}`` envelope, and the tool.called success classifier in
``_tools_helpers`` relies on a ``startswith("Error")`` string heuristic.

All tests assert the DESIRED contract and are xfail(strict=True) at current
HEAD (audit:C1). Remove the marker when the contract lands.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock

from nous.api.mcp import _tools_memory
from nous.api.mcp._tools_helpers import _tool_called_result_success
from nous.domain.shared.result import Success


async def test_memory_delete_missing_key_returns_envelope(mock_app_context):
    """Delete by query with no hits must return a structured envelope."""
    mock_app_context.search_engine.search = AsyncMock(return_value=Success([]))
    result = await _tools_memory._tool_memory_delete(mock_app_context, "p", query="no such memory anywhere")
    payload = json.loads(result)
    assert {"ok", "data", "error"} <= set(payload)
    assert payload["ok"] is False
    assert payload["error"]["code"] == "NOT_FOUND"


async def test_memory_stats_returns_envelope(mock_app_context):
    """memory_stats must return a JSON envelope, not str(some_dict)."""
    mock_app_context.memory_service.get_stats.return_value = Success(
        {"total": 3, "tags": {"food": 2}, "emotions": {"joy": 2}}
    )
    result = await _tools_memory._tool_memory_stats(mock_app_context, "p")
    payload = json.loads(result)
    assert "ok" in payload and "data" in payload and "error" in payload


def test_success_classification_is_structural():
    """The envelope's ``ok`` field is the success signal — classification must
    not depend on prose prefixes for envelope payloads. Legacy plain-text
    error prefixes stay classified as failures for pre-envelope compat.

    Note: prose that is neither envelope JSON nor a legacy error prefix
    (e.g. plain success text from pre-envelope core paths) is classified
    True by the compat heuristic; the MCP surface no longer emits such
    strings since the _envelope_wrap funnel (audit C1).
    """
    from nous.api.mcp._envelope import tool_error, tool_ok

    assert _tool_called_result_success(tool_ok("anything")) is True
    assert _tool_called_result_success(tool_error("NOT_FOUND", "nope")) is False
    assert _tool_called_result_success("Error: something broke") is False
    assert _tool_called_result_success("No memory found for query: x") is False
