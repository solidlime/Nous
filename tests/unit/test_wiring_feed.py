"""Wiring fire event feed backend (synapse viz) tests.

- emit → ring buffer (3 kinds, cap 200)
- 3 hooks fire without breaking main flows
- SSE initial flush at function + router level (no real HTTP)
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nous.domain.memory import wiring_events
from nous.domain.memory.enrich_service import MemoryEnrichService
from nous.domain.memory.entities import MemoryStrength
from nous.domain.memory.memory_link import MemoryLink
from nous.domain.memory.query_service import MemoryQueryService
from nous.domain.search.spreading_activation import SpreadingActivation
from nous.domain.shared.result import Success
from nous.infrastructure.sqlite.connection import SQLiteConnection
from nous.infrastructure.sqlite.entity_repo import SQLiteEntityRepository


@pytest.fixture(autouse=True)
def _clean_buffer():
    wiring_events.clear()
    yield
    wiring_events.clear()


class TestEmitBuffer:
    def test_emit_three_kinds(self) -> None:
        assert wiring_events.emit("link_fire", source="a", target="b", weight=0.6) is True
        assert wiring_events.emit("recall_boost", source="m", weight=0.8) is True
        assert wiring_events.emit("ppr_hit", source="s", weight=0.4) is True
        assert wiring_events.emit("replay_fire", source="r", target="t", weight=0.7) is True
        events = wiring_events.snapshot_after(0)
        assert [e["kind"] for e in events] == [
            "link_fire",
            "recall_boost",
            "ppr_hit",
            "replay_fire",
        ]
        assert [e["seq"] for e in events] == [
            events[0]["seq"],
            events[0]["seq"] + 1,
            events[0]["seq"] + 2,
            events[0]["seq"] + 3,
        ]
        assert events[0]["source"] == "a" and events[0]["target"] == "b"
        assert events[0]["ts"] != ""

    def test_novelty_gate_kind(self) -> None:
        """novelty_gate kind（新規性ゲート、lane1 契約）が受信される。"""
        assert wiring_events.emit("novelty_gate", source="k1", weight=2.0) is True
        events = [e for e in wiring_events.snapshot_after(0) if e["kind"] == "novelty_gate"]
        assert len(events) == 1
        assert events[0]["source"] == "k1"
        assert events[0]["weight"] == 2.0

    def test_unknown_kind_dropped(self) -> None:
        assert wiring_events.emit("nope") is False
        assert wiring_events.snapshot_after(0) == []

    def test_ring_caps_at_200(self) -> None:
        for i in range(210):
            wiring_events.emit("link_fire", source=f"s{i}")
        events = wiring_events.snapshot_after(0)
        assert len(events) == 200
        assert events[0]["source"] == "s10"


class TestHooks:
    def test_upsert_link_fires(self, tmp_path) -> None:
        conn = SQLiteConnection(data_dir=str(tmp_path), persona="test_wiring")
        conn.initialize_schema()
        try:
            repo = SQLiteEntityRepository(conn)
            assert repo.upsert_link("a", "b", "semantic", strength=0.1).is_ok
            fires = [e for e in wiring_events.snapshot_after(0) if e["kind"] == "link_fire"]
            assert len(fires) == 1
            assert fires[0]["source"] == "a" and fires[0]["target"] == "b"
            assert fires[0]["weight"] == 0.6
        finally:
            conn.close()

    def test_boost_recall_fires(self) -> None:
        repo = MagicMock()
        repo.get_strength.return_value = Success(MemoryStrength(memory_key="m1"))
        repo.save_strength.side_effect = lambda s: Success(None)
        result = MemoryQueryService(repo).boost_recall("m1")
        assert result.is_ok
        fires = [e for e in wiring_events.snapshot_after(0) if e["kind"] == "recall_boost"]
        assert len(fires) == 1
        assert fires[0]["source"] == "m1"
        assert fires[0]["weight"] > 0

    def test_propagate_fires_top_seeds(self) -> None:
        links = [MemoryLink(source_key=s, target_key="n", weight=1.0) for s in ("s1", "s2")]
        SpreadingActivation().propagate(["s1", "s2"], links)
        fires = [e for e in wiring_events.snapshot_after(0) if e["kind"] == "ppr_hit"]
        assert {e["source"] for e in fires} == {"s1", "s2"}
        assert all(e["weight"] > 0 for e in fires)


class TestEnrichFires:
    """replay_fire pulses from the enrichment pipeline (offline reactivation)."""

    @staticmethod
    def _svc(enrichment, repo=None, entity_service=None) -> MemoryEnrichService:
        enricher = SimpleNamespace(enrich_async=AsyncMock(return_value=enrichment))
        return MemoryEnrichService(enricher, entity_service, repo or MagicMock())

    @pytest.mark.asyncio
    async def test_relation_registration_fires(self) -> None:
        rel = SimpleNamespace(
            source_entity="s1",
            target_entity="s2",
            relation_type="related",
            confidence=0.8,
        )
        enrichment = SimpleNamespace(importance=0.5, relations=[rel])
        entity_service = MagicMock()
        svc = self._svc(enrichment, entity_service=entity_service)
        memory = MagicMock(importance=0.5)
        with patch("nous.domain.memory.sudachi_extractor.SudachiExtractor") as ner:
            ner.return_value.extract.return_value = []
            await svc.enrich_memory(memory, "内容", None, "k1", 0.5)
        fires = [e for e in wiring_events.snapshot_after(0) if e["kind"] == "replay_fire"]
        assert len(fires) == 1
        assert fires[0]["source"] == "s1" and fires[0]["target"] == "s2"
        assert fires[0]["weight"] == 0.8
        assert fires[0]["meta"]["memory_key"] == "k1"

    @pytest.mark.asyncio
    async def test_importance_only_fires_once(self) -> None:
        enrichment = SimpleNamespace(importance=0.9, relations=[])
        svc = self._svc(enrichment)
        memory = MagicMock(importance=0.5)
        with patch("nous.domain.memory.sudachi_extractor.SudachiExtractor") as ner:
            ner.return_value.extract.return_value = []
            await svc.enrich_memory(memory, "内容", None, "k2", 0.5)
        fires = [e for e in wiring_events.snapshot_after(0) if e["kind"] == "replay_fire"]
        assert len(fires) == 1
        assert fires[0]["source"] == "k2" and fires[0]["target"] == ""
        assert fires[0]["weight"] == 0.9

    @pytest.mark.asyncio
    async def test_failed_relation_does_not_fire(self) -> None:
        rel = SimpleNamespace(
            source_entity="s1",
            target_entity="s2",
            relation_type="related",
            confidence=0.8,
        )
        enrichment = SimpleNamespace(importance=0.5, relations=[rel])
        entity_service = MagicMock()
        entity_service.add_relation.side_effect = RuntimeError("db down")
        svc = self._svc(enrichment, entity_service=entity_service)
        with patch("nous.domain.memory.sudachi_extractor.SudachiExtractor") as ner:
            ner.return_value.extract.return_value = []
            await svc.enrich_memory(MagicMock(importance=0.5), "内容", None, "k3", 0.5)
        assert [e for e in wiring_events.snapshot_after(0) if e["kind"] == "replay_fire"] == []

    @pytest.mark.asyncio
    async def test_importance_only_clamps_weight(self) -> None:
        enrichment = SimpleNamespace(importance=1.3, relations=[])
        svc = self._svc(enrichment)
        memory = MagicMock(importance=0.5)
        with patch("nous.domain.memory.sudachi_extractor.SudachiExtractor") as ner:
            ner.return_value.extract.return_value = []
            await svc.enrich_memory(memory, "内容", None, "k4", 0.5)
        fires = [e for e in wiring_events.snapshot_after(0) if e["kind"] == "replay_fire"]
        assert len(fires) == 1
        assert fires[0]["weight"] == 1.0


class _FakeRequest:
    def __init__(self, disconnect_after: int = 99):
        self.query_params: dict = {}
        self.path_params: dict = {}
        self._calls = 0
        self._disconnect_after = disconnect_after

    async def is_disconnected(self) -> bool:
        self._calls += 1
        return self._calls > self._disconnect_after


class TestSSEFlush:
    @pytest.mark.asyncio
    async def test_initial_flush(self) -> None:
        from nous.api.http.routers.memory import _wiring_stream_gen

        wiring_events.emit("link_fire", source="a", target="b", weight=0.6)
        wiring_events.emit("ppr_hit", source="s", weight=0.4)
        gen = _wiring_stream_gen(_FakeRequest(disconnect_after=1), poll_interval=0.01)  # type: ignore[arg-type]
        chunks = [c async for c in gen]
        assert chunks[0].startswith("event: connected")
        wiring = [c for c in chunks[1:] if c.startswith("event: wiring")]
        assert len(wiring) == 2
        first = json.loads(wiring[0].split("data: ", 1)[1])
        assert first["kind"] == "link_fire" and first["source"] == "a"

    def test_route_registered(self) -> None:
        from nous.api.http.routers.memory import register_memory_routes

        seen: dict = {}

        class FakeMCP:
            def custom_route(self, path, methods=None):
                def deco(fn):
                    seen[path] = fn
                    return fn

                return deco

        register_memory_routes(FakeMCP())
        assert "/api/memory/wiring/stream" in seen

    @pytest.mark.asyncio
    async def test_route_handler_flush(self) -> None:
        from nous.api.http.routers.memory import register_memory_routes

        seen: dict = {}

        class FakeMCP:
            def custom_route(self, path, methods=None):
                def deco(fn):
                    seen[path] = fn
                    return fn

                return deco

        register_memory_routes(FakeMCP())
        handler = seen["/api/memory/wiring/stream"]
        wiring_events.emit("recall_boost", source="m", weight=0.8)
        with (
            patch("nous.api.http.routers.memory._resolve_persona_from_request", return_value="test"),
            patch("nous.api.http.routers.memory._safe_get_context", return_value=MagicMock()),
        ):
            response = await handler(_FakeRequest(disconnect_after=1))  # type: ignore[arg-type]
        assert response.media_type == "text/event-stream"
        chunks = [c async for c in response.body_iterator]
        assert any("recall_boost" in c for c in chunks)
