"""Unit tests for application workers: RebuildWorker and CleanupWorker."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from nous.application.workers.cleanup_worker import CleanupWorker
from nous.application.workers.rebuild_worker import RebuildWorker
from nous.domain.memory.entities import Memory
from nous.domain.shared.errors import VectorStoreError
from nous.domain.shared.result import Failure, Success
from nous.domain.shared.time_utils import get_now


def _make_memory(key: str = "mem_001", content: str = "test") -> Memory:
    now = get_now()
    return Memory(key=key, content=content, created_at=now, updated_at=now)


def _make_context(memories=None, vs=None, find_all_fails=False):
    """Create a mock AppContext."""
    ctx = MagicMock()
    ctx.persona = "test"
    if find_all_fails:
        ctx.memory_repo.find_all.return_value = Failure(Exception("db error"))
    else:
        ctx.memory_repo.find_all.return_value = Success(memories or [])
    ctx.vector_store = vs
    return ctx


# ---------------------------------------------------------------------------
# RebuildWorker
# ---------------------------------------------------------------------------


class TestRebuildWorker:
    @pytest.mark.asyncio
    async def test_rebuild_fails_when_find_all_fails(self):
        ctx = _make_context(find_all_fails=True)
        worker = RebuildWorker(ctx)
        result = await worker.rebuild()
        assert not result.is_ok

    @pytest.mark.asyncio
    async def test_rebuild_fails_when_vector_store_is_none(self):
        ctx = _make_context(memories=[], vs=None)
        worker = RebuildWorker(ctx)
        result = await worker.rebuild()
        assert not result.is_ok
        assert isinstance(result.error, VectorStoreError)

    @pytest.mark.asyncio
    async def test_rebuild_empty_memories(self):
        vs = MagicMock()
        vs.upsert = AsyncMock(return_value=Success(None))
        ctx = _make_context(memories=[], vs=vs)
        worker = RebuildWorker(ctx)
        result = await worker.rebuild()
        assert result.is_ok
        assert result.unwrap() == 0

    @pytest.mark.asyncio
    async def test_rebuild_upserts_all_memories(self):
        vs = MagicMock()
        vs.upsert = AsyncMock(return_value=Success(None))
        memories = [_make_memory(f"mem_{i:03d}", f"content {i}") for i in range(3)]
        ctx = _make_context(memories=memories, vs=vs)

        worker = RebuildWorker(ctx)
        result = await worker.rebuild()
        assert result.is_ok
        assert result.unwrap() == 3
        assert vs.upsert.call_count == 3

    @pytest.mark.asyncio
    async def test_rebuild_skips_failed_upserts(self):
        vs = MagicMock()
        vs.upsert = AsyncMock()
        vs.upsert.side_effect = [
            Success(None),
            Failure(VectorStoreError("upsert error")),
            Success(None),
        ]
        memories = [_make_memory(f"mem_{i:03d}") for i in range(3)]
        ctx = _make_context(memories=memories, vs=vs)

        worker = RebuildWorker(ctx)
        result = await worker.rebuild()
        assert result.is_ok
        assert result.unwrap() == 2  # Only 2 successful upserts

    @pytest.mark.asyncio
    async def test_rebuild_passes_correct_metadata(self):
        vs = MagicMock()
        vs.upsert = AsyncMock(return_value=Success(None))
        m = _make_memory("mem_001", "hello world")
        m.importance = 0.8
        m.emotion = "joy"
        m.tags = ["tag1", "tag2"]
        ctx = _make_context(memories=[m], vs=vs)

        await RebuildWorker(ctx).rebuild()

        call_args = vs.upsert.call_args
        assert call_args[0][0] == "test"  # persona
        assert call_args[0][1] == "mem_001"  # key
        assert call_args[0][2] == "hello world"  # content
        metadata = call_args[0][3]
        assert metadata["importance"] == 0.8
        assert metadata["emotion"] == "joy"
        assert "tag1" in metadata["tags"]


# ---------------------------------------------------------------------------
# CleanupWorker
# ---------------------------------------------------------------------------


class TestCleanupWorker:
    def test_start_and_stop(self):
        ctx = _make_context(memories=[])
        worker = CleanupWorker(ctx, interval_seconds=9999)
        worker.start()
        assert worker._running is True
        assert worker._thread is not None
        worker.stop()
        assert worker._running is False

    def test_cleanup_cycle_skips_when_no_vector_store(self):
        """_cleanup_cycle should do nothing when vector_store is None."""
        ctx = _make_context(memories=[], vs=None)
        worker = CleanupWorker(ctx)
        # Should not raise
        worker._cleanup_cycle()
        ctx.memory_repo.find_all.assert_not_called()

    def test_cleanup_cycle_skips_when_find_all_fails(self):
        vs = AsyncMock()
        ctx = _make_context(find_all_fails=True, vs=vs)
        worker = CleanupWorker(ctx)
        worker._cleanup_cycle()
        # find_all was called but vs.search was not (early return)
        vs.search.assert_not_called()

    def test_cleanup_cycle_with_no_duplicates(self):
        vs = AsyncMock()
        # search returns results with score below threshold
        vs.search.return_value = Success([("mem_002", 0.5)])
        memories = [_make_memory("mem_001", "unique content")]
        ctx = _make_context(memories=memories, vs=vs)

        worker = CleanupWorker(ctx)
        worker._cleanup_cycle()
        vs.search.assert_called_once()

    def test_cleanup_cycle_detects_duplicate(self):
        vs = AsyncMock()
        # Return a near-duplicate with high score
        vs.search.return_value = Success([("mem_002", 0.99)])
        memories = [_make_memory("mem_001", "content")]
        ctx = _make_context(memories=memories, vs=vs)

        worker = CleanupWorker(ctx)
        worker._cleanup_cycle()
        # Should have searched for the memory
        vs.search.assert_called_once()

    def test_cleanup_cycle_skips_already_seen_keys(self):
        vs = AsyncMock()

        # mem_001 returns mem_002 as duplicate; then mem_002 is in seen_keys
        async def fake_search(persona, content, limit):
            if "first" in content:
                return Success([("mem_002", 0.99)])
            return Success([])

        vs.search.side_effect = fake_search
        memories = [
            _make_memory("mem_001", "first content"),
            _make_memory("mem_002", "second content"),
        ]
        ctx = _make_context(memories=memories, vs=vs)
        worker = CleanupWorker(ctx)
        worker._cleanup_cycle()

        # mem_002 was in seen_keys so second call wasn't made
        assert vs.search.call_count == 1

    def test_cleanup_cycle_handles_failed_search(self):
        vs = AsyncMock()
        vs.search.return_value = Failure(VectorStoreError("search error"))
        memories = [_make_memory("mem_001")]
        ctx = _make_context(memories=memories, vs=vs)

        worker = CleanupWorker(ctx)
        worker._cleanup_cycle()
        vs.search.assert_called_once()
