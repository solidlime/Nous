"""#89: ルーター入力ガードの回帰テスト。

- GET /api/graph/{persona}?limit=abc / limit=0 → 400（int() の素の ValueError を 500 にしない）
- POST /api/memories/{persona} の body が list → 422（CreateMemoryRequest(**list) は TypeError）
- POST /api/chat/{persona}/tool の body が不正 JSON → 400
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any, cast

import nous.api.http.routers.chat.chat_management as chat_management
import nous.api.http.routers.memory.memory as memory_router
import nous.api.http.routers.memory.search as search_router
from nous.api.http.routers.chat.chat_management import execute_chat_tool


class _FakeMCP:
    def __init__(self) -> None:
        # 同じパスに複数メソッドが登録されるのでキーにメソッドも含める
        self.handlers: dict[tuple[str, tuple[str, ...]], Any] = {}

    def custom_route(self, path: str, methods: list[str]):
        def deco(fn):
            self.handlers[(path, tuple(methods))] = fn
            return fn

        return deco


class _FakeRequest:
    def __init__(
        self,
        persona: str = "p",
        query: dict | None = None,
        json_body=None,
        json_error: Exception | None = None,
        key: str = "k",
    ):
        self.path_params = {"persona": persona, "key": key}
        self.query_params = query or {}
        self.headers: dict[str, str] = {}
        self._json_body = json_body
        self._json_error = json_error

    async def json(self):
        if self._json_error is not None:
            raise self._json_error
        return self._json_body


def _graph_handler():
    mcp = _FakeMCP()
    search_router.register_search_routes(mcp)
    return mcp.handlers[("/api/graph/{persona}", ("GET",))]


async def test_graph_limit_non_integer_returns_400():
    resp = await _graph_handler()(_FakeRequest(query={"limit": "abc"}))
    assert resp.status_code == 400
    assert b"limit must be an integer" in resp.body


async def test_graph_limit_zero_returns_400():
    resp = await _graph_handler()(_FakeRequest(query={"limit": "0"}))
    assert resp.status_code == 400


async def test_create_memory_list_body_returns_422(monkeypatch):
    mcp = _FakeMCP()
    memory_router.register_memory_routes(mcp)
    handler = mcp.handlers[("/api/memories/{persona}", ("POST",))]
    monkeypatch.setattr(
        memory_router,
        "_safe_get_context",
        lambda p: SimpleNamespace(memory_service=SimpleNamespace()),
    )
    # body が JSON の list でも 500 にせず 422（#89: TypeError を捕まえる）
    resp = await handler(_FakeRequest(json_body=[{"content": "x"}]))
    assert resp.status_code == 422


async def test_execute_chat_tool_invalid_json_returns_400(monkeypatch):
    monkeypatch.setattr(
        chat_management,
        "_resolve_request",
        lambda request: ("p", SimpleNamespace()),
    )
    resp = await execute_chat_tool(cast("Any", _FakeRequest(json_error=json.JSONDecodeError("Expecting value", "", 0))))
    assert resp.status_code == 400


async def test_execute_chat_tool_non_object_json_returns_400(monkeypatch):
    """JSON として妥当でも object でなければ body.get が落ちる → 400（#89 review #1）。"""
    monkeypatch.setattr(
        chat_management,
        "_resolve_request",
        lambda request: ("p", SimpleNamespace()),
    )
    resp = await execute_chat_tool(cast("Any", _FakeRequest(json_body=[])))
    assert resp.status_code == 400


async def test_update_memory_list_body_returns_422(monkeypatch):
    """PUT も list body を 500 にせず 422（#89 review #2）。"""
    mcp = _FakeMCP()
    memory_router.register_memory_routes(mcp)
    handler = mcp.handlers[("/api/memories/{persona}/{key}", ("PUT",))]
    monkeypatch.setattr(
        memory_router,
        "_safe_get_context",
        lambda p: SimpleNamespace(memory_service=SimpleNamespace()),
    )
    resp = await handler(_FakeRequest(json_body=[{"content": "x"}]))
    assert resp.status_code == 422
