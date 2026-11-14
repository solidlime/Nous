"""プロセス内メトリクス（kanban #10）."""

from __future__ import annotations

import pytest

from nous.infrastructure.metrics import registry

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def _clean():
    registry.reset()
    yield
    registry.reset()


def test_snapshot_is_empty_for_unknown_persona() -> None:
    snap = registry.snapshot("nobody")
    assert snap["search"] == {
        "count": 0,
        "zero_result": 0,
        "zero_result_rate": 0.0,
        "p50_ms": 0.0,
        "p95_ms": 0.0,
        "samples": 0,
    }
    assert snap["tools"] == {}


def test_observe_search_tracks_zero_result_rate() -> None:
    registry.observe_search("p1", 10.0, 3)
    registry.observe_search("p1", 30.0, 0)
    snap = registry.snapshot("p1")["search"]
    assert snap["count"] == 2
    assert snap["zero_result"] == 1
    assert snap["zero_result_rate"] == 0.5


def test_percentiles_are_monotonic() -> None:
    for ms in range(1, 101):
        registry.observe_search("p1", float(ms), 1)
    snap = registry.snapshot("p1")["search"]
    assert snap["p50_ms"] <= snap["p95_ms"]
    assert 40 <= snap["p50_ms"] <= 60
    assert snap["p95_ms"] >= 90


def test_samples_are_capped() -> None:
    for _ in range(registry.MAX_SAMPLES + 50):
        registry.observe_search("p1", 5.0, 1)
    assert registry.snapshot("p1")["search"]["samples"] == registry.MAX_SAMPLES


def test_observe_tool_counts_and_sorts() -> None:
    registry.observe_tool("p1", "memory_search")
    registry.observe_tool("p1", "memory_search")
    registry.observe_tool("p1", "wiki_read")
    tools = registry.snapshot("p1")["tools"]
    assert tools == {"memory_search": 2, "wiki_read": 1}


def test_personas_are_isolated() -> None:
    registry.observe_search("p1", 10.0, 1)
    registry.observe_search("p2", 20.0, 0)
    assert registry.snapshot("p1")["search"]["count"] == 1
    assert registry.snapshot("p2")["search"]["zero_result"] == 1
