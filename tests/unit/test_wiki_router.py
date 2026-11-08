"""wiki 手動トリガ API（POST /api/wiki/run/{persona}）の認証・状態判定の検証。"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from nous.api.http.routers.wiki import register_wiki_routes


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
    register_wiki_routes(mcp)
    return mcp.routes["/api/wiki/run/{persona}"]


def _ctx(plugin_enabled=True, api_key="k", wiki_enabled=True):
    ctx = MagicMock()
    ctx.settings.plugin.enabled = plugin_enabled
    ctx.settings.plugin.api_key = api_key
    ctx.settings.wiki.enabled = wiki_enabled
    return ctx


def _request(persona="herta", auth="Bearer k"):
    req = MagicMock()
    req.path_params = {"persona": persona}
    req.headers = {"authorization": auth} if auth else {}
    return req


class TestWikiRunAuth:
    @pytest.mark.asyncio
    async def test_missing_context_404(self, route):
        with patch("nous.api.http.routers.wiki._safe_get_context", return_value=None):
            resp = await route(_request())
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_plugin_disabled_403(self, route):
        with patch("nous.api.http.routers.wiki._safe_get_context", return_value=_ctx(plugin_enabled=False)):
            resp = await route(_request())
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_missing_key_401(self, route):
        with patch("nous.api.http.routers.wiki._safe_get_context", return_value=_ctx()):
            resp = await route(_request(auth=""))
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_wrong_key_401(self, route):
        with patch("nous.api.http.routers.wiki._safe_get_context", return_value=_ctx()):
            resp = await route(_request(auth="Bearer wrong"))
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_wiki_disabled_409(self, route):
        with patch("nous.api.http.routers.wiki._safe_get_context", return_value=_ctx(wiki_enabled=False)):
            resp = await route(_request())
        assert resp.status_code == 409

    @pytest.mark.asyncio
    async def test_accepted_202_and_thread_started(self, route):
        ctx = _ctx()
        thread = MagicMock()
        with (
            patch("nous.api.http.routers.wiki._safe_get_context", return_value=ctx),
            patch("nous.api.http.routers.wiki.threading.Thread", return_value=thread) as thr,
        ):
            resp = await route(_request())
        assert resp.status_code == 202
        assert thr.call_args.kwargs["daemon"] is True
        thread.start.assert_called_once()
