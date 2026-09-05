"""Oja-normalized Hebbian links (F1/T3) tests.

``weight = MIN(1.0, MAX(0.5, w + η·c − η·w²·c))`` の収束特性。
"""

from __future__ import annotations

import pytest

from nous.infrastructure.sqlite.connection import SQLiteConnection
from nous.infrastructure.sqlite.entity_repo import SQLiteEntityRepository


@pytest.fixture()
def entity_repo(tmp_path):
    conn = SQLiteConnection(data_dir=str(tmp_path), persona="test_oja")
    conn.initialize_schema()
    yield SQLiteEntityRepository(conn)
    conn.close()


def _row(entity_repo: SQLiteEntityRepository, src: str = "a", dst: str = "b"):
    return entity_repo._db.execute(
        "SELECT weight, co_activation_count, last_activated FROM memory_links WHERE source_key = ? AND target_key = ?",
        (src, dst),
    ).fetchone()


class TestOjaLinks:
    def test_insert_starts_at_base_plus_strength(self, entity_repo) -> None:
        entity_repo.upsert_link("a", "b", "semantic", strength=0.1)
        row = _row(entity_repo)
        assert row["weight"] == pytest.approx(0.6)
        assert row["co_activation_count"] == 1
        assert row["last_activated"] is not None

    def test_repeated_coact_converges_without_pinning(self, entity_repo) -> None:
        """反復 coact で単調収束し、1.0 に張り付かない"""
        prev = 0.0
        for _ in range(300):
            entity_repo.upsert_link("a", "b", "semantic", strength=0.1)
            w = _row(entity_repo)["weight"]
            assert w <= 1.0
            assert w >= prev
            prev = w
        assert 0.9 < prev < 1.0

    def test_floor_never_breached(self, entity_repo) -> None:
        """floor 0.5 を割らない"""
        entity_repo.upsert_link("a", "b", "semantic", strength=0.0)
        assert _row(entity_repo)["weight"] == pytest.approx(0.5)
        for _ in range(50):
            entity_repo.upsert_link("a", "b", "semantic", strength=0.01)
        assert _row(entity_repo)["weight"] >= 0.5

    def test_count_and_timestamp_kept(self, entity_repo) -> None:
        """co_activation_count+1・last_activated=now・単文原子性は維持"""
        for _ in range(3):
            entity_repo.upsert_link("a", "b", "semantic", strength=0.1)
        row = _row(entity_repo)
        assert row["co_activation_count"] == 3
        assert row["last_activated"] is not None
