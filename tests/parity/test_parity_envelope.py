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

import pytest

from nous.api.mcp import _tools_memory
from nous.api.mcp._tools_helpers import _tool_called_result_success
from nous.domain.shared.result import Success


@pytest.mark.xfail(
    strict=True,
    reason="audit:C1 — memory_delete returns plain text instead of {ok,data,error} envelope",
)
async def test_memory_delete_missing_key_returns_envelope(mock_app_context):
    """Delete by query with no hits must return a structured envelope."""
    mock_app_context.search_engine.search = AsyncMock(return_value=Success([]))
    result = await _tools_memory._tool_memory_delete(mock_app_context, "p", query="no such memory anywhere")
    # Production returns plain "No memory found for query: ..." — json.loads raises.
    payload = json.loads(result)
    assert {"ok", "data", "error"} <= set(payload)


@pytest.mark.xfail(
    strict=True,
    reason="audit:C1 — memory_stats returns str(dict) instead of {ok,data,error} envelope",
)
async def test_memory_stats_returns_envelope(mock_app_context):
    """memory_stats must return a JSON envelope, not str(some_dict)."""
    mock_app_context.memory_service.get_stats.return_value = Success(
        {"total": 3, "tags": {"food": 2}, "emotions": {"joy": 2}}
    )
    result = await _tools_memory._tool_memory_stats(mock_app_context, "p")
    # Production returns str(dict) — single-quoted repr, json.loads raises.
    payload = json.loads(result)
    assert "ok" in payload and "data" in payload and "error" in payload


@pytest.mark.xfail(
    strict=True,
    reason='audit:C1 — success classifier is a startswith("Error") string heuristic',
)
def test_success_classification_is_structural():
    """A plain-text failure message that does not start with 'Error'/'No memory'
    must be classified as failure (structural signal, not prefix matching)."""
    assert _tool_called_result_success("Validation failed: input id=7 is malformed") is False
    assert _tool_called_result_success("Something went wrong inside the tool") is False
