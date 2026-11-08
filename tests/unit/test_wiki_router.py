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


# ---------------------------------------------------------------------------
# GET /api/wiki/{persona}  と /api/wiki/{persona}/{slug:path}（ダッシュボード閲覧）
# ---------------------------------------------------------------------------


@pytest.fixture
def read_routes(tmp_path):
    mcp = _FakeMcp()
    register_wiki_routes(mcp)
    ctx = _ctx()
    ctx.settings.data_root = str(tmp_path)
    return mcp, ctx


def _write_page(tmp_path, persona="herta", slug="project-nous", title="Nous", body="本文", sources=("m1",)):
    from nous.infrastructure.wiki.store import WikiStore

    store = WikiStore(tmp_path, persona)
    result = store.write_page(slug=slug, title=title, body=body, project="nous", sources=sources)
    assert result.is_ok, result
    return store


def _get_request(persona="herta", slug=None):
    req = MagicMock()
    req.path_params = {"persona": persona} if slug is None else {"persona": persona, "slug": slug}
    req.headers = {}
    return req


class TestWikiReadApi:
    @pytest.mark.asyncio
    async def test_list_unknown_persona_404(self, read_routes):
        mcp, _ = read_routes
        with patch("nous.api.http.routers.wiki._safe_get_context", return_value=None):
            resp = await mcp.routes["/api/wiki/{persona}"](_get_request())
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_list_empty(self, read_routes):
        mcp, ctx = read_routes
        with patch("nous.api.http.routers.wiki._safe_get_context", return_value=ctx):
            resp = await mcp.routes["/api/wiki/{persona}"](_get_request())
        assert resp.status_code == 200
        import json

        payload = json.loads(bytes(resp.body))
        assert payload == {"persona": "herta", "pages": []}

    @pytest.mark.asyncio
    async def test_list_returns_page_meta(self, read_routes):
        mcp, ctx = read_routes
        _write_page(tmp_path=ctx.settings.data_root)
        with patch("nous.api.http.routers.wiki._safe_get_context", return_value=ctx):
            resp = await mcp.routes["/api/wiki/{persona}"](_get_request())
        import json

        page = json.loads(bytes(resp.body))["pages"][0]
        assert page["slug"] == "project-nous"
        assert page["title"] == "Nous"
        assert page["sources"] == ["m1"]
        assert "updated" in page

    @pytest.mark.asyncio
    async def test_page_returns_body(self, read_routes):
        mcp, ctx = read_routes
        _write_page(tmp_path=ctx.settings.data_root)
        with patch("nous.api.http.routers.wiki._safe_get_context", return_value=ctx):
            resp = await mcp.routes["/api/wiki/{persona}/{slug:path}"](_get_request(slug="project-nous"))
        assert resp.status_code == 200
        import json

        payload = json.loads(bytes(resp.body))
        assert payload["slug"] == "project-nous"
        assert "本文" in payload["body"]

    @pytest.mark.asyncio
    async def test_page_missing_404(self, read_routes):
        mcp, ctx = read_routes
        with patch("nous.api.http.routers.wiki._safe_get_context", return_value=ctx):
            resp = await mcp.routes["/api/wiki/{persona}/{slug:path}"](_get_request(slug="nope"))
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_page_traversal_404(self, read_routes):
        mcp, ctx = read_routes
        with patch("nous.api.http.routers.wiki._safe_get_context", return_value=ctx):
            resp = await mcp.routes["/api/wiki/{persona}/{slug:path}"](_get_request(slug="../secrets"))
        assert resp.status_code == 404


def test_dashboard_renders_wiki_tab():
    """SPA に Wiki タブ・パネル・JS が配線されている（回帰ガード）。"""
    from nous.api.http.dashboard import render_dashboard

    html = render_dashboard("herta")
    assert 'data-tab="wiki"' in html
    assert 'id="tab-wiki"' in html
    assert "/static/features/wiki.js" in html
