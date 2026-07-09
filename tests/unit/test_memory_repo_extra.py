"""Additional unit tests for SQLiteMemoryRepository — targeting uncovered paths."""

from __future__ import annotations

from datetime import timedelta

import pytest

from nous.domain.memory.entities import Memory
from nous.domain.shared.time_utils import get_now
from nous.infrastructure.sqlite.connection import SQLiteConnection
from nous.infrastructure.sqlite.memory_repo import SQLiteMemoryRepository


@pytest.fixture
def sqlite_conn(tmp_path):
    conn = SQLiteConnection(data_dir=str(tmp_path), persona="test")
    conn.initialize_schema()
    yield conn
    conn.close()


@pytest.fixture
def repo(sqlite_conn):
    return SQLiteMemoryRepository(sqlite_conn)


def _make_memory(key: str = "memory_20250101120000", content: str = "test", **kwargs) -> Memory:
    now = get_now()
    return Memory(key=key, content=content, created_at=now, updated_at=now, **kwargs)


def _save_many(repo, count: int, prefix: str = "memory_202501010000") -> list[Memory]:
    memories = []
    for i in range(count):
        m = _make_memory(key=f"{prefix}{i:02d}", content=f"memory content {i}")
        repo.save(m)
        memories.append(m)
    return memories


class TestFindWithPagination:
    def test_basic_pagination(self, repo):
        _save_many(repo, 5)
        result = repo.find_with_pagination(page=1, per_page=2)
        assert result.is_ok
        memories, total = result.unwrap()
        assert total == 5
        assert len(memories) == 2

    def test_page_2(self, repo):
        _save_many(repo, 5)
        result = repo.find_with_pagination(page=2, per_page=2)
        assert result.is_ok
        memories, total = result.unwrap()
        assert total == 5
        assert len(memories) == 2

    def test_filter_by_tag(self, repo):
        m1 = _make_memory("memory_20250101000001", "tagged")
        m1.tags = ["food"]
        m2 = _make_memory("memory_20250101000002", "untagged")
        repo.save(m1)
        repo.save(m2)

        result = repo.find_with_pagination(tag="food")
        assert result.is_ok
        memories, total = result.unwrap()
        assert total == 1
        assert memories[0].content == "tagged"

    def test_filter_by_query(self, repo):
        repo.save(_make_memory("memory_20250101000001", "I love ramen"))
        repo.save(_make_memory("memory_20250101000002", "sushi is great"))

        result = repo.find_with_pagination(query="ramen")
        assert result.is_ok
        memories, total = result.unwrap()
        assert total == 1
        assert "ramen" in memories[0].content

    def test_sort_order_asc(self, repo):
        _save_many(repo, 3)
        result = repo.find_with_pagination(sort_order="asc")
        assert result.is_ok
        memories, _ = result.unwrap()
        assert len(memories) >= 1

    def test_empty_db(self, repo):
        result = repo.find_with_pagination()
        assert result.is_ok
        memories, total = result.unwrap()
        assert total == 0
        assert memories == []


class TestGetAllTags:
    def test_returns_empty_for_empty_db(self, repo):
        result = repo.get_all_tags()
        assert result.is_ok
        assert result.unwrap() == []

    def test_returns_sorted_unique_tags(self, repo):
        m1 = _make_memory("memory_20250101000001", "c1")
        m1.tags = ["b_tag", "a_tag"]
        m2 = _make_memory("memory_20250101000002", "c2")
        m2.tags = ["a_tag", "c_tag"]
        repo.save(m1)
        repo.save(m2)

        result = repo.get_all_tags()
        assert result.is_ok
        tags = result.unwrap()
        assert "a_tag" in tags
        assert "b_tag" in tags
        assert "c_tag" in tags
        assert tags == sorted(set(tags))  # sorted, unique


class TestConsumeMemory:
    def _tagged_memory(self, key: str, content: str) -> Memory:
        m = _make_memory(key=key, content=content)
        m.tags = ["speech_style"]
        return m

    def test_consume_memory_sets_last_consumed_at(self, repo):
        key = repo.save(_make_memory(key="mem_consume_1", content="test")).unwrap()
        result = repo.consume_memory(key)
        assert result.is_ok
        mem = repo.find_by_key(key).unwrap()
        assert mem is not None
        assert mem.last_consumed_at is not None

    def test_get_by_tags_excludes_consumed(self, repo):
        key1 = repo.save(self._tagged_memory("mem_consume_2", "古い状態")).unwrap()
        key2 = repo.save(self._tagged_memory("mem_consume_3", "新しい状態")).unwrap()
        repo.consume_memory(key2)
        results = repo.get_by_tags(["speech_style"], include_consumed=False).unwrap()
        assert len(results) == 1
        assert results[0].key == key1

    def test_get_by_tags_include_consumed(self, repo):
        key1 = repo.save(self._tagged_memory("mem_consume_4", "s1")).unwrap()
        repo.consume_memory(key1)
        results = repo.get_by_tags(["speech_style"], include_consumed=True).unwrap()
        assert len(results) == 1


