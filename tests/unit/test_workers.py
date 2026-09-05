"""Task 5: consolidation worker uses a single batch entity query (no N+1)."""

from __future__ import annotations

from types import SimpleNamespace

from nous.application.workers.consolidation_worker import _memory_entity_map
from nous.domain.shared.result import Failure, Success


def test_batch_entity_map_single_query():
    calls: list[list[str]] = []

    class FakeRepo:
        def get_entities_for_memories(self, keys: list[str], limit: int = 50):
            calls.append(list(keys))
            return [
                {"id": "e1", "memory_key": "m1"},
                {"id": "e1", "memory_key": "m2"},
                {"id": "e2", "memory_key": "m2"},
            ]

    out = _memory_entity_map(FakeRepo(), ["m1", "m2", "m3"])
    assert calls == [["m1", "m2", "m3"]]
    assert out == {"m1": {"e1"}, "m2": {"e1", "e2"}, "m3": set()}


def test_batch_falls_back_to_per_memory():
    per_calls: list[str] = []

    class LegacyRepo:
        def get_memory_entities(self, key: str):
            per_calls.append(key)
            if key == "m1":
                return Success([SimpleNamespace(id="e9")])
            return Failure("nope")

    out = _memory_entity_map(LegacyRepo(), ["m1", "m2"])
    assert sorted(per_calls) == ["m1", "m2"]
    assert out == {"m1": {"e9"}, "m2": set()}
