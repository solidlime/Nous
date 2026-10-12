"""Unit tests for GET /api/search/{persona} entity-layer wiring (#011 Phase 15).

The firing visualization needs entity nodes in the search response, in the
same shape as GET /api/graph, so a single frontend branch paints them:
    nodes: [{key, kind:'entity', label, entity_type, typed_by, mention_count}]
    edges: [{source, target, type:'mentions'}]

Repo contract (mocked here):
    get_entities_for_memories(memory_keys, limit=50)
        -> [{id, label, type, mention_count, metadata, memory_key}]
    get_relations_between_entities(entity_ids)
        -> [{source_id, target_id, relation, confidence}]
"""

from __future__ import annotations

import json
from datetime import datetime
from types import SimpleNamespace
from typing import Any

import pytest

from nous.api.http.routers import search as search_router
from nous.domain.memory.entities import Memory
from nous.domain.search.engine import SearchResult


class _Ok:
    def __init__(self, value: Any) -> None:
        self.value = value

    @property
    def is_ok(self) -> bool:
        return True


class _FakeMCP:
    def __init__(self) -> None:
        self.handlers: dict[str, Any] = {}

    def custom_route(self, path: str, methods: list[str]):
        def deco(fn):
            self.handlers[path] = fn
            return fn

        return deco


class _FakeRequest:
    def __init__(self, persona: str = "p", query: dict[str, str] | None = None) -> None:
        self.path_params = {"persona": persona}
        self.query_params = query or {"q": "x"}
        self.headers: dict[str, str] = {}


def _result(key: str, score: float = 0.9) -> SearchResult:
    now = datetime.now()
    mem = Memory(key=key, content="c", created_at=now, updated_at=now)
    return SearchResult(memory=mem, score=score, source="keyword")


@pytest.fixture()
def search_handler():
    mcp = _FakeMCP()
    search_router.register_search_routes(mcp)
    return mcp.handlers["/api/search/{persona}"]


def _entity_repo(entities=None):
    def get_entities_for_memories(memory_keys, limit=50):
        return [dict(e) for e in (entities or [])]

    def get_relations_between_entities(entity_ids):
        return []

    return SimpleNamespace(
        get_entities_for_memories=get_entities_for_memories,
        get_relations_between_entities=get_relations_between_entities,
    )


def _install(monkeypatch, results, entity_repo) -> None:
    async def _fake_search(query):
        return _Ok(results)

    ctx = SimpleNamespace(
        search_engine=SimpleNamespace(search=_fake_search),
        entity_repo=entity_repo,
        memory_repo=None,
    )
    monkeypatch.setattr(search_router, "_safe_get_context", lambda persona: ctx)


async def _json(search_handler, monkeypatch, results, repo):
    _install(monkeypatch, results, repo)
    resp = await search_handler(_FakeRequest())
    assert resp.status_code == 200
    return json.loads(resp.body.decode())


async def test_search_carries_entity_nodes_and_mentions(search_handler, monkeypatch):
    entities = [
        {"id": "ヘルタ", "label": "ヘルタ", "type": "person", "mention_count": 3, "memory_key": "m1"},
        {"id": "ヘルタ", "label": "ヘルタ", "type": "person", "mention_count": 3, "memory_key": "m2"},
        # sentinel row: aggregate entity without a specific memory
        {"id": "", "label": "aggregate", "type": "concept", "mention_count": 9, "memory_key": ""},
    ]
    data = await _json(search_handler, monkeypatch, [_result("m1"), _result("m2")], _entity_repo(entities))

    ent = [n for n in data["nodes"] if n.get("kind") == "entity"]
    assert len(ent) == 1  # deduped; sentinel excluded
    assert ent[0]["key"] == "ent:ヘルタ"
    assert ent[0]["entity_type"] == "person"
    assert ent[0]["mention_count"] == 3

    mentions = [e for e in data["edges"] if e["type"] == "mentions"]
    assert {("m1", "ent:ヘルタ"), ("m2", "ent:ヘルタ")} == {(e["source"], e["target"]) for e in mentions}
    # memory 本体の結果は不変
    assert [r["memory"]["key"] for r in data["results"]] == ["m1", "m2"]


async def test_search_entity_typed_by_from_metadata(search_handler, monkeypatch):
    entities = [
        {
            "id": "p1",
            "label": "P",
            "type": "person",
            "mention_count": 2,
            "memory_key": "m1",
            "metadata": json.dumps({"typed_by": "llm"}),
        },
        {"id": "p2", "label": "Q", "type": "person", "mention_count": 1, "memory_key": "m1", "metadata": "{}"},
    ]
    data = await _json(search_handler, monkeypatch, [_result("m1")], _entity_repo(entities))
    by_id = {n["key"]: n for n in data["nodes"] if n.get("kind") == "entity"}
    assert by_id["ent:p1"]["typed_by"] == "llm"
    assert by_id["ent:p2"]["typed_by"] is None


async def test_search_entity_cap_50_by_mention_count(search_handler, monkeypatch):
    entities = [
        {"id": f"e{i}", "label": f"e{i}", "type": "x", "mention_count": i, "memory_key": "m1"} for i in range(60)
    ]
    data = await _json(search_handler, monkeypatch, [_result("m1")], _entity_repo(entities))
    ent = [n for n in data["nodes"] if n.get("kind") == "entity"]
    assert len(ent) == 50
    kept = {n["key"] for n in ent}
    assert "ent:e59" in kept and "ent:e10" in kept and "ent:e9" not in kept
    assert all(e["target"] in kept for e in data["edges"] if e["type"] == "mentions")


async def test_search_entity_layer_absent_for_legacy_repo(search_handler, monkeypatch):
    """Legacy repo without entity methods → empty layer, memory results intact."""
    data = await _json(search_handler, monkeypatch, [_result("m1")], SimpleNamespace())
    assert data["nodes"] == []
    assert data["edges"] == []
    assert len(data["results"]) == 1
