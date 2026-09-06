"""Persona-scoped wiring feed tests.

- persona 付き emit → filter 一致のみ
- 未指定 → 全返（後方互換）
- meta 無し旧イベント → filter 下では除外、未指定では含む
- hook の persona 付与（repo 実測／取れない経路は None）
- SSE ?persona= 濾過
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from nous.domain.memory import wiring_events
from nous.domain.memory.memory_link import MemoryLink
from nous.domain.memory.query_service import MemoryQueryService
from nous.domain.search.spreading_activation import SpreadingActivation
from nous.infrastructure.sqlite.connection import SQLiteConnection
from nous.infrastructure.sqlite.entity_repo import SQLiteEntityRepository
from nous.infrastructure.sqlite.memory_repo import SQLiteMemoryRepository


@pytest.fixture(autouse=True)
def _clean_buffer():
    wiring_events.clear()
    yield
    wiring_events.clear()


class _FakeRequest:
    def __init__(self, query_params=None, disconnect_after: int = 99):
        from starlette.datastructures import QueryParams

        self.query_params: QueryParams = QueryParams(query_params or {})
        self.path_params: dict = {}
        self.headers: dict = {}
        self._calls = 0
        self._disconnect_after = disconnect_after

    async def is_disconnected(self) -> bool:
        self._calls += 1
        return self._calls > self._disconnect_after


class TestPersonaFilter:
    def test_filter_returns_only_match(self) -> None:
        wiring_events.emit("link_fire", source="a", meta={"persona": "p1"})
        wiring_events.emit("link_fire", source="b", meta={"persona": "p2"})
        got = wiring_events.snapshot_after(0, persona="p1")
        assert [e["source"] for e in got] == ["a"]

    def test_unspecified_returns_all(self) -> None:
        wiring_events.emit("link_fire", source="a", meta={"persona": "p1"})
        wiring_events.emit("link_fire", source="legacy")
        got = wiring_events.snapshot_after(0)
        assert [e["source"] for e in got] == ["a", "legacy"]

    def test_legacy_excluded_under_filter(self) -> None:
        wiring_events.emit("link_fire", source="legacy")
        wiring_events.emit("ppr_hit", source="s", meta={"persona": None})
        assert wiring_events.snapshot_after(0, persona="p1") == []

    def test_replay_fire_scoped(self) -> None:
        wiring_events.emit("replay_fire", source="s1", target="s2", weight=0.8, meta={"persona": "p1"})
        wiring_events.emit("replay_fire", source="s3", target="s4", weight=0.6, meta={"persona": "p2"})
        got = wiring_events.snapshot_after(0, persona="p1")
        assert [e["source"] for e in got] == ["s1"]
        assert got[0]["kind"] == "replay_fire" and got[0]["meta"]["persona"] == "p1"


class TestHookPersona:
    def test_upsert_link_persona(self, tmp_path) -> None:
        conn = SQLiteConnection(data_dir=str(tmp_path), persona="p1")
        conn.initialize_schema()
        try:
            SQLiteEntityRepository(conn).upsert_link("a", "b", "semantic", strength=0.1)
            fires = wiring_events.snapshot_after(0, persona="p1")
            assert len(fires) == 1 and fires[0]["kind"] == "link_fire"
        finally:
            conn.close()

    def test_boost_recall_persona(self, tmp_path) -> None:
        conn = SQLiteConnection(data_dir=str(tmp_path), persona="p2")
        conn.initialize_schema()
        try:
            from nous.domain.memory.entities import Memory
            from nous.domain.shared.time_utils import get_now

            now = get_now()
            repo = SQLiteMemoryRepository(conn)
            repo.save(Memory(key="k", content="test", created_at=now, updated_at=now))
            result = MemoryQueryService(repo).boost_recall("k")
            assert result.is_ok
            fires = wiring_events.snapshot_after(0, persona="p2")
            assert len(fires) == 1 and fires[0]["kind"] == "recall_boost"
        finally:
            conn.close()

    def test_boost_recall_mock_repo_none(self) -> None:
        repo = MagicMock()
        from nous.domain.memory.entities import MemoryStrength
        from nous.domain.shared.result import Success

        repo.get_strength.return_value = Success(MemoryStrength(memory_key="m"))
        repo.save_strength.side_effect = lambda s: Success(None)
        assert MemoryQueryService(repo).boost_recall("m").is_ok
        fires = [e for e in wiring_events.snapshot_after(0) if e["kind"] == "recall_boost"]
        assert len(fires) == 1
        assert fires[0]["meta"].get("persona") is None

    @pytest.mark.asyncio
    async def test_replay_fire_persona_attributed(self) -> None:
        from types import SimpleNamespace
        from unittest.mock import AsyncMock

        from nous.domain.memory.enrich_service import MemoryEnrichService

        repo = MagicMock()
        repo._conn.persona = "p2"
        rel = SimpleNamespace(source_entity="s1", target_entity="s2", relation_type="related", confidence=0.8)
        enricher = SimpleNamespace(
            enrich_async=AsyncMock(return_value=SimpleNamespace(importance=0.5, relations=[rel]))
        )
        svc = MemoryEnrichService(enricher, MagicMock(), repo)
        with patch("nous.domain.memory.sudachi_extractor.SudachiExtractor") as ner:
            ner.return_value.extract.return_value = []
            await svc.enrich_memory(MagicMock(importance=0.5), "内容", None, "k", 0.5)
        fires = wiring_events.snapshot_after(0, persona="p2")
        assert len(fires) == 1 and fires[0]["kind"] == "replay_fire"
        assert fires[0]["meta"]["persona"] == "p2" and fires[0]["meta"]["memory_key"] == "k"

    def test_propagate_persona_none(self) -> None:
        links = [MemoryLink(source_key="s", target_key="n", weight=1.0)]
        SpreadingActivation().propagate(["s"], links)
        fires = [e for e in wiring_events.snapshot_after(0) if e["kind"] == "ppr_hit"]
        assert len(fires) >= 1
        assert all("persona" not in e["meta"] for e in fires)
        assert wiring_events.snapshot_after(0, persona="p1") == [
            e for e in wiring_events.snapshot_after(0, persona="p1") if e["kind"] != "ppr_hit"
        ]

    def test_propagate_persona_attributed(self) -> None:
        links = [MemoryLink(source_key="s", target_key="n", weight=1.0)]
        SpreadingActivation().propagate(["s"], links, persona="p1")
        fires = wiring_events.snapshot_after(0, persona="p1")
        assert any(e["kind"] == "ppr_hit" and e["source"] == "s" for e in fires)
        assert wiring_events.snapshot_after(0, persona="other") == []


class TestSSEPersona:
    @pytest.mark.asyncio
    async def test_query_param_filters(self) -> None:
        from nous.api.http.routers.memory import _wiring_stream_gen

        wiring_events.emit("link_fire", source="a", meta={"persona": "p1"})
        wiring_events.emit("link_fire", source="b", meta={"persona": "p2"})
        req = _FakeRequest(query_params={"persona": "p1"}, disconnect_after=1)
        gen = _wiring_stream_gen(req, poll_interval=0.01)  # type: ignore[arg-type]
        chunks = [c async for c in gen]
        wiring = [json.loads(c.split("data: ", 1)[1]) for c in chunks if c.startswith("event: wiring")]
        assert [e["source"] for e in wiring] == ["a"]

    @pytest.mark.asyncio
    async def test_no_param_streams_all(self) -> None:
        from nous.api.http.routers.memory import register_memory_routes

        seen: dict = {}

        class FakeMCP:
            def custom_route(self, path, methods=None):
                def deco(fn):
                    seen[path] = fn
                    return fn

                return deco

        register_memory_routes(FakeMCP())
        wiring_events.emit("link_fire", source="a", meta={"persona": "p1"})
        wiring_events.emit("link_fire", source="legacy")
        with (
            patch("nous.api.http.routers.memory._resolve_persona_from_request", return_value="test"),
            patch("nous.api.http.routers.memory._safe_get_context", return_value=MagicMock()),
        ):
            response = await seen["/api/memory/wiring/stream"](_FakeRequest(disconnect_after=1))  # type: ignore[arg-type]
        chunks = [c async for c in response.body_iterator]
        sources = [json.loads(c.split("data: ", 1)[1])["source"] for c in chunks if c.startswith("event: wiring")]
        assert sources == ["a", "legacy"]


class TestSSEAuth:
    """SSE endpoints resolve persona from ?persona= (EventSource can't send headers).

    Regression: dashboard opens `/api/memory/wiring/stream?persona=herta` but the
    resolver ignored query params → PersonaRequiredError → HTTP 401.
    """

    @pytest.fixture(autouse=True)
    def _handlers(self):
        seen: dict = {}

        class FakeMCP:
            def custom_route(self, path, methods=None):
                def deco(fn):
                    seen[(path, methods[0] if methods else "GET")] = fn
                    return fn

                return deco

        from nous.api.http.routers.memory import register_memory_routes

        register_memory_routes(FakeMCP())
        self.seen = seen
        yield

    @pytest.fixture()
    def _strict_key(self, monkeypatch, tmp_path):
        from nous.config.runtime_config import RuntimeConfigManager
        from nous.config.settings import Settings

        RuntimeConfigManager.reset()
        monkeypatch.delenv("NOUS_API_KEY", raising=False)
        monkeypatch.setattr(
            "nous.config.runtime_config.get_settings",
            lambda: Settings(data_root=str(tmp_path)),
        )
        RuntimeConfigManager().update("general", "api_key", "x" * 16)
        yield
        RuntimeConfigManager.reset()

    @pytest.fixture(autouse=True)
    def _no_context(self):
        """Bypass AppContextRegistry — endpoint auth is what's under test."""
        with (
            patch("nous.api.http.routers.memory._safe_get_context", return_value=MagicMock()),
            patch("nous.api.http.routers.memory._wiring_stream_gen"),
        ):
            yield

    async def test_query_persona_resolves(self):
        """dev pass-through: ?persona= が解決され 200 (旧コードでは 401)"""
        response = await self.seen[("/api/memory/wiring/stream", "GET")](
            _FakeRequest(query_params={"persona": "herta"})
        )
        assert response.status_code == 200

    async def test_no_persona_still_401(self):
        """?persona= 無しは従来どおり 401"""
        from starlette.exceptions import HTTPException

        with pytest.raises(HTTPException) as exc_info:
            await self.seen[("/api/memory/wiring/stream", "GET")](_FakeRequest())
        assert exc_info.value.status_code == 401

    async def test_strict_valid_token_200(self, _strict_key):
        """api_key 設定下: 正当 ?token= 付きはダッシュボード由来の正当アクセスとして 200"""
        response = await self.seen[("/api/memory/wiring/stream", "GET")](
            _FakeRequest(query_params={"persona": "herta", "token": "x" * 16})
        )
        assert response.status_code == 200

    async def test_strict_invalid_token_401(self, _strict_key):
        """api_key 設定下: 不正 token は 401 のまま"""
        from starlette.exceptions import HTTPException

        with pytest.raises(HTTPException) as exc_info:
            await self.seen[("/api/memory/wiring/stream", "GET")](
                _FakeRequest(query_params={"persona": "herta", "token": "wrong"})
            )
        assert exc_info.value.status_code == 401

    async def test_strict_missing_token_401(self, _strict_key):
        """api_key 設定下: token 無しは 401（匿名全開放にはしない）"""
        from starlette.exceptions import HTTPException

        with pytest.raises(HTTPException) as exc_info:
            await self.seen[("/api/memory/wiring/stream", "GET")](_FakeRequest(query_params={"persona": "herta"}))
        assert exc_info.value.status_code == 401
