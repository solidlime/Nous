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
        self.query_params: dict = query_params or {}
        self.path_params: dict = {}
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

    def test_propagate_persona_none(self) -> None:
        links = [MemoryLink(source_key="s", target_key="n", weight=1.0)]
        SpreadingActivation().propagate(["s"], links)
        fires = [e for e in wiring_events.snapshot_after(0) if e["kind"] == "ppr_hit"]
        assert len(fires) >= 1
        assert all("persona" not in e["meta"] for e in fires)
        assert wiring_events.snapshot_after(0, persona="p1") == [
            e for e in wiring_events.snapshot_after(0, persona="p1") if e["kind"] != "ppr_hit"
        ]


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
