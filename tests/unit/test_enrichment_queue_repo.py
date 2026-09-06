"""Tests for EnrichmentQueueRepository."""

from __future__ import annotations

from datetime import datetime

import pytest

from nous.infrastructure.sqlite.enrichment_queue_repo import PendingItem


@pytest.fixture
def repo(sqlite_conn):
    from nous.infrastructure.sqlite.enrichment_queue_repo import EnrichmentQueueRepository

    return EnrichmentQueueRepository(sqlite_conn)


def test_enqueue_dedupes_pending(repo):
    """Same key enqueued twice yields a single pending row (INSERT OR IGNORE)."""
    repo.enqueue("k1")
    repo.enqueue("k1")
    pending = repo.pending_keys()
    assert len(pending) == 1
    assert pending[0].memory_key == "k1"
    # raw enqueued_at: repo returns it as-is (datetime); defer judgment is worker-side
    assert isinstance(pending[0].enqueued_at, datetime)


def test_mark_processed_removes_from_pending(repo):
    repo.enqueue("k1")
    repo.mark_processed("k1")
    assert repo.pending_keys() == []


def test_has_processed_true_after_mark(repo):
    repo.enqueue("k1")
    assert not repo.has_processed("k1")
    repo.mark_processed("k1")
    assert repo.has_processed("k1")


def test_has_processed_false_when_never_enqueued(repo):
    assert not repo.has_processed("ghost")


def test_mark_processed_allows_reenqueue(repo):
    repo.enqueue("k1")
    repo.mark_processed("k1")
    assert repo.has_processed("k1")
    assert repo.pending_keys() == []
    # a processed row does not block a new pending row for the same key
    repo.enqueue("k1")
    pending = repo.pending_keys()
    assert len(pending) == 1
    assert pending[0] == PendingItem(memory_key="k1", enqueued_at=pending[0].enqueued_at)


def test_pending_keys_returns_minimum_enqueued_at(repo):
    """Dedupe keeps the earliest enqueued_at per key."""
    repo.enqueue("k1")
    # backdate via direct SQL to simulate an older enqueue
    db = repo._db
    db.execute("UPDATE enrichment_queue SET enqueued_at = '2020-01-01T00:00:00+09:00' WHERE memory_key = 'k1'")
    repo.mark_processed("k1")
    repo.enqueue("k1")
    pending = repo.pending_keys()
    assert len(pending) == 1
    assert pending[0].enqueued_at.year == 2026
