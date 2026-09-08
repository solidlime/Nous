"""Events router SSE: CancelledError は re-raise されること（外側 wait_for が
StopAsyncIteration に化けない。chat_event_stream と同一の挙動）。"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nous.api.http.routers.events import register_events_routes


class _FakeMcp:
    def __init__(self) -> None:
        self.routes: dict = {}

    def custom_route(self, path, methods=None):
        def deco(fn):
            self.routes[path] = fn
            return fn

        return deco


@pytest.fixture
def route():
    mcp = _FakeMcp()
    register_events_routes(mcp)
    return mcp.routes["/api/events/{persona}"]


def _ctx():
    ctx = MagicMock()
    ctx.event_bus.subscribe = MagicMock()
    ctx.event_bus.unsubscribe = MagicMock()
    return ctx


def _request(ctx):
    req = MagicMock()
    req.is_disconnected = AsyncMock(return_value=False)
    req.query_params = {"topics": ""}
    return req


def _patched(ctx, req):
    return (
        patch("nous.api.http.routers.events._resolve_persona_from_request", return_value="test"),
        patch("nous.api.http.routers.events._safe_get_context", return_value=ctx),
        req,
    )


class TestSseCancellationPropagation:
    @pytest.mark.asyncio
    async def test_cancelled_error_propagates_not_stopasynciteration(self, route):
        """wait_for のキャンセルで TimeoutError が外へ出る（StopAsyncIteration に化けない）。

        旧実装は except CancelledError: pass で飲み込み、generator が正常終了
        （StopAsyncIteration）して外側の wait_for の意味論が壊れていた。
        """
        ctx = _ctx()
        p1, p2, req = _patched(ctx, _request(ctx))
        with p1, p2:
            resp = await route(req)
        gen = resp.body_iterator
        first = await asyncio.wait_for(gen.__anext__(), timeout=2.0)
        assert "event: connected" in first

        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(gen.__anext__(), timeout=0.2)
        # CancelledError は finally の unsubscribe を通って外へ伝播している
        assert ctx.event_bus.unsubscribe.called

    @pytest.mark.asyncio
    async def test_disconnect_breaks_loop_and_unsubscribes(self, route):
        ctx = _ctx()
        req = MagicMock()
        # 1回目: connected を yield（ループ前）。2回目: ループ先頭の is_disconnected → True → break
        req.is_disconnected = AsyncMock(return_value=True)
        req.query_params = {"topics": ""}
        p1, p2, req2 = _patched(ctx, req)
        with p1, p2:
            resp = await route(req2)
        gen = resp.body_iterator
        await asyncio.wait_for(gen.__anext__(), timeout=2.0)  # connected
        # is_disconnected=True → break → generator 正常終了
        with pytest.raises(StopAsyncIteration):
            await asyncio.wait_for(gen.__anext__(), timeout=2.0)
        assert ctx.event_bus.unsubscribe.called
