"""wiki 手動トリガ API（POST /api/wiki/run/{persona}）の認証・状態判定の検証。"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from nous.api.http.routers.wiki import register_wiki_routes


class _FakeMcp:
    """path × method で handler を記録する（同一 path に GET と PUT が同居するため）。"""

    def __init__(self) -> None:
        self.routes: dict[tuple[str, str], object] = {}

    def custom_route(self, path, methods=None):
        methods = [m.upper() for m in (methods or ["GET"])]

        def deco(fn):
            for method in methods:
                self.routes[(path, method)] = fn
            return fn

        return deco

    def route(self, path, method="GET"):
        return self.routes[(path, method)]


@pytest.fixture
def route():
    mcp = _FakeMcp()
    register_wiki_routes(mcp)
    return mcp.route("/api/wiki/run/{persona}", "POST")


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


def _write_page(tmp_path, persona="herta", slug="project-nous", title="Nous", body="本文", sources=("m1",), tags=()):
    from nous.infrastructure.wiki.store import WikiStore

    store = WikiStore(tmp_path, persona)
    result = store.write_page(slug=slug, title=title, body=body, project="nous", sources=sources, tags=tags)
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
            resp = await mcp.route("/api/wiki/{persona}", "GET")(_get_request())
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_list_empty(self, read_routes):
        mcp, ctx = read_routes
        with patch("nous.api.http.routers.wiki._safe_get_context", return_value=ctx):
            resp = await mcp.route("/api/wiki/{persona}", "GET")(_get_request())
        assert resp.status_code == 200
        import json

        payload = json.loads(bytes(resp.body))
        assert payload == {"persona": "herta", "pages": []}

    @pytest.mark.asyncio
    async def test_list_returns_page_meta(self, read_routes):
        mcp, ctx = read_routes
        _write_page(tmp_path=ctx.settings.data_root)
        with patch("nous.api.http.routers.wiki._safe_get_context", return_value=ctx):
            resp = await mcp.route("/api/wiki/{persona}", "GET")(_get_request())
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
            resp = await mcp.route("/api/wiki/{persona}/{slug:path}", "GET")(_get_request(slug="project-nous"))
        assert resp.status_code == 200
        import json

        payload = json.loads(bytes(resp.body))
        assert payload["slug"] == "project-nous"
        assert "本文" in payload["body"]

    @pytest.mark.asyncio
    async def test_page_missing_404(self, read_routes):
        mcp, ctx = read_routes
        with patch("nous.api.http.routers.wiki._safe_get_context", return_value=ctx):
            resp = await mcp.route("/api/wiki/{persona}/{slug:path}", "GET")(_get_request(slug="nope"))
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_page_traversal_404(self, read_routes):
        mcp, ctx = read_routes
        with patch("nous.api.http.routers.wiki._safe_get_context", return_value=ctx):
            resp = await mcp.route("/api/wiki/{persona}/{slug:path}", "GET")(_get_request(slug="../secrets"))
        assert resp.status_code == 404


def test_dashboard_renders_wiki_tab():
    """SPA に Wiki タブ・パネル・JS が配線されている（回帰ガード）。"""
    from nous.api.http.dashboard import render_dashboard

    html = render_dashboard("herta")
    assert 'data-tab="wiki"' in html
    assert 'id="tab-wiki"' in html
    assert "/static/features/wiki.js" in html


# ---------------------------------------------------------------------------
# PUT /api/wiki/{persona}/{slug:path} — ダッシュボードからの手書き保存
# ---------------------------------------------------------------------------


def _put_request(persona="herta", slug="project-nous", payload=None):
    req = MagicMock()
    req.path_params = {"persona": persona, "slug": slug}
    req.headers = {}
    req.method = "PUT"

    async def _json():
        return payload if payload is not None else {}

    req.json = _json
    return req


class TestWikiSaveApi:
    @pytest.mark.asyncio
    async def test_missing_persona_404(self, read_routes):
        mcp, _ = read_routes
        with patch("nous.api.http.routers.wiki._safe_get_context", return_value=None):
            resp = await mcp.route("/api/wiki/{persona}/{slug:path}", "PUT")(_put_request())
        assert resp.status_code in (404, 405)

    @pytest.mark.asyncio
    async def test_body_required_400(self, read_routes):
        mcp, ctx = read_routes
        with patch("nous.api.http.routers.wiki._safe_get_context", return_value=ctx):
            resp = await mcp.route("/api/wiki/{persona}/{slug:path}", "PUT")(_put_request(payload={"title": "x"}))
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_saves_page_and_schedules_vector_sync(self, read_routes):
        import asyncio as _asyncio
        import json as _json

        mcp, ctx = read_routes
        _write_page(tmp_path=ctx.settings.data_root, sources=("m1", "m2"))
        calls = []

        async def _fake_sync(settings, persona, slug, title, body):
            calls.append((persona, slug, title, body))

        with (
            patch("nous.api.http.routers.wiki._safe_get_context", return_value=ctx),
            patch("nous.api.http.routers.wiki.async_sync_page", _fake_sync),
        ):
            resp = await mcp.route("/api/wiki/{persona}/{slug:path}", "PUT")(
                _put_request(payload={"title": "直した題名", "body": "誤字を直した本文"})
            )
            assert resp.status_code == 200
            await _asyncio.sleep(0)  # create_task を 1 周回す

        page = _json.loads(bytes(resp.body))
        assert "manual" not in page
        assert page["title"] == "直した題名"
        assert page["sources"] == ["m1", "m2"]

        from nous.infrastructure.wiki.store import WikiStore

        stored = WikiStore(ctx.settings.data_root, "herta").read_page("project-nous").value
        assert stored.body == "誤字を直した本文"
        raw = (
            WikiStore(ctx.settings.data_root, "herta")
            .wiki_dir()
            .joinpath("project-nous.md")
            .read_text(encoding="utf-8")
        )
        assert "manual" not in raw
        assert calls == [("herta", "project-nous", "直した題名", "誤字を直した本文")]

    async def test_put_preserves_tags(self, read_routes):
        """GUI 保存で tags が消えない（journal タグで一括参照できる前提を守る）。"""
        mcp, ctx = read_routes
        _write_page(tmp_path=ctx.settings.data_root, tags=("journal", "2026-11"))

        async def _fake_sync(*_a, **_k):
            return None

        with (
            patch("nous.api.http.routers.wiki._safe_get_context", return_value=ctx),
            patch("nous.api.http.routers.wiki.async_sync_page", _fake_sync),
        ):
            resp = await mcp.route("/api/wiki/{persona}/{slug:path}", "PUT")(
                _put_request(payload={"body": "編集した本文"})
            )
        assert resp.status_code == 200

        from nous.infrastructure.wiki.store import WikiStore

        stored = WikiStore(ctx.settings.data_root, "herta").read_page("project-nous").value
        assert stored.tags == ("journal", "2026-11")

    @pytest.mark.asyncio
    async def test_traversal_rejected(self, read_routes):
        mcp, ctx = read_routes
        with patch("nous.api.http.routers.wiki._safe_get_context", return_value=ctx):
            resp = await mcp.route("/api/wiki/{persona}/{slug:path}", "PUT")(
                _put_request(slug="../evil", payload={"body": "x"})
            )
        assert resp.status_code == 400
