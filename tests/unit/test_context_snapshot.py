"""Unit tests for MemoryContextSnapshot."""

from __future__ import annotations

from unittest.mock import MagicMock

from nous.domain.search.context_snapshot import SNAPSHOT_BLOCK_NAME, MemoryContextSnapshot


def _make_memory(key: str, content: str, importance: float = 0.8, tags: list = None, emotion: str = "neutral"):
    m = MagicMock()
    m.key = key
    m.content = content
    m.importance = importance
    m.tags = tags or []
    m.emotion = emotion
    return m


def _make_repo(memories=None, index=None, block_content=None):
    repo = MagicMock()
    mems = memories or []
    repo.find_top_by_importance.return_value = MagicMock(is_ok=True, value=mems)
    repo.get_memory_index.return_value = MagicMock(
        is_ok=True,
        value=index or {"total": len(mems), "top_tags": [("food", 3), ("travel", 2)], "emotion_dist": [("joy", 5)]},
    )
    if block_content is not None:
        repo.get_block.return_value = MagicMock(is_ok=True, value={"content": block_content})
    else:
        repo.get_block.return_value = MagicMock(is_ok=True, value=None)
    repo.save_block.return_value = MagicMock(is_ok=True)
    return repo


class TestMemoryContextSnapshotBuild:
    def test_build_basic(self):
        mems = [_make_memory("k1", "I love coffee", tags=["food"])]
        repo = _make_repo(memories=mems)
        snap = MemoryContextSnapshot.build(repo, top_n=5)
        assert snap.memory_count == 1
        assert len(snap.top_memories) == 1
        assert snap.top_memories[0]["snippet"] == "I love coffee"
        assert "food" in [t for t, _ in snap.top_tags]

    def test_snippet_truncated(self):
        long_content = "a" * 100
        mems = [_make_memory("k1", long_content)]
        repo = _make_repo(memories=mems)
        snap = MemoryContextSnapshot.build(repo, top_n=5)
        assert snap.top_memories[0]["snippet"].endswith("…")
        assert len(snap.top_memories[0]["snippet"]) <= 65

    def test_build_empty(self):
        repo = _make_repo(memories=[])
        snap = MemoryContextSnapshot.build(repo, top_n=5)
        assert snap.memory_count == 0
        assert snap.top_memories == []


class TestMemoryContextSnapshotSerialization:
    def test_round_trip(self):
        snap = MemoryContextSnapshot(
            top_memories=[{"key": "k1", "snippet": "test", "importance": 0.9, "tags": ["a"], "emotion": "joy"}],
            top_tags=[("food", 3)],
            emotion_dist=[("joy", 5)],
            memory_count=42,
            built_at="2024-01-01T00:00:00",
        )
        json_str = snap.to_json()
        loaded = MemoryContextSnapshot.from_json(json_str)
        assert loaded.memory_count == 42
        assert loaded.top_tags == [("food", 3)]
        assert loaded.top_memories[0]["snippet"] == "test"


class TestMemoryContextSnapshotStaleness:
    def test_is_stale_when_threshold_exceeded(self):
        snap = MemoryContextSnapshot(memory_count=100)
        assert snap.is_stale(121, threshold=20) is True

    def test_not_stale_within_threshold(self):
        snap = MemoryContextSnapshot(memory_count=100)
        assert snap.is_stale(110, threshold=20) is False

    def test_stale_decrease(self):
        snap = MemoryContextSnapshot(memory_count=100)
        assert snap.is_stale(79, threshold=20) is True


class TestMemoryContextSnapshotStorage:
    def test_save(self):
        snap = MemoryContextSnapshot(memory_count=5, built_at="2024-01-01T00:00:00")
        repo = _make_repo()
        snap.save(repo)
        repo.save_block.assert_called_once()
        call_args = repo.save_block.call_args
        assert call_args.kwargs.get("block_name") == SNAPSHOT_BLOCK_NAME or call_args.args[0] == SNAPSHOT_BLOCK_NAME

    def test_load_none_when_missing(self):
        repo = _make_repo(block_content=None)
        result = MemoryContextSnapshot.load(repo)
        assert result is None

    def test_load_existing(self):
        snap = MemoryContextSnapshot(memory_count=10, built_at="2024-01-01T00:00:00")
        repo = _make_repo(block_content=snap.to_json())
        loaded = MemoryContextSnapshot.load(repo)
        assert loaded is not None
        assert loaded.memory_count == 10
