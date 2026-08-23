"""Unit tests for GET /api/graph/{persona} entity integration (Lane A).

Repo contract (implemented by Lane B) is mocked here:
    get_entities_for_memories(memory_keys, limit=50)
        -> [{id, label, type, mention_count, memory_key}]
    get_relations_between_entities(entity_ids)
        -> [{source_id, target_id, relation, confidence}]
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from nous.api.http.routers import search as search_router


class _Ok:
    def __init__(self, value: Any) -> None:
        self.value = value

    @property
    def is_ok(self) -> bool:
        return True


def _mem(key: str, content: str = "c", tags: list | None = None, related: list | None = None):
    return SimpleNamespace(
        key=key,
        content=content,
        tags=tags or [],
        related_keys=related or [],
        emotion=None,
        emotion_intensity=None,
        importance=0.5,
    )


class _FakeMCP:
    def __init__(self) -> None:
        self.handlers: dict[str, Any] = {}

    def custom_route(self, path: str, methods: list[str]):
        def deco(fn):
            self.handlers[path] = fn
            return fn

        return deco


class _FakeRequest:
    def __init__(self, persona: str = "p") -> None:
        self.path_params = {"persona": persona}
        self.query_params: dict[str, str] = {}
        self.headers: dict[str, str] = {}


@pytest.fixture()
def graph_handler():
    mcp = _FakeMCP()
    search_router.register_search_routes(mcp)
    return mcp.handlers["/api/graph/{persona}"]


def _install_ctx(monkeypatch, memories: list, entity_repo: Any) -> None:
    ctx = SimpleNamespace(
        memory_repo=SimpleNamespace(find_recent=lambda limit: _Ok(memories)),
        entity_repo=entity_repo,
    )
    monkeypatch.setattr(search_router, "_safe_get_context", lambda persona: ctx)


def _entity_repo(entities=None, relations=None, fail_entities=False, fail_relations=False):
    def get_entities_for_memories(memory_keys, limit=50):
        if fail_entities:
            raise RuntimeError("boom")
        return [dict(e) for e in (entities or [])]

    def get_relations_between_entities(entity_ids):
        if fail_relations:
            raise RuntimeError("boom")
        return [dict(r) for r in (relations or [])]

    return SimpleNamespace(
        get_entities_for_memories=get_entities_for_memories,
        get_relations_between_entities=get_relations_between_entities,
    )


async def _json(graph_handler, monkeypatch, memories, repo):
    _install_ctx(monkeypatch, memories, repo)
    resp = await graph_handler(_FakeRequest())
    assert resp.status_code == 200
    import json

    return json.loads(resp.body.decode())


# --- entity nodes + mentions edges ---------------------------------------


async def test_entity_nodes_and_mentions_edges(graph_handler, monkeypatch):
    entities = [
        {"id": "ヘルタ", "label": "ヘルタ", "type": "person", "mention_count": 3, "memory_key": "m1"},
        {"id": "ヘルタ", "label": "ヘルタ", "type": "person", "mention_count": 3, "memory_key": "m2"},
        # sentinel row: aggregate entity without a specific memory
        {"id": "", "label": "aggregate", "type": "concept", "mention_count": 9, "memory_key": ""},
    ]
    data = await _json(graph_handler, monkeypatch, [_mem("m1"), _mem("m2")], _entity_repo(entities))

    ent_nodes = [n for n in data["nodes"] if n.get("kind") == "entity"]
    assert len(ent_nodes) == 1  # deduped; sentinel excluded
    node = ent_nodes[0]
    assert node["key"] == "ent:ヘルタ"
    assert node["label"] == "ヘルタ"
    assert node["entity_type"] == "person"
    assert node["mention_count"] == 3

    mentions = [e for e in data["edges"] if e["type"] == "mentions"]
    assert {("m1", "ent:ヘルタ"), ("m2", "ent:ヘルタ")} == {(e["source"], e["target"]) for e in mentions}


async def test_cap_50_by_mention_count(graph_handler, monkeypatch):
    entities = [
        {"id": f"ent{i}", "label": f"ent{i}", "type": "x", "mention_count": i, "memory_key": "m1"} for i in range(60)
    ]
    data = await _json(graph_handler, monkeypatch, [_mem("m1")], _entity_repo(entities))

    ent_nodes = [n for n in data["nodes"] if n.get("kind") == "entity"]
    assert len(ent_nodes) == 50
    kept_ids = {n["key"] for n in ent_nodes}
    assert "ent:ent59" in kept_ids and "ent:ent10" in kept_ids and "ent:ent9" not in kept_ids
    mentions = [e for e in data["edges"] if e["type"] == "mentions"]
    assert all(e["target"] in kept_ids for e in mentions)


# --- relation edges --------------------------------------------------------


async def test_relation_edges_filtered_to_visible_endpoints(graph_handler, monkeypatch):
    # 52 entities total → cap 50 drops "c" (mention_count 1)
    entities = [
        {"id": "a", "label": "a", "type": "x", "mention_count": 5, "memory_key": "m1"},
        {"id": "b", "label": "b", "type": "y", "mention_count": 4, "memory_key": "m1"},
        {"id": "c", "label": "c", "type": "z", "mention_count": 1, "memory_key": "m1"},
    ] + [{"id": f"f{i}", "label": f"f{i}", "type": "w", "mention_count": 3, "memory_key": "m1"} for i in range(49)]
    relations = [
        {"source_id": "a", "target_id": "b", "relation": "created", "confidence": 0.9},
        {"source_id": "a", "target_id": "c", "relation": "knows", "confidence": 0.8},
    ]
    data = await _json(graph_handler, monkeypatch, [_mem("m1")], _entity_repo(entities, relations))

    rels = [e for e in data["edges"] if e["type"] == "relation"]
    assert len(rels) == 1
    edge = rels[0]
    assert edge["source"] == "ent:a" and edge["target"] == "ent:b"
    assert edge["relation"] == "created"
    assert edge["confidence"] == 0.9
    assert not any(n["key"] == "ent:c" for n in data["nodes"])


# --- backward compatibility -------------------------------------------------


async def test_backward_compat_tag_and_related_preserved(graph_handler, monkeypatch):
    entities = [
        {"id": "e1", "label": "e1", "type": "x", "mention_count": 2, "memory_key": "m1"},
    ]
    # NOTE: existing router behavior suppresses a tag edge when a related
    # edge already exists for the same pair, so use disjoint pairs here.
    memories = [
        _mem("m1", tags=["t"], related=["m3"]),
        _mem("m2", tags=["t"], related=[]),
        _mem("m3", tags=[], related=[]),
    ]
    data = await _json(graph_handler, monkeypatch, memories, _entity_repo(entities))

    types = {e["type"] for e in data["edges"]}
    assert {"tag", "related", "mentions"} <= types
    tag_pairs = {(e["source"], e["target"]) for e in data["edges"] if e["type"] == "tag"}
    assert ("m1", "m2") in tag_pairs or ("m2", "m1") in tag_pairs
    rel_pairs = {(e["source"], e["target"]) for e in data["edges"] if e["type"] == "related"}
    assert ("m1", "m3") in rel_pairs or ("m3", "m1") in rel_pairs


async def test_no_entity_methods_memory_only_graph(graph_handler, monkeypatch):
    """Legacy repo without the new methods → exactly the old response shape."""
    data = await _json(
        graph_handler,
        monkeypatch,
        [
            _mem("m1", tags=["t"], related=["m3"]),
            _mem("m2", tags=["t"]),
            _mem("m3"),
        ],
        SimpleNamespace(),  # no get_entities_for_memories / get_relations_between_entities
    )
    assert not any(n.get("kind") == "entity" for n in data["nodes"])
    assert not any(e["type"] in ("mentions", "relation") for e in data["edges"])
    assert any(e["type"] == "tag" for e in data["edges"])
    assert any(e["type"] == "related" for e in data["edges"])


async def test_repo_failure_degrades_to_memory_only(graph_handler, monkeypatch):
    data = await _json(
        graph_handler,
        monkeypatch,
        [_mem("m1", tags=["t"], related=["m3"]), _mem("m2", tags=["t"]), _mem("m3")],
        _entity_repo(fail_entities=True),
    )
    assert not any(n.get("kind") == "entity" for n in data["nodes"])
    assert any(e["type"] == "tag" for e in data["edges"])
