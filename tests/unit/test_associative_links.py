"""Tests for entity co-occurrence links + spreading activation (Lane B)."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest

from nous.domain.memory.entities import Memory
from nous.domain.search.engine import SearchEngine, SearchQuery, SearchResult
from nous.domain.shared.result import Success
from nous.infrastructure.sqlite.entity_repo import SQLiteEntityRepository

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _insert_memory_entities(conn, rows: list[tuple[str, str]]) -> None:
    db = conn.get_memory_db()
    entity_ids = sorted({e for _, e in rows})
    db.executemany(
        "INSERT OR IGNORE INTO entities (id, entity_type, first_seen, last_seen) VALUES (?, 'test', '', '')",
        [(eid,) for eid in entity_ids],
    )
    db.executemany(
        "INSERT OR IGNORE INTO memory_entities (memory_key, entity_id, role) VALUES (?, ?, 'mentioned')",
        rows,
    )


@pytest.fixture
def entity_repo(sqlite_conn):
    return SQLiteEntityRepository(sqlite_conn)


def _mem(key: str, content: str = "content") -> Memory:
    now = datetime.now(UTC)
    return Memory(
        key=key,
        content=content,
        created_at=now,
        updated_at=now,
        importance=0.5,
        emotion="neutral",
        tags=[],
    )


def _result(key: str, score: float) -> SearchResult:
    return SearchResult(memory=_mem(key), score=score, source="keyword")


def _make_keyword_strategy(pairs: list[tuple[Memory, float]]):
    strat = MagicMock()
    strat.search.return_value = Success(pairs)
    return strat


# ---------------------------------------------------------------------------
# SQLiteEntityRepository.get_links_for_keys
# ---------------------------------------------------------------------------


class TestGetLinksForKeys:
    def test_cooccurrence_links_returned(self, sqlite_conn, entity_repo):
        _insert_memory_entities(sqlite_conn, [("m1", "e1"), ("m2", "e1"), ("m3", "e2")])
        links = entity_repo.get_links_for_keys(["m1"])
        assert len(links) == 1
        link = links[0]
        assert link.source_key == "m1"
        assert link.target_key == "m2"
        assert link.weight == 0.5
        assert link.link_type == "semantic"

    def test_no_self_links(self, sqlite_conn, entity_repo):
        _insert_memory_entities(sqlite_conn, [("m1", "e1"), ("m2", "e1")])
        links = entity_repo.get_links_for_keys(["m1"])
        assert all(link.source_key != link.target_key for link in links)

    def test_empty_db_returns_empty(self, entity_repo):
        assert entity_repo.get_links_for_keys(["missing"]) == []

    def test_empty_keys_returns_empty(self, entity_repo):
        assert entity_repo.get_links_for_keys([]) == []

    def test_default_limit_caps_hub(self, sqlite_conn, entity_repo):
        # Hub memory linked to 1200 others via one shared entity → capped at 1000
        rows = [("hub", "hub_e")] + [(f"mem_{i:04d}", "hub_e") for i in range(1200)]
        _insert_memory_entities(sqlite_conn, rows)
        links = entity_repo.get_links_for_keys(["hub"])
        assert len(links) == 1000

    def test_explicit_limit_respected(self, sqlite_conn, entity_repo):
        rows = [("hub", "hub_e")] + [(f"mem_{i:04d}", "hub_e") for i in range(20)]
        _insert_memory_entities(sqlite_conn, rows)
        assert len(entity_repo.get_links_for_keys(["hub"], limit=5)) == 5


# ---------------------------------------------------------------------------
# SearchEngine spreading activation wiring
# ---------------------------------------------------------------------------


class TestSpreadingActivationWiring:
    @pytest.mark.asyncio
    async def test_link_repo_boosts_associated_tail_result(self, sqlite_conn, entity_repo):
        # Seeds s1..s5; tail_a shares an entity with s1, tail_b does not.
        # Without link_repo: tail_b (0.25) ranks above tail_a (0.24).
        # With link_repo: SA boosts tail_a above tail_b.
        _insert_memory_entities(sqlite_conn, [("s1", "shared_e"), ("tail_a", "shared_e")])
        pairs = [
            (_mem("s1"), 0.9),
            (_mem("s2"), 0.8),
            (_mem("s3"), 0.7),
            (_mem("s4"), 0.6),
            (_mem("s5"), 0.5),
            (_mem("tail_b"), 0.25),
            (_mem("tail_a"), 0.24),
        ]
        kw = _make_keyword_strategy(pairs)

        engine_without = SearchEngine(keyword_search=_make_keyword_strategy(pairs))
        result_without = await engine_without.search(SearchQuery(text="q", mode="hybrid", top_k=10))
        keys_without = [r.memory.key for r in result_without.value]
        assert keys_without.index("tail_b") < keys_without.index("tail_a")

        engine_with = SearchEngine(keyword_search=kw, link_repo=entity_repo)
        result_with = await engine_with.search(SearchQuery(text="q", mode="hybrid", top_k=10))
        keys_with = [r.memory.key for r in result_with.value]
        assert keys_with.index("tail_a") < keys_with.index("tail_b")

    @pytest.mark.asyncio
    async def test_sa_boost_capped_at_01(self, sqlite_conn, entity_repo):
        # Even a strongly activated neighbour gets at most +0.1
        _insert_memory_entities(sqlite_conn, [("s1", "e"), ("tail_a", "e")])
        pairs = [
            (_mem("s1"), 0.9),
            (_mem("tail_b"), 0.30),
            (_mem("tail_a"), 0.29),
        ]
        engine = SearchEngine(keyword_search=_make_keyword_strategy(pairs), link_repo=entity_repo)
        result = await engine.search(SearchQuery(text="q", mode="hybrid", top_k=10))
        scores = {r.memory.key: r.score for r in result.value}
        # tail_a activation ≈ 0.63 → uncapped boost would be ~0.126; capped at 0.1
        assert scores["tail_a"] - 0.29 <= 0.1 + 1e-9

    @pytest.mark.asyncio
    async def test_empty_db_link_repo_is_noop(self, sqlite_conn, entity_repo):
        pairs = [(_mem("a"), 0.9), (_mem("b"), 0.5)]
        engine = SearchEngine(keyword_search=_make_keyword_strategy(pairs), link_repo=entity_repo)
        result = await engine.search(SearchQuery(text="q", mode="hybrid", top_k=10))
        assert result.is_ok
        assert [r.memory.key for r in result.value] == ["a", "b"]

    @pytest.mark.asyncio
    async def test_raising_link_repo_does_not_break_search(self):
        class BrokenRepo:
            def get_links_for_keys(self, keys, limit=1000):
                raise RuntimeError("boom")

        pairs = [(_mem("a"), 0.9)]
        engine = SearchEngine(keyword_search=_make_keyword_strategy(pairs), link_repo=BrokenRepo())
        result = await engine.search(SearchQuery(text="q", mode="hybrid"))
        assert result.is_ok
        assert [r.memory.key for r in result.value] == ["a"]


# ---------------------------------------------------------------------------
# Graph layer contract (Lane A): entities for memories + relations
# ---------------------------------------------------------------------------


def _insert_entity(conn, eid: str, mention_count: int = 1) -> None:
    conn.get_memory_db().execute(
        "INSERT OR IGNORE INTO entities (id, entity_type, first_seen, last_seen, mention_count) "
        "VALUES (?, 'test', '', '', ?)",
        (eid, mention_count),
    )


def _insert_relation(conn, source: str, target: str, relation: str = "related", confidence: float = 0.8) -> None:
    conn.get_memory_db().execute(
        "INSERT OR IGNORE INTO entity_relations (source_entity, target_entity, relation_type, memory_key, confidence, created_at) "
        "VALUES (?, ?, ?, '', ?, '')",
        (source, target, relation, confidence),
    )


class TestGetEntitiesForMemories:
    def test_returns_entities_ordered_by_mention_count(self, sqlite_conn, entity_repo):
        _insert_entity(sqlite_conn, "e_high", mention_count=10)
        _insert_entity(sqlite_conn, "e_low", mention_count=1)
        _insert_memory_entities(sqlite_conn, [("m1", "e_high"), ("m1", "e_low")])
        rows = entity_repo.get_entities_for_memories(["m1"])
        assert [r["id"] for r in rows] == ["e_high", "e_low"]
        assert rows[0]["mention_count"] == 10
        assert rows[0]["label"] == "e_high"
        assert rows[0]["type"] == "test"
        assert rows[0]["memory_key"] == "m1"

    def test_limit_respected(self, sqlite_conn, entity_repo):
        for i in range(10):
            _insert_entity(sqlite_conn, f"e{i}", mention_count=i)
        _insert_memory_entities(sqlite_conn, [("m1", f"e{i}") for i in range(10)])
        assert len(entity_repo.get_entities_for_memories(["m1"], limit=3)) == 3

    def test_empty_keys_noop(self, entity_repo):
        assert entity_repo.get_entities_for_memories([]) == []

    def test_empty_db_noop(self, entity_repo):
        assert entity_repo.get_entities_for_memories(["missing"]) == []

    def test_limit_applies_to_distinct_entities_not_rows(self, sqlite_conn, entity_repo):
        # Regression (#081 BLOCK): a hub entity's rows must not consume the
        # whole LIMIT — limit caps distinct entities (top-N), not raw rows.
        _insert_entity(sqlite_conn, "hub_e", mention_count=100)
        rows = [(f"m_hub_{i}", "hub_e") for i in range(10)]
        rows += [(f"m_{i:02d}", f"e{i:02d}") for i in range(60)]
        _insert_memory_entities(sqlite_conn, rows)
        result = entity_repo.get_entities_for_memories([k for k, _ in rows], limit=50)
        distinct_ids = {r["id"] for r in result}
        assert len(distinct_ids) >= 2  # old impl returned 50 rows / 1 distinct entity
        assert len(distinct_ids) == 50

    def test_mention_rows_restricted_to_visible_set(self, sqlite_conn, entity_repo):
        # Stage-2 rows (memory_key-bearing, for mentions edges) must only
        # cover entities inside the stage-1 visible set.
        _insert_entity(sqlite_conn, "hub_e", mention_count=100)
        _insert_entity(sqlite_conn, "ea", mention_count=1)
        _insert_entity(sqlite_conn, "eb", mention_count=1)
        rows = [(f"m_hub_{i}", "hub_e") for i in range(5)]
        rows += [("m_a", "ea"), ("m_b", "eb")]
        _insert_memory_entities(sqlite_conn, rows)
        result = entity_repo.get_entities_for_memories([k for k, _ in rows], limit=2)
        ids_in_rows = {r["id"] for r in result}
        assert ids_in_rows == {"hub_e", "ea"}  # eb is outside top-2 visible set
        hub_keys = {r["memory_key"] for r in result if r["id"] == "hub_e"}
        assert len(hub_keys) == 5  # all mention rows for the visible hub survive


class TestGetRelationsBetweenEntities:
    def test_both_endpoints_filtered(self, sqlite_conn, entity_repo):
        for eid in ("a", "b", "c"):
            _insert_entity(sqlite_conn, eid)
        _insert_relation(sqlite_conn, "a", "b")
        _insert_relation(sqlite_conn, "b", "c")  # c not queried → excluded
        rels = entity_repo.get_relations_between_entities(["a", "b"])
        assert len(rels) == 1
        assert rels[0]["source_id"] == "a"
        assert rels[0]["target_id"] == "b"
        assert rels[0]["relation"] == "related"
        assert rels[0]["confidence"] == 0.8

    def test_empty_ids_noop(self, entity_repo):
        assert entity_repo.get_relations_between_entities([]) == []

    def test_empty_db_noop(self, entity_repo):
        assert entity_repo.get_relations_between_entities(["x"]) == []
