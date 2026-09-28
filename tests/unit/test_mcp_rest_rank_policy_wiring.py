"""RankPolicy 配線テスト（oracle BLOCK F2/F3 対応）。

MCP memory_search と REST /api/search/{persona} の SearchQuery 構築が
rank_policy を渡すことを検証する。重みマップ:
  tool 引数 vector_weight  → RankPolicy.relevance_weight
  tool 引数 keyword_weight → RankPolicy.lexical_weight
  tool 引数 importance_weight / recency_weight → そのまま同名へ
配線されないと keyword/fts 由来の語一致が MCP 実利用経路で効かない
（/tmp/oracle_lexical_review.log F2/F3）。
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock

import pytest

from nous.domain.shared.result import Success

if TYPE_CHECKING:
    from nous.domain.search.engine import SearchQuery


class _CapSearchEngine:
    """SearchQuery を capture する search_engine スタブ（set_persona / log_search 付き）。"""

    def __init__(self) -> None:
        self.engine = MagicMock()
        self.engine._semantic = None
        self.last_query: SearchQuery | None = None

    def set_persona(self, persona: str) -> None:  # noqa: ARG002
        pass

    async def search(self, query: SearchQuery):
        self.last_query = query
        return Success([])

    def log_search(self, *_a, **_kw) -> None:
        pass


# ---------------------------------------------------------------------------
# MCP memory_search
# ---------------------------------------------------------------------------


class TestMCPRankPolicyWiring:
    @pytest.mark.asyncio
    async def test_memory_search_passes_rank_policy(self):
        from nous.api.mcp._tools_memory import _tool_memory_search

        cap = _CapSearchEngine()
        ctx = MagicMock()
        ctx.search_engine = cap
        ctx.event_bus.publish = AsyncMock()
        ctx.memory_service = MagicMock()
        await _tool_memory_search(ctx, "herta", query="機能確認テスト")
        q = cap.last_query
        assert q is not None
        assert q.rank_policy is not None
        # RRF 段への既定重みは従来どおり
        assert q.vector_weight == 1.0
        assert q.keyword_weight == 1.0

    @pytest.mark.asyncio
    async def test_tool_weights_map_to_policy(self):
        from nous.api.mcp._tools_memory import _tool_memory_search

        cap = _CapSearchEngine()
        ctx = MagicMock()
        ctx.search_engine = cap
        ctx.event_bus.publish = AsyncMock()
        await _tool_memory_search(
            ctx,
            "herta",
            query="q",
            importance_weight=0.7,
            recency_weight=0.2,
            vector_weight=0.5,
            keyword_weight=0.3,
        )
        policy = getattr(cap.last_query, "rank_policy", None)
        assert policy is not None
        p = policy
        assert p.importance_weight == pytest.approx(0.7)
        assert p.recency_weight == pytest.approx(0.2)
        assert p.relevance_weight == pytest.approx(0.5)
        assert p.lexical_weight == pytest.approx(0.3)

    @pytest.mark.asyncio
    async def test_profile_recent_semantics_preserved(self):
        """profile='recent' の重みプリセットが policy 重みへ写像される。"""
        from nous.api.mcp._tools_memory import _tool_memory_search

        cap = _CapSearchEngine()
        ctx = MagicMock()
        ctx.search_engine = cap
        ctx.event_bus.publish = AsyncMock()
        await _tool_memory_search(ctx, "herta", query="q", profile="recent")
        policy = getattr(cap.last_query, "rank_policy", None)
        assert policy is not None
        p = policy
        assert p.importance_weight == pytest.approx(0.0)
        assert p.recency_weight == pytest.approx(0.4)
        assert p.relevance_weight == pytest.approx(0.8)

    @pytest.mark.asyncio
    async def test_search_query_equality_untouched(self):
        """tool 引数・envelope 形式は不変（順位のみ変わる）。"""
        from nous.api.mcp._tools_memory import _tool_memory_search

        cap = _CapSearchEngine()
        ctx = MagicMock()
        ctx.search_engine = cap
        ctx.event_bus.publish = AsyncMock()
        ctx.memory_service = MagicMock()
        out = await _tool_memory_search(ctx, "herta", query="q", top_k=3)
        assert isinstance(out, str)
        payload = json.loads(out)
        assert payload["ok"] is True


class TestUnifiedWeights:
    """重み統一: MCP 既定と REST 経路が同一の RankPolicy を渡す（oracle #011）。"""

    @pytest.mark.asyncio
    async def test_mcp_default_and_rest_use_identical_policy(self):
        """両経路が同一インスタンス等価の重み（lexical 1.0 / relevance 1.0）を渡す。"""
        from nous.api.http.routers.search import register_search_routes
        from nous.api.mcp._tools_memory import _tool_memory_search

        cap = _CapSearchEngine()
        ctx = MagicMock()
        ctx.search_engine = cap
        ctx.event_bus.publish = AsyncMock()
        ctx.memory_service = MagicMock()
        await _tool_memory_search(ctx, "herta", query="機能確認テスト")
        mcp_policy = cap.last_query.rank_policy
        assert mcp_policy is not None
        # MCP 既定（profile 無指定）: importance 0 / recency 0.05 / relevance(vector) 1.0 / lexical(keyword) 1.0
        assert mcp_policy.importance_weight == pytest.approx(0.0)
        assert mcp_policy.recency_weight == pytest.approx(0.05)
        assert mcp_policy.relevance_weight == pytest.approx(1.0)
        assert mcp_policy.lexical_weight == pytest.approx(1.0)

        # REST 経路のキャプチャ（既存 test と同じ最小モック）
        rest_captured: dict[str, SearchQuery] = {}

        class _CapEngine:
            def set_persona(self, _p: str) -> None:
                pass

            async def search(self, q):
                rest_captured["q"] = q
                return Success([])

        class _Ctx:
            search_engine = _CapEngine()

        rest_ctx = _Ctx()
        request = MagicMock()
        request.query_params = {"q": "機能確認テスト", "limit": "5"}
        request.state.persona = "herta"
        import nous.api.http.routers.search as mod

        orig_resolve = mod._resolve_persona_from_request
        orig_get_ctx = mod._safe_get_context
        mod._resolve_persona_from_request = lambda _request: "herta"
        mod._safe_get_context = lambda _persona: rest_ctx
        try:
            engines = {}

            def fake_route(path, methods=None):  # noqa: ARG001
                def deco(fn):
                    engines[path] = fn
                    return fn

                return deco

            fake_mcp = MagicMock()
            fake_mcp.custom_route = fake_route
            register_search_routes(fake_mcp)
            handler = engines["/api/search/{persona}"]
            resp = await handler(request)
            assert resp.status_code == 200
        finally:
            mod._resolve_persona_from_request = orig_resolve
            mod._safe_get_context = orig_get_ctx
        rest_policy = rest_captured["q"].rank_policy
        assert rest_policy is not None
        # 両経路の重みが完全一致する（frozen dataclass の等価性）。
        assert rest_policy == mcp_policy

    @pytest.mark.asyncio
    async def test_rest_default_weights_are_mcp_defaults(self):
        """REST が MCP 既定（lexical 1.0）を渡すことの直接 assert。"""
        from nous.api.http.routers.search import register_search_routes

        rest_captured: dict[str, SearchQuery] = {}

        class _CapEngine:
            def set_persona(self, _p: str) -> None:
                pass

            async def search(self, q):
                rest_captured["q"] = q
                return Success([])

        class _Ctx:
            search_engine = _CapEngine()

        rest_ctx = _Ctx()
        request = MagicMock()
        request.query_params = {"q": "テスト", "limit": "5"}
        request.state.persona = "herta"
        import nous.api.http.routers.search as mod

        orig_resolve = mod._resolve_persona_from_request
        orig_get_ctx = mod._safe_get_context
        mod._resolve_persona_from_request = lambda _request: "herta"
        mod._safe_get_context = lambda _persona: rest_ctx
        try:
            engines = {}

            def fake_route(path, methods=None):  # noqa: ARG001
                def deco(fn):
                    engines[path] = fn
                    return fn

                return deco

            fake_mcp = MagicMock()
            fake_mcp.custom_route = fake_route
            register_search_routes(fake_mcp)
            handler = engines["/api/search/{persona}"]
            resp = await handler(request)
            assert resp.status_code == 200
        finally:
            mod._resolve_persona_from_request = orig_resolve
            mod._safe_get_context = orig_get_ctx
        p = rest_captured["q"].rank_policy
        assert p is not None
        assert p.importance_weight == pytest.approx(0.0)
        assert p.recency_weight == pytest.approx(0.05)
        assert p.relevance_weight == pytest.approx(1.0)
        assert p.lexical_weight == pytest.approx(1.0)
        assert p.graph_boost_weight == pytest.approx(0.1)


