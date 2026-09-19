"""MCP memory tool contract: all tools return a str; payloads follow the
common ``{ok, data, error}`` envelope (audit C1 / v4.0 P2).

Envelope assertions live in tests/parity/test_parity_envelope.py; this file
keeps the str-typed + error-path coverage for memory tools.
"""

from __future__ import annotations

import json

import pytest

from nous.api.mcp import _tools_memory as m
from nous.domain.shared.result import Failure


def _as_json_str(result) -> dict:
    assert isinstance(result, str), f"expected str, got {type(result)}: {result!r:.120}"
    return json.loads(result)


def _is_error_envelope(d: dict) -> bool:
    assert {"ok", "data", "error"} <= set(d), f"not an envelope: {d!r:.200}"
    assert d["ok"] is False
    assert d["error"]["code"]
    return True


@pytest.mark.asyncio
async def test_create_error_paths_return_error_envelope(mock_app_context):
    r = await m._tool_memory_create(mock_app_context, "p")
    assert _is_error_envelope(_as_json_str(r))

    r = await m._tool_memory_create(mock_app_context, "p", content="x", importance=9.9)
    assert _is_error_envelope(_as_json_str(r))


@pytest.mark.asyncio
async def test_update_search_read_error_paths_return_envelope(mock_app_context):
    r = await m._tool_memory_update(mock_app_context, "p", query="nope")
    mock_app_context.search_engine.search.return_value = Failure("nf")
    r = await m._tool_memory_update(mock_app_context, "p", query="q")
    assert _is_error_envelope(_as_json_str(r))

    r = await m._tool_memory_update(mock_app_context, "p", memory_key="k", content="x" * 50001)
    assert _is_error_envelope(_as_json_str(r))

    mock_app_context.search_engine.search.return_value = Failure("boom")
    r = await m._tool_memory_search(mock_app_context, "p", query="q")
    assert _is_error_envelope(_as_json_str(r))

    mock_app_context.memory_service.get_recent.return_value = Failure("boom")
    r = await m._tool_memory_read(mock_app_context, "p")
    assert _is_error_envelope(_as_json_str(r))

    r = await m._tool_memory_search(mock_app_context, "p", query="q", top_k=999)
    assert _is_error_envelope(_as_json_str(r))


def test_ok_err_wrappers():
    assert isinstance(m._ok({"ok": True}), str)
    d = json.loads(m._ok({"ok": True}))
    assert d["ok"] is True and d["data"] == {"ok": True} and d["error"] is None
    d = json.loads(m._err("oops"))
    assert _is_error_envelope(d)
