"""Red-first parity tests — audit H3: HTTP create_memory side effects.

The MCP path publishes ``memory.created`` (which invalidates the query cache
via AppContext's event-bus subscription) and upserts the vector store. The
HTTP path (``nous/api/http/routers/memory.py``) performs a bare
``memory_service.create_memory`` + manual vector upsert with no event
publication, so cached search results stay stale for up to the 30s TTL.

This test drives the REAL route closure (captured from
``register_memory_routes``) with a mocked context, and asserts the desired
MCP-parity behaviour. xfail(strict=True) at current HEAD (audit:H3).
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, patch

import pytest

from nous.api.http.routers import memory as memory_router
from nous.domain.shared.result import Success

from tests.parity.conftest import make_memory

if TYPE_CHECKING:
    from collections.abc import Callable


class _FakeMCP:
    """Minimal stand-in for MCPServer: captures custom_route handlers."""

    def __init__(self) -> None:
        self.routes: dict[tuple[str, str], Callable] = {}  # noqa: F821

    def custom_route(self, path: str, methods: list[str]):
        def decorator(fn):
            for method in methods:
                self.routes[(path, method)] = fn
            return fn

        return decorator


class _EmptyQueryParams:
    def __str__(self) -> str:
        return ""

    def get(self, key: str, default: object = None) -> object:
        return default


class _FakeRequest:
    """Minimal request shaped like a Starlette Request for the memory router."""

    def __init__(self, body: dict) -> None:
        self.path_params = {"persona": "parity_p"}
        self.query_params = _EmptyQueryParams()
        self.headers: dict[str, str] = {}
        self._body = body

    async def json(self) -> dict:
        return self._body


@pytest.mark.xfail(
    strict=True,
    reason="audit:H3 — HTTP create_memory does not publish memory.created / invalidate query cache",
)
async def test_http_create_memory_side_effects(mock_app_context, monkeypatch):
    mcp = _FakeMCP()
    memory_router.register_memory_routes(mcp)
    handler = mcp.routes[("/api/memories/{persona}", "POST")]
    assert handler is not None

    ctx = mock_app_context
    ctx.memory_service.create_memory = AsyncMock(
        return_value=Success(make_memory("mem_h3", content="hello side effects"))
    )
    ctx.vector_store = None
    ctx.event_bus = AsyncMock()
    monkeypatch.setattr(memory_router, "_safe_get_context", lambda persona: ctx)

    with patch("nous.domain.search.engine.invalidate_query_cache") as invalidate:
        resp = await handler(_FakeRequest({"content": "hello side effects", "importance": 0.5}))

    assert resp.status_code == 201
    # Contract (MCP parity): HTTP create publishes memory.created exactly once,
    # which is the event that drives query-cache invalidation in AppContext.
    published = [call.args[0] for call in ctx.event_bus.publish.await_args_list]
    assert published.count("memory.created") == 1
    # Explicit invalidation-side contract: the query cache must be dropped.
    invalidate.assert_called_once()


async def test_http_create_memory_response_schema(mock_app_context, monkeypatch):
    """Regression guard (NOT red): HTTP create already returns a JSON body.
    Kept so the P3 side-effect fix cannot silently change the response shape."""
    # Guard against a regression where the handler stops returning JSON entirely.
    mcp = _FakeMCP()
    memory_router.register_memory_routes(mcp)
    handler = mcp.routes[("/api/memories/{persona}", "POST")]

    ctx = mock_app_context
    ctx.memory_service.create_memory = AsyncMock(
        return_value=Success(make_memory("mem_h3b", content="x"))
    )
    ctx.vector_store = None
    monkeypatch.setattr(memory_router, "_safe_get_context", lambda persona: ctx)

    resp = await handler(_FakeRequest({"content": "x", "importance": 0.5}))
    assert resp.status_code == 201
    body = json.loads(resp.body)
    assert body["status"] == "ok"
    assert "cache_invalidated" in body or body.get("memory", {}).get("key") == "mem_h3b"
