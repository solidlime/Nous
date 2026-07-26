"""Integration tests: decay ↔ search ranking.

Uses real SQLite database (``tmp_path`` + ``SQLiteConnection``) to verify
that decay states are reflected in search ranking via the
``ForgettingCurveRanker`` lookup from actual DB rows.
"""

from __future__ import annotations

import pytest

from nous.domain.memory.entities import Memory, MemoryStrength
from nous.domain.search.engine import SearchQuery, SearchResult
from nous.domain.search.ranker import ForgettingCurveRanker
from nous.domain.shared.time_utils import get_now
from nous.infrastructure.sqlite.connection import SQLiteConnection
from nous.infrastructure.sqlite.memory_repo import SQLiteMemoryRepository


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def conn(tmp_path):
    c = SQLiteConnection(str(tmp_path), "test_persona")
    c.initialize_schema()
    return c


@pytest.fixture
def repo(conn):
    return SQLiteMemoryRepository(conn)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_memory(key: str, content: str, **kwargs) -> Memory:
    now = get_now()
    return Memory(key=key, content=content, created_at=now, updated_at=now, **kwargs)


def _search(repo, conn, query_text: str):
    """Run keyword search then rank with ForgettingCurveRanker reading from DB."""
    raw = repo.search_keyword(query_text).unwrap()
    db = conn.get_memory_db()

    def lookup(key: str):
        row = db.execute(
            "SELECT strength, stability FROM memory_strength WHERE memory_key = ?",
            (key,),
        ).fetchone()
        if row is not None:
            return (row["strength"], row["stability"])
        return None

    ranker = ForgettingCurveRanker(lookup)
    results = [SearchResult(memory=m, score=s, source="keyword") for m, s in raw]
    return ranker.rank(results, SearchQuery(text=query_text))


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestDecaySearch:
    """Decay ↔ search integration."""

    async def test_decayed_memory_ranks_lower(self, repo, conn) -> None:
        """A memory with low strength should rank below a fresh memory."""
        repo.save(_make_memory("mem_fresh", "hello world fresh content"))
        repo.save(_make_memory("mem_decayed", "hello world old content"))

        # Manually decay old memory's strength via raw SQL.
        # Set stability=0 so ForgettingCurveRanker falls to strength-multiplier
        # branch instead of the FSRS recall-probability branch.
        db = conn.get_memory_db()
        db.execute(
            "UPDATE memory_strength SET strength = 0.1, stability = 0 WHERE memory_key = ?",
            ("mem_decayed",),
        )
        db.commit()

        ranked = _search(repo, conn, "hello")

        assert len(ranked) == 2
        assert ranked[0].memory.key == "mem_fresh", (
            f"Expected mem_fresh first, got {ranked[0].memory.key}"
        )
        assert ranked[1].memory.key == "mem_decayed", (
            f"Expected mem_decayed second, got {ranked[1].memory.key}"
        )
        # Fresh memory should have a higher score
        assert ranked[0].score > ranked[1].score, (
            f"Fresh mem score ({ranked[0].score}) should be > decayed ({ranked[1].score})"
        )

    async def test_strength_boost_after_recall(self, repo, conn) -> None:
        """Boosting a memory's strength (boost_on_recall) should improve its rank.

        Both memories start with low strength (0.2); mem_a is then boosted
        to 1.0 via boost_on_recall, so it should rank higher.
        """
        repo.save(_make_memory("mem_a", "unique content alpha"))
        repo.save(_make_memory("mem_b", "unique content beta"))

        # Set both to low strength + stability=0 so ranker uses strength multiplier
        db = conn.get_memory_db()
        db.execute(
            "UPDATE memory_strength SET strength = 0.2, stability = 0 WHERE memory_key = ?",
            ("mem_a",),
        )
        db.execute(
            "UPDATE memory_strength SET strength = 0.2, stability = 0 WHERE memory_key = ?",
            ("mem_b",),
        )
        db.commit()

        # Boost mem_a via the repo
        strength_a = repo.get_strength("mem_a").unwrap()
        assert strength_a is not None
        strength_a.boost_on_recall()  # sets strength=1.0, stability=min(0*1.5,365)=0→stays 0
        repo.save_strength(strength_a).unwrap()

        ranked = _search(repo, conn, "unique")

        # mem_a (boosted, strength=1.0) should rank above mem_b (strength=0.2)
        assert ranked[0].memory.key == "mem_a", (
            f"Expected boosted mem_a first, got {ranked[0].memory.key}"
        )
        # With stability=0, ForgettingCurveRanker does score * max(0.1, strength)
        # mem_a: score * 1.0, mem_b: score * 0.2 → mem_a should be ~5x higher
        ratio = ranked[0].score / ranked[1].score
        assert ratio > 2.0, (
            f"Boosted score ratio ({ratio}) should be >> 1: "
            f"mem_a={ranked[0].score:.4f}, mem_b={ranked[1].score:.4f}"
        )

    async def test_orphan_strength_does_not_break(self, repo, conn) -> None:
        """Orphan memory_strength rows must not crash search."""
        repo.save(_make_memory("mem_ok", "working memory content"))

        # Insert orphan records directly (no corresponding memories row).
        # Temporarily disable FK enforcement to bypass the constraint.
        db = conn.get_memory_db()
        db.execute("PRAGMA foreign_keys=OFF")
        db.execute(
            "INSERT INTO memory_strength (memory_key, strength) VALUES (?, ?)",
            ("orphan_search_001", 0.5),
        )
        db.execute(
            "INSERT INTO memory_strength (memory_key, strength) VALUES (?, ?)",
            ("orphan_search_002", 0.3),
        )
        db.execute("PRAGMA foreign_keys=ON")
        db.commit()

        # 1. Keyword search should still return only the real memory
        raw = repo.search_keyword("working").unwrap()
        assert len(raw) == 1
        assert raw[0][0].key == "mem_ok"

        # 2. save_strength with a non-existent key should not crash
        orphan = MemoryStrength(memory_key="orphan_no_parent")
        result = repo.save_strength(orphan)
        # FK violation → Failure, but not a crash (logged as warning)
        assert not result.is_ok
