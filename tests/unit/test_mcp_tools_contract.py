"""Task 4 (Q4): all MCP memory tools return str (JSON-encoded), never dict."""

from __future__ import annotations

import json

import pytest

from nous.api.mcp import _tools_memory as m
from nous.domain.shared.result import Failure


def _as_json_str(result) -> dict:
    assert isinstance(result, str), f"expected str, got {type(result)}: {result!r:.120}"
    return json.loads(result)


@pytest.mark.asyncio
async def test_create_error_paths_return_str(mock_app_context):
    r = await m._tool_memory_create(mock_app_context, "p")
    d = _as_json_str(r)
    assert d["success"] is False

    r = await m._tool_memory_create(mock_app_context, "p", content="x", importance=9.9)
    d = _as_json_str(r)
    assert d["success"] is False


@pytest.mark.asyncio
async def test_update_search_read_error_paths_return_str(mock_app_context):
    r = await m._tool_memory_update(mock_app_context, "p", query="nope")
    mock_app_context.search_engine.search.return_value = Failure("nf")
    r = await m._tool_memory_update(mock_app_context, "p", query="q")
    _as_json_str(r)

    r = await m._tool_memory_update(mock_app_context, "p", memory_key="k", content="x" * 50001)
    _as_json_str(r)

    mock_app_context.search_engine.search.return_value = Failure("boom")
    r = await m._tool_memory_search(mock_app_context, "p", query="q")
    _as_json_str(r)

    mock_app_context.memory_service.get_recent.return_value = Failure("boom")
    r = await m._tool_memory_read(mock_app_context, "p")
    _as_json_str(r)

    r = await m._tool_memory_search(mock_app_context, "p", query="q", top_k=999)
    _as_json_str(r)


def test_ok_err_wrappers():
    assert isinstance(m._ok({"ok": True}), str)
    assert json.loads(m._ok({"ok": True}))["ok"] is True
    d = json.loads(m._err("oops"))
    assert d["success"] is False and d["data"] is None