# ---------------------------------------------------------------------------
# REST /api/search/{persona}（配線のみ・前タスクからの存置）
# ---------------------------------------------------------------------------


class TestRESTSearchRankPolicyWiring:
    @pytest.mark.asyncio
    async def test_rest_search_passes_rank_policy(self):
        """REST 経路の SearchQuery にも rank_policy が載る。"""
        from nous.api.http.routers.search import register_search_routes

        captured: dict[str, SearchQuery] = {}

        class _CapEngine:
            def set_persona(self, _p: str) -> None:
                pass

            async def search(self, q):
                captured["q"] = q
                return Success([])

        class _Ctx:
            search_engine = _CapEngine()

        ctx = _Ctx()

        # starlette Request を最小構成でモック
        request = MagicMock()
        request.query_params = {"q": "テスト", "limit": "5"}
        request.state.persona = "herta"
        # _safe_get_context / _resolve_persona_from_request は monkeypatch
        import nous.api.http.routers.search as mod

        orig_resolve = mod._resolve_persona_from_request
        orig_get_ctx = mod._safe_get_context

        def _fake_resolve(_request: object) -> str:
            return "herta"

        def _fake_get_ctx(_persona: str) -> object:
            return ctx

        mod._resolve_persona_from_request = _fake_resolve
        mod._safe_get_context = _fake_get_ctx
        try:
            # custom_route デコレータから関数を取り出す
            engines = {}

            def fake_route(path, methods=None):  # noqa: ARG001
                def deco(fn):
                    engines[path] = fn
                    return fn

                return deco

            fake_mcp = MagicMock()
            fake_mcp.custom_route = fake_route
            register_search_routes(fake_mcp)
            handler = engines["/api/search/{persona}"]
            resp = await handler(request)
            assert resp.status_code == 200
        finally:
            mod._resolve_persona_from_request = orig_resolve
            mod._safe_get_context = orig_get_ctx
        q = captured["q"]
        assert q.rank_policy is not None
