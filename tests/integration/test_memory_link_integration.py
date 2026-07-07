"""Integration tests for MemoryLinkRepository — SQLite-backed Hebbian link persistence."""

from __future__ import annotations

import pytest

from nous.infrastructure.sqlite.memory_link_repo import MemoryLinkRepository


@pytest.fixture()
def link_repo(tmp_path):
    """Create a MemoryLinkRepository backed by a temporary SQLite database.

    Uses an in-memory SQLite file to test persistence without needing the
    full SQLiteConnection infrastructure.
    """
    import sqlite3

    db_path = tmp_path / "test_memory_links.sqlite"
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS memory_links (
            source_key TEXT NOT NULL,
            target_key TEXT NOT NULL,
            weight REAL NOT NULL DEFAULT 0.5,
            link_type TEXT NOT NULL DEFAULT 'semantic',
            co_activation_count INTEGER DEFAULT 0,
            last_activated TEXT,
            PRIMARY KEY (source_key, target_key, link_type)
        )
    """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_links_source ON memory_links(source_key)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_links_target ON memory_links(target_key)")
    conn.commit()

    # We need to wrap this in an object with a get_memory_db method
    class FakeConnection:
        def __init__(self, c):
            self._c = c

        def get_memory_db(self):
            return self._c

    repo = MemoryLinkRepository(FakeConnection(conn))
    yield repo
    conn.close()


class TestMemoryLinkRepositoryUpsert:
    """Insert and Hebbian-boost operations."""

    def test_upsert_creates_link(self, link_repo) -> None:
        link_repo.upsert("mem_a", "mem_b", "semantic")
        links = link_repo.get_links("mem_a")
        assert len(links) == 1
        assert links[0].source_key == "mem_a"
        assert links[0].target_key == "mem_b"
        assert links[0].weight == 0.5
        assert links[0].link_type == "semantic"
        assert links[0].co_activation_count == 1
        assert links[0].last_activated is not None  # set by SQLite datetime('now')

    def test_upsert_updates_existing_link_hebbian(self, link_repo) -> None:
        link_repo.upsert("mem_a", "mem_b", "semantic")
        link_repo.upsert("mem_a", "mem_b", "semantic")

        links = link_repo.get_links("mem_a")
        assert len(links) == 1
        assert links[0].weight == 0.6  # 0.5 + 0.1
        assert links[0].co_activation_count == 2

    def test_upsert_multiple_boosts_capped(self, link_repo) -> None:
        for _ in range(10):
            link_repo.upsert("mem_a", "mem_b", "semantic")

        links = link_repo.get_links("mem_a")
        assert links[0].weight == 1.0  # capped
        assert links[0].co_activation_count == 10

    def test_upsert_different_link_types_independent(self, link_repo) -> None:
        link_repo.upsert("mem_a", "mem_b", "semantic")
        link_repo.upsert("mem_a", "mem_b", "emotional")

        links = link_repo.get_links("mem_a")
        assert len(links) == 2
        types = {ln.link_type for ln in links}
        assert types == {"semantic", "emotional"}
        # Each starts at 0.5 since they're separate records
        assert all(ln.weight == 0.5 for ln in links)

    def test_upsert_reverse_direction(self, link_repo) -> None:
        link_repo.upsert("mem_a", "mem_b", "semantic")
        link_repo.upsert("mem_b", "mem_a", "semantic")

        a_links = link_repo.get_links("mem_a")
        b_links = link_repo.get_links("mem_b")
        assert len(a_links) == 1
        assert a_links[0].target_key == "mem_b"
        assert len(b_links) == 1
        assert b_links[0].target_key == "mem_a"

    def test_upsert_multiple_targets(self, link_repo) -> None:
        link_repo.upsert("mem_a", "mem_b")
        link_repo.upsert("mem_a", "mem_c")
        link_repo.upsert("mem_a", "mem_d")

        links = link_repo.get_links("mem_a")
        assert len(links) == 3
        targets = {ln.target_key for ln in links}
        assert targets == {"mem_b", "mem_c", "mem_d"}


class TestMemoryLinkRepositoryGetLinks:
    """Query operations."""

    def test_get_links_returns_by_source(self, link_repo) -> None:
        link_repo.upsert("mem_a", "mem_b")
        link_repo.upsert("mem_c", "mem_d")

        a_links = link_repo.get_links("mem_a")
        c_links = link_repo.get_links("mem_c")
        assert len(a_links) == 1
        assert a_links[0].target_key == "mem_b"
        assert len(c_links) == 1
        assert c_links[0].target_key == "mem_d"

    def test_get_links_empty_for_unknown_key(self, link_repo) -> None:
        links = link_repo.get_links("nonexistent")
        assert links == []

    def test_get_links_no_links_yet(self, link_repo) -> None:
        assert link_repo.get_links("mem_a") == []


class TestMemoryLinkRepositoryGetLinksForKeys:
    """Batch query operations."""

    def test_get_links_for_keys(self, link_repo) -> None:
        link_repo.upsert("mem_a", "mem_x")
        link_repo.upsert("mem_b", "mem_y")
        link_repo.upsert("mem_c", "mem_z")

        results = link_repo.get_links_for_keys(["mem_a", "mem_c"])
        assert len(results) == 2
        targets = {r.target_key for r in results}
        assert targets == {"mem_x", "mem_z"}

    def test_get_links_for_keys_empty_list(self, link_repo) -> None:
        assert link_repo.get_links_for_keys([]) == []

    def test_get_links_for_keys_no_matches(self, link_repo) -> None:
        assert link_repo.get_links_for_keys(["nonexistent"]) == []

    def test_get_links_for_keys_duplicates_returned_once(self, link_repo) -> None:
        link_repo.upsert("mem_a", "mem_x")
        results = link_repo.get_links_for_keys(["mem_a", "mem_a"])
        assert len(results) == 1  # single source_key, single link


class TestMemoryLinkRepositoryEdgeCases:
    """Boundary conditions."""

    def test_upsert_empty_keys(self, link_repo) -> None:
        """Empty strings are valid keys; no crash expected."""
        link_repo.upsert("", "", "semantic")
        links = link_repo.get_links("")
        assert len(links) == 1

    def test_upsert_long_keys(self, link_repo) -> None:
        long_key = "x" * 500
        link_repo.upsert(long_key, "mem_y")
        links = link_repo.get_links(long_key)
        assert len(links) == 1
        assert links[0].target_key == "mem_y"