class TestGetByTags:
    def test_returns_memories_matching_all_tags(self, repo):
        m1 = _make_memory("memory_20250101000001", "both tags")
        m1.tags = ["food", "japanese"]
        m2 = _make_memory("memory_20250101000002", "one tag only")
        m2.tags = ["food"]
        repo.save(m1)
        repo.save(m2)

        result = repo.get_by_tags(["food", "japanese"])
        assert result.is_ok
        memories = result.unwrap()
        assert len(memories) == 1
        assert memories[0].content == "both tags"

    def test_empty_tags_returns_empty(self, repo):
        repo.save(_make_memory())
        result = repo.get_by_tags([])
        assert result.is_ok
        assert result.unwrap() == []


class TestFindSmartRecent:
    def test_returns_memories(self, repo):
        _save_many(repo, 3)
        result = repo.find_smart_recent(limit=2)
        assert result.is_ok
        assert len(result.unwrap()) == 2

    def test_empty_db(self, repo):
        result = repo.find_smart_recent()
        assert result.is_ok
        assert result.unwrap() == []


class TestSearchKeyword:
    def test_multi_word_and_logic(self, repo):
        repo.save(_make_memory("memory_20250101000001", "tokyo ramen noodles delicious"))
        repo.save(_make_memory("memory_20250101000002", "tokyo sushi fresh"))
        repo.save(_make_memory("memory_20250101000003", "osaka ramen spicy"))

        # "tokyo ramen" should match only the first record (has both "tokyo" and "ramen")
        result = repo.search_keyword("tokyo ramen")
        assert result.is_ok
        memories = result.unwrap()
        assert len(memories) == 1
        assert "tokyo ramen noodles" in memories[0][0].content

    def test_empty_query_returns_empty(self, repo):
        repo.save(_make_memory())
        result = repo.search_keyword("")
        assert result.is_ok
        assert result.unwrap() == []

    def test_limit_respected(self, repo):
        for i in range(5):
            repo.save(_make_memory(f"memory_2025010100000{i}", f"keyword match {i}"))

        result = repo.search_keyword("keyword", limit=2)
        assert result.is_ok
        assert len(result.unwrap()) == 2


class TestMemoryVersions:
    def test_save_and_get_versions(self, repo):
        m = _make_memory()
        repo.save(m)

        save_result = repo.save_version(
            memory_key=m.key,
            version=1,
            content="original content",
            metadata={"source": "test"},
            changed_by="user",
            change_type="create",
        )
        assert save_result.is_ok

        get_result = repo.get_versions(m.key)
        assert get_result.is_ok
        versions = get_result.unwrap()
        assert len(versions) == 1
        assert versions[0]["content"] == "original content"
        assert versions[0]["change_type"] == "create"

    def test_get_specific_version(self, repo):
        m = _make_memory()
        repo.save(m)
        repo.save_version(m.key, 1, "v1 content", None, "user", "create")
        repo.save_version(m.key, 2, "v2 content", None, "user", "update")

        result = repo.get_version(m.key, 1)
        assert result.is_ok
        v = result.unwrap()
        assert v is not None
        assert v["content"] == "v1 content"

    def test_get_version_not_found(self, repo):
        m = _make_memory()
        repo.save(m)

        result = repo.get_version(m.key, 99)
        assert result.is_ok
        assert result.unwrap() is None

    def test_get_latest_version_number(self, repo):
        m = _make_memory()
        repo.save(m)

        # No versions yet -> 0
        result = repo.get_latest_version_number(m.key)
        assert result.is_ok
        assert result.unwrap() == 0

        repo.save_version(m.key, 1, "v1", None, "user", "create")
        repo.save_version(m.key, 2, "v2", None, "user", "update")

        result = repo.get_latest_version_number(m.key)
        assert result.is_ok
        assert result.unwrap() == 2

    def test_get_versions_empty(self, repo):
        m = _make_memory()
        repo.save(m)
        result = repo.get_versions(m.key)
        assert result.is_ok
        assert result.unwrap() == []


class TestLogAndSearchLog:
    def test_log_search(self, repo):
        result = repo.log_search("test query", "hybrid", 5)
        assert result.is_ok

    def test_get_recent_searches(self, repo):
        repo.log_search("query 1", "hybrid", 3)
        repo.log_search("query 2", "semantic", 1)

        result = repo.get_recent_searches(limit=5)
        assert result.is_ok
        searches = result.unwrap()
        assert len(searches) == 2

    def test_get_recent_searches_limit(self, repo):
        for i in range(5):
            repo.log_search(f"query {i}", "hybrid", i)

        result = repo.get_recent_searches(limit=3)
        assert result.is_ok
        assert len(result.unwrap()) == 3


class TestCountDecayedImportant:
    def test_returns_zero_with_no_decayed(self, repo):
        m = _make_memory(importance=0.9)
        repo.save(m)
        # Default strength is 1.0, not decayed
        result = repo.count_decayed_important(min_importance=0.7, max_strength=0.3)
        assert result.is_ok
        assert result.unwrap() == 0

    def test_counts_decayed_important_memory(self, repo, sqlite_conn):
        m = _make_memory(importance=0.9)
        repo.save(m)
        # Manually set strength to a decayed value
        sqlite_conn.get_memory_db().execute("UPDATE memory_strength SET strength = 0.1 WHERE memory_key = ?", (m.key,))
        sqlite_conn.get_memory_db().commit()

        result = repo.count_decayed_important(min_importance=0.7, max_strength=0.3)
        assert result.is_ok
        assert result.unwrap() == 1


class TestGetMemoryIndex:
    def test_empty_db(self, repo):
        result = repo.get_memory_index()
        assert result.is_ok
        index = result.unwrap()
        assert index["total"] == 0
        assert index["top_tags"] == []

    def test_with_memories(self, repo):
        m1 = _make_memory("memory_20250101000001", "First", importance=0.9)
        m1.tags = ["milestone", "important"]
        m1.emotion = "joy"
        m2 = _make_memory("memory_20250101000002", "Second", importance=0.6)
        m2.tags = ["milestone"]
        m2.emotion = "neutral"
        repo.save(m1)
        repo.save(m2)

        result = repo.get_memory_index()
        assert result.is_ok
        index = result.unwrap()
        assert index["total"] == 2
        assert index["high_importance_count"] == 1
        tag_names = [t[0] for t in index["top_tags"]]
        assert "milestone" in tag_names


class TestFindRelationshipHighlights:
    def test_empty_db(self, repo):
        result = repo.find_relationship_highlights()
        assert result.is_ok
        assert result.unwrap() == []

    def test_finds_relationship_memories(self, repo):
        m = _make_memory("memory_20250101000001", "Met a special person", importance=0.9)
        m.tags = ["milestone", "important_moment"]
        repo.save(m)

        result = repo.find_relationship_highlights()
        assert result.is_ok
        memories = result.unwrap()
        assert len(memories) == 1

    def test_low_importance_excluded(self, repo):
        m = _make_memory("memory_20250101000001", "casual meeting", importance=0.3)
        m.tags = ["milestone"]
        repo.save(m)

        result = repo.find_relationship_highlights()
        assert result.is_ok
        assert len(result.unwrap()) == 0


class TestDeleteNonexistentKey:
    def test_delete_nonexistent_succeeds_silently(self, repo):
        """Deleting a non-existent key should succeed (no error)."""
        result = repo.delete("memory_key_that_does_not_exist")
        assert result.is_ok


class TestUpdatePartialFields:
    def test_update_tags_field(self, repo):
        m = _make_memory()
        repo.save(m)

        result = repo.update(m.key, tags=["new_tag", "another"])
        assert result.is_ok
        updated = result.unwrap()
        assert "new_tag" in updated.tags
        assert "another" in updated.tags

    def test_update_related_keys_field(self, repo):
        m = _make_memory()
        repo.save(m)

        result = repo.update(m.key, related_keys=["mem_other_001"])
        assert result.is_ok
        assert "mem_other_001" in result.unwrap().related_keys

    def test_update_emotion_fields(self, repo):
        m = _make_memory()
        repo.save(m)

        result = repo.update(m.key, emotion="joy", emotion_intensity=0.9)
        assert result.is_ok
        updated = result.unwrap()
        assert updated.emotion == "joy"
        assert updated.emotion_intensity == 0.9


class TestGetAllStrengths:
    def test_returns_empty_for_no_records(self, repo):
        result = repo.get_all_strengths()
        assert result.is_ok
        assert result.unwrap() == []

    def test_returns_strength_after_save(self, repo):
        m = _make_memory()
        repo.save(m)
        # strength record auto-created on save

        result = repo.get_all_strengths()
        assert result.is_ok
        strengths = result.unwrap()
        assert len(strengths) == 1
        assert strengths[0].memory_key == m.key

    def test_multiple_strengths(self, repo):
        for i in range(3):
            repo.save(_make_memory(f"memory_2025010100000{i}", f"content {i}"))

        result = repo.get_all_strengths()
        assert result.is_ok
        assert len(result.unwrap()) == 3


# ---------------------------------------------------------------------------
# FTS5 full-text search
# ---------------------------------------------------------------------------


class TestFTS5Search:
    def test_fts_empty_query_returns_empty(self, repo):
        result = repo.search_fts("")
        assert result.is_ok
        assert result.unwrap() == []

    def test_fts_search_finds_content(self, repo):
        repo.save(_make_memory("mem1", "hello world this is a test"))
        repo.save(_make_memory("mem2", "goodbye world"))
        result = repo.search_fts("hello", top_k=10)
        assert result.is_ok
        results = result.unwrap()
        assert len(results) >= 1
        assert results[0][0].key == "mem1"

    def test_fts_search_respects_top_k(self, repo):
        repo.save(_make_memory("mem1", "alpha beta gamma"))
        repo.save(_make_memory("mem2", "alpha beta delta"))
        repo.save(_make_memory("mem3", "alpha beta epsilon"))
        result = repo.search_fts("alpha", top_k=2)
        assert result.is_ok
        assert len(result.unwrap()) == 2

    def test_fts_score_normalized(self, repo):
        repo.save(_make_memory("mem1", "hello world foo bar baz"))
        result = repo.search_fts("hello", top_k=10)
        assert result.is_ok
        results = result.unwrap()
        assert len(results) >= 1
        mem, score = results[0]
        assert 0.0 <= score <= 1.0
        assert mem.key == "mem1"

    def test_fts_excludes_tombstoned(self, repo):
        repo.save(_make_memory("mem1", "hello world active"))
        repo.save(_make_memory("mem2", "hello world tombstoned"))
        repo.tombstone("mem2")
        result = repo.search_fts("hello", top_k=10)
        assert result.is_ok
        keys = [m.key for m, _ in result.unwrap()]
        assert "mem1" in keys
        assert "mem2" not in keys

    def test_fts_and_trigger_sync_on_insert(self, repo):
        """FTS5 index should automatically sync with memories table via trigger."""
        repo.save(_make_memory("mem_trigger", "trigger test content"))
        result = repo.search_fts("trigger", top_k=10)
        assert result.is_ok
        assert len(result.unwrap()) >= 1
        assert result.unwrap()[0][0].key == "mem_trigger"

    def test_fts_and_trigger_sync_on_update(self, repo):
        """Updating content should be reflected in FTS5."""
        repo.save(_make_memory("mem_update", "original content"))
        repo.update("mem_update", content="updated content here")
        # Should find by new content
        result = repo.search_fts("updated", top_k=10)
        assert result.is_ok
        assert len(result.unwrap()) >= 1
        # Should NOT find by old content
        result = repo.search_fts("original", top_k=10)
        assert result.is_ok
        assert len(result.unwrap()) == 0

    def test_fts_and_trigger_sync_on_delete(self, repo):
        """Deleting a memory should remove it from FTS5 index."""
        repo.save(_make_memory("mem_del", "delete this content"))
        repo.delete("mem_del")
        result = repo.search_fts("delete", top_k=10)
        assert result.is_ok
        assert len(result.unwrap()) == 0

    def test_fts_sanitize_query_special_chars(self, repo):
        """FTS5 query sanitization should handle special characters."""
        repo.save(_make_memory("mem_safe", "safe content here"))
        # Special FTS5 chars (parentheses) should be handled safely
        result = repo.search_fts("safe (content)", top_k=10)
        assert result.is_ok
        assert len(result.unwrap()) >= 1

    def test_fts_sanitize_query_with_quotes(self, repo):
        """Terms with embedded quotes should be escaped correctly."""
        repo.save(_make_memory("mem_quote", 'say "hello" world'))
        result = repo.search_fts('"hello"', top_k=10)
        assert result.is_ok
        assert len(result.unwrap()) >= 1

    def test_fts_date_filter(self, repo):
        """FTS5 search should respect date range filtering."""
        now = get_now()
        repo.save(
            Memory(
                key="mem_old",
                content="old content hello",
                created_at=now - timedelta(days=30),
                updated_at=now - timedelta(days=30),
            )
        )
        repo.save(
            Memory(
                key="mem_new",
                content="new content hello",
                created_at=now,
                updated_at=now,
            )
        )
        # Filter to only recent memories
        result = repo.search_fts("hello", top_k=10, date_from=now - timedelta(days=1))
        assert result.is_ok
        keys = [m.key for m, _ in result.unwrap()]
        assert "mem_new" in keys
        assert "mem_old" not in keys
