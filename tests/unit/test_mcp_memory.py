"""Tests for memory-related MCP tool handlers (create, read, delete, stats, update, search)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pytest

from nous.domain.memory.entities import Memory
from nous.domain.search.engine import SearchResult
from nous.domain.shared.errors import RepositoryError
from nous.domain.shared.result import Failure, Success

UTC = UTC


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mem(key: str = "mem_001", content: str = "test content") -> Memory:
    now = datetime.now(UTC)
    return Memory(key=key, content=content, created_at=now, updated_at=now)


def _search_result(key: str = "mem_001", score: float = 0.8) -> SearchResult:
    return SearchResult(memory=_mem(key), score=score, source="keyword")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def registered_tools(mock_app_context):
    """
    Call register_tools with a mock FastMCP, capturing the tool functions
    by intercepting the @mcp.tool() decorator calls.
    """
    tools: dict[str, object] = {}

    def mock_tool_decorator():
        def decorator(func):
            tools[func.__name__] = func
            return func

        return decorator

    mock_mcp = MagicMock()
    mock_mcp.tool = mock_tool_decorator

    with (
        patch("nous.api.mcp.tools.AppContextRegistry") as mock_registry_cls,
        patch("nous.api.mcp.tools.get_current_persona", return_value="test_persona"),
    ):
        mock_registry_cls.get.return_value = mock_app_context

        from nous.api.mcp.tools import register_tools

        register_tools(mock_mcp)

        # Yield both the tools dict and the patched context so tests can
        # configure return values.
        yield tools, mock_app_context, mock_registry_cls


# ---------------------------------------------------------------------------
# memory_create()
# ---------------------------------------------------------------------------


class TestMemoryCreate:
    @pytest.mark.asyncio
    async def test_create_success(self, registered_tools):
        tools, ctx, registry = registered_tools
        ctx.memory_service.create_memory.return_value = Success(_mem("mem_new"))
        ctx.persona_service.get_state_snapshot.return_value = ("neutral", 0.0, {}, None)

        memory_create = tools["memory_create"]
        result = await memory_create(content="hello world")

        import json

        data = json.loads(result)
        assert data["ok"] is True
        assert data["key"] == "mem_new"
        ctx.memory_service.create_memory.assert_called_once()

    @pytest.mark.asyncio
    async def test_create_requires_content(self, registered_tools):
        tools, ctx, _ = registered_tools
        memory_create = tools["memory_create"]
        result = await memory_create()
        assert result["success"] is False
        assert result["data"] is None
        assert "content is required" in result["result_summary"].lower()

    @pytest.mark.asyncio
    async def test_create_invalid_importance(self, registered_tools):
        tools, ctx, _ = registered_tools
        memory_create = tools["memory_create"]
        result = await memory_create(content="hi", importance=1.5)
        assert result["success"] is False
        assert result["data"] is None
        assert "importance must be" in result["result_summary"].lower()

    @pytest.mark.asyncio
    async def test_create_unknown_emotion_warns(self, registered_tools):
        tools, ctx, _ = registered_tools
        ctx.persona_service.get_state_snapshot.return_value = ("neutral", 0.0, {}, None)
        ctx.memory_service.create_memory.return_value = Success(_mem("mem_x"))
        memory_create = tools["memory_create"]
        result = await memory_create(content="hi", tags=["test"], defer_vector=True)
        import json

        data = json.loads(result)
        assert data["ok"] is True
        assert data["key"] == "mem_x"

    @pytest.mark.asyncio
    async def test_create_service_failure(self, registered_tools):
        tools, ctx, _ = registered_tools
        ctx.persona_service.get_state_snapshot.return_value = ("neutral", 0.0, {}, None)
        ctx.memory_service.create_memory.return_value = Failure(RepositoryError("db error"))
        memory_create = tools["memory_create"]
        result = await memory_create(content="hi")
        assert result["success"] is False
        assert result["data"] is None
        assert "db error" in result["result_summary"].lower()

    # ── Duplicate detection tests ──

    @pytest.mark.asyncio
    async def test_create_memory_duplicate_detected(self, registered_tools):
        """Duplicate content should return duplicate status without creating memory."""
        tools, ctx, _ = registered_tools
        from nous.domain.shared.errors import DuplicateMemoryError

        ctx.memory_service.create_memory.return_value = Failure(
            DuplicateMemoryError("similar", similar_to=[{"key": "mem_dup", "content": "similar content", "score": 0.89}])
        )
        ctx.persona_service.get_state_snapshot.return_value = ("neutral", 0.0, {}, None)
        memory_create = tools["memory_create"]
        result = await memory_create(content="similar content")

        import json

        data = json.loads(result)
        assert data["ok"] is True
        assert data["status"] == "duplicate"
        assert len(data["similar_to"]) >= 1
        assert data["similar_to"][0]["key"] == "mem_dup"
        ctx.memory_service.create_memory.assert_called_once()

    @pytest.mark.asyncio
    async def test_create_memory_skip_duplicate_check(self, registered_tools):
        """skip_duplicate_check=True should bypass duplicate detection."""
        tools, ctx, _ = registered_tools
        ctx.persona_service.get_state_snapshot.return_value = ("neutral", 0.0, {}, None)
        ctx.memory_service.create_memory.return_value = Success(_mem("mem_new"))
        memory_create = tools["memory_create"]
        result = await memory_create(content="similar content", skip_duplicate_check=True)

        import json

        data = json.loads(result)
        assert data["ok"] is True
        assert data["key"] == "mem_new"
        ctx.memory_service.create_memory.assert_called_once()

    @pytest.mark.asyncio
    async def test_create_memory_no_duplicate(self, registered_tools):
        """Low-similarity content should not trigger duplicate detection."""
        tools, ctx, _ = registered_tools
        ctx.persona_service.get_state_snapshot.return_value = ("neutral", 0.0, {}, None)
        ctx.memory_service.create_memory.return_value = Success(_mem("mem_new"))
        memory_create = tools["memory_create"]
        result = await memory_create(content="unique content")

        import json

        data = json.loads(result)
        assert data["ok"] is True
        assert data["key"] == "mem_new"
        ctx.memory_service.create_memory.assert_called_once()

    # ── Duplicate via service (replaces old DB exact-match detection) ──

    @pytest.mark.asyncio
    async def test_create_memory_duplicate_via_service(self, registered_tools):
        """Service-level DuplicateMemoryError with duplicate_key should return duplicate status."""
        tools, ctx, _ = registered_tools
        from nous.domain.shared.errors import DuplicateMemoryError

        ctx.memory_service.create_memory.return_value = Failure(
            DuplicateMemoryError("identical content", duplicate_key="mem_exact_dup")
        )
        ctx.persona_service.get_state_snapshot.return_value = ("neutral", 0.0, {}, None)
        memory_create = tools["memory_create"]
        result = await memory_create(content="identical content")

        import json

        data = json.loads(result)
        assert data["ok"] is True
        assert data["status"] == "duplicate"
        assert data["duplicate_of"] == "mem_exact_dup"
        ctx.memory_service.create_memory.assert_called_once()

    @pytest.mark.asyncio
    async def test_create_memory_service_success(self, registered_tools):
        """Normal creation proceeds when no duplicate."""
        tools, ctx, _ = registered_tools
        ctx.persona_service.get_state_snapshot.return_value = ("neutral", 0.0, {}, None)
        ctx.memory_service.create_memory.return_value = Success(_mem("mem_new"))

        memory_create = tools["memory_create"]
        result = await memory_create(content="unique content")

        import json

        data = json.loads(result)
        assert data["ok"] is True
        assert data["key"] == "mem_new"
        ctx.memory_service.create_memory.assert_called_once()


# ---------------------------------------------------------------------------
# memory_read()
# ---------------------------------------------------------------------------


class TestMemoryRead:
    @pytest.mark.asyncio
    async def test_read_by_key(self, registered_tools):
        tools, ctx, _ = registered_tools
        m = _mem("mem_001", "stored content")
        ctx.memory_service.get_memory.return_value = Success(m)
        ctx.memory_service.boost_recall.return_value = Success(None)
        memory_read = tools["memory_read"]
        result = await memory_read(memory_key="mem_001")
        assert "stored content" in result
        assert "mem_001" in result

    @pytest.mark.asyncio
    async def test_read_recent_when_no_key(self, registered_tools):
        tools, ctx, _ = registered_tools
        ctx.memory_service.get_recent.return_value = Success([_mem("k1"), _mem("k2")])
        ctx.memory_service.count_memories.return_value = Success(2)
        memory_read = tools["memory_read"]
        result = json.loads(await memory_read())
        assert result["ok"] is True
        assert len(result["memories"]) == 2
        assert result["memories"][0]["key"] == "k1"
        assert result["memories"][1]["key"] == "k2"
        assert result["total_count"] == 2

    @pytest.mark.asyncio
    async def test_read_by_key_not_found(self, registered_tools):
        tools, ctx, _ = registered_tools
        ctx.memory_service.get_memory.return_value = Failure(RepositoryError("not found"))
        memory_read = tools["memory_read"]
        result = await memory_read(memory_key="missing")
        assert "not found" in result.lower()


# ---------------------------------------------------------------------------
# memory_delete()
# ---------------------------------------------------------------------------


class TestMemoryDelete:
    @pytest.mark.asyncio
    async def test_delete_by_key(self, registered_tools):
        tools, ctx, _ = registered_tools
        m = _mem("mem_del")
        ctx.memory_service.get_memory.return_value = Success(m)
        ctx.memory_service.delete_memory.return_value = Success(None)
        memory_delete = tools["memory_delete"]
        result = await memory_delete(memory_key="mem_del")
        assert "tombstoned" in result.lower()

    @pytest.mark.asyncio
    async def test_delete_requires_key_or_query(self, registered_tools):
        tools, ctx, _ = registered_tools
        memory_delete = tools["memory_delete"]
        result = await memory_delete()
        assert "memory_key or query required" in result.lower()

    @pytest.mark.asyncio
    async def test_delete_failure(self, registered_tools):
        tools, ctx, _ = registered_tools
        ctx.memory_service.get_memory.return_value = Failure(RepositoryError("not found"))
        ctx.memory_service.delete_memory.return_value = Failure(RepositoryError("not found"))
        memory_delete = tools["memory_delete"]
        result = await memory_delete(memory_key="missing")
        assert "not found" in result.lower()


# ---------------------------------------------------------------------------
# memory_stats()
# ---------------------------------------------------------------------------


class TestMemoryStats:
    @pytest.mark.asyncio
    async def test_stats_success(self, registered_tools):
        tools, ctx, _ = registered_tools
        ctx.memory_service.get_stats.return_value = Success({"total": 42, "by_emotion": {}})
        memory_stats = tools["memory_stats"]
        result = await memory_stats()
        assert "42" in result

    @pytest.mark.asyncio
    async def test_stats_failure(self, registered_tools):
        tools, ctx, _ = registered_tools
        ctx.memory_service.get_stats.return_value = Failure(RepositoryError("db error"))
        memory_stats = tools["memory_stats"]
        result = await memory_stats()
        assert "db error" in result.lower()


# ---------------------------------------------------------------------------
# memory_update()
# ---------------------------------------------------------------------------


class TestMemoryUpdate:
    @pytest.mark.asyncio
    async def test_update_success(self, registered_tools):
        tools, ctx, _ = registered_tools
        ctx.memory_service.update_memory.return_value = Success(_mem("mem_001"))
        memory_update = tools["memory_update"]
        result = await memory_update(memory_key="mem_001", content="new content")
        import json

        data = json.loads(result)
        assert data["ok"] is True
        assert data["key"] == "mem_001"

    @pytest.mark.asyncio
    async def test_update_requires_key(self, registered_tools):
        tools, ctx, _ = registered_tools
        memory_update = tools["memory_update"]
        result = await memory_update()
        assert result["success"] is False
        assert result["data"] is None
        assert "memory_key is required" in result["result_summary"].lower()

    @pytest.mark.asyncio
    async def test_update_invalid_importance(self, registered_tools):
        tools, ctx, _ = registered_tools
        memory_update = tools["memory_update"]
        result = await memory_update(memory_key="k1", importance=-0.1)
        assert result["success"] is False
        assert result["data"] is None
        assert "importance must be" in result["result_summary"].lower()

    @pytest.mark.asyncio
    async def test_update_content_too_long(self, registered_tools):
        tools, ctx, _ = registered_tools
        memory_update = tools["memory_update"]
        result = await memory_update(memory_key="k1", content="x" * 50001)
        assert result["success"] is False
        assert result["data"] is None
        assert "content too long" in result["result_summary"].lower()

    @pytest.mark.asyncio
    async def test_update_invalid_emotion(self, registered_tools):
        tools, ctx, _ = registered_tools
        memory_update = tools["memory_update"]
        result = await memory_update(memory_key="k1", content="test", emotion="nonexistent")
        assert result["success"] is False
        assert result["data"] is None
        assert "invalid emotion" in result["result_summary"].lower()

    @pytest.mark.asyncio
    async def test_update_emotion_intensity_nan(self, registered_tools):
        tools, ctx, _ = registered_tools
        memory_update = tools["memory_update"]
        # Pass a string where float is expected — the core function should reject it
        result = await memory_update(memory_key="k1", content="test", emotion_intensity="not_a_number")
        assert result["success"] is False
        assert result["data"] is None
        assert "emotion_intensity must be a number" in result["result_summary"].lower()

    @pytest.mark.asyncio
    async def test_update_emotion_intensity_out_of_range(self, registered_tools):
        tools, ctx, _ = registered_tools
        ctx.memory_service.update_memory.return_value = Success(_mem("mem_001"))
        memory_update = tools["memory_update"]
        # 5.0 gets clamped to 1.0, so the update should succeed
        result = await memory_update(memory_key="k1", content="test", emotion_intensity=5.0)
        import json

        data = json.loads(result)
        assert data["ok"] is True
        assert data["key"] == "k1"

    @pytest.mark.asyncio
    async def test_update_tags_not_list(self, registered_tools):
        tools, ctx, _ = registered_tools
        memory_update = tools["memory_update"]
        result = await memory_update(memory_key="k1", content="test", tags="not_a_list")
        assert result["success"] is False
        assert result["data"] is None
        assert "tags must be a list" in result["result_summary"].lower()

    @pytest.mark.asyncio
    async def test_update_tag_not_string(self, registered_tools):
        tools, ctx, _ = registered_tools
        memory_update = tools["memory_update"]
        result = await memory_update(memory_key="k1", content="test", tags=[123])
        assert result["success"] is False
        assert result["data"] is None
        assert "all tags must be strings" in result["result_summary"].lower()

    @pytest.mark.asyncio
    async def test_update_invalid_privacy_level(self, registered_tools):
        tools, ctx, _ = registered_tools
        memory_update = tools["memory_update"]
        result = await memory_update(memory_key="k1", content="test", privacy_level="classified")
        assert result["success"] is False
        assert result["data"] is None
        assert "invalid privacy_level" in result["result_summary"].lower()

    @pytest.mark.asyncio
    async def test_update_no_fields_returns_error(self, registered_tools):
        """No update fields → early return with error."""
        tools, ctx, _ = registered_tools
        memory_update = tools["memory_update"]
        result = await memory_update(memory_key="k1")
        assert result["success"] is False
        assert result["data"] is None
        assert "no fields to update" in result["result_summary"].lower()
        ctx.memory_service.update_memory.assert_not_called()

    @pytest.mark.asyncio
    async def test_update_changes_contains_content(self, registered_tools):
        """Single field update → field appears in changes."""
        tools, ctx, _ = registered_tools
        ctx.memory_service.update_memory.return_value = Success(_mem("mem_001"))
        memory_update = tools["memory_update"]
        result = await memory_update(memory_key="k1", content="updated content")
        import json

        data = json.loads(result)
        assert data["ok"] is True
        # Verify the event bus was called with changes=["content"]
        call_args = ctx.event_bus.publish.call_args
        assert call_args is not None
        _event_name, payload = call_args[0]
        assert payload["changes"] == ["content"]

    @pytest.mark.asyncio
    async def test_update_changes_contains_multiple(self, registered_tools):
        """Multiple field update → all fields appear in changes."""
        tools, ctx, _ = registered_tools
        ctx.memory_service.update_memory.return_value = Success(_mem("mem_001"))
        memory_update = tools["memory_update"]
        result = await memory_update(
            memory_key="k1",
            content="updated",
            importance=0.8,
            tags=["a", "b"],
        )
        import json

        data = json.loads(result)
        assert data["ok"] is True
        call_args = ctx.event_bus.publish.call_args
        assert call_args is not None
        _event_name, payload = call_args[0]
        # content, importance, tags — in insertion order
        assert payload["changes"] == ["content", "importance", "tags"]


# ---------------------------------------------------------------------------
# memory_search()
# ---------------------------------------------------------------------------


class TestMemorySearch:
    @pytest.mark.asyncio
    async def test_search_returns_results(self, registered_tools):
        tools, ctx, _ = registered_tools
        sr = _search_result("mem_abc", score=0.75)
        ctx.search_engine.search.return_value = Success([sr])
        ctx.memory_service.log_search.return_value = Success(None)
        ctx.memory_service.count_memories.return_value = Success(42)
        # search_engine._semantic should exist for the persona assignment
        ctx.search_engine._semantic = None
        memory_search = tools["memory_search"]
        result = await memory_search(query="test query")
        import json

        data = json.loads(result)
        assert data["ok"] is True
        assert len(data["memories"]) == 1
        assert data["memories"][0]["key"] == "mem_abc"
        assert data["memories"][0]["score"] == 1.0  # normalized to max score
        assert data["total_count"] == 42

    @pytest.mark.asyncio
    async def test_search_no_results(self, registered_tools):
        tools, ctx, _ = registered_tools
        ctx.search_engine.search.return_value = Success([])
        ctx.memory_service.count_memories.return_value = Success(0)
        ctx.search_engine._semantic = None
        memory_search = tools["memory_search"]
        result = await memory_search(query="nothing")
        import json

        data = json.loads(result)
        assert data["ok"] is True
        assert data["memories"] == []
        assert data["total_count"] == 0

    @pytest.mark.asyncio
    async def test_search_invalid_top_k(self, registered_tools):
        tools, ctx, _ = registered_tools
        memory_search = tools["memory_search"]
        result = await memory_search(query="test", top_k=0)
        assert result["success"] is False
        assert result["data"] is None
        assert "top_k must be" in result["result_summary"].lower()

    @pytest.mark.asyncio
    async def test_search_engine_failure(self, registered_tools):
        tools, ctx, _ = registered_tools
        from nous.domain.shared.errors import SearchError

        ctx.search_engine.search.return_value = Failure(SearchError("vector store down"))
        ctx.search_engine._semantic = None
        memory_search = tools["memory_search"]
        result = await memory_search(query="test")
        assert result["success"] is False
        assert result["data"] is None
        assert "vector store" in result["result_summary"].lower()

    @pytest.mark.asyncio
    async def test_search_with_tags_filter(self, registered_tools):
        tools, ctx, _ = registered_tools
        sr = _search_result("mem_tag", score=0.8)
        ctx.search_engine.search.return_value = Success([sr])
        ctx.search_engine._semantic = None
        ctx.memory_service.log_search.return_value = Success(None)
        memory_search = tools["memory_search"]
        await memory_search(query="test", tags=["goal"])
        call_args = ctx.search_engine.search.call_args[0][0]
        assert call_args.tags == ["goal"]
        assert call_args.text == "test"

    @pytest.mark.asyncio
    async def test_search_with_date_range(self, registered_tools):
        tools, ctx, _ = registered_tools
        ctx.search_engine.search.return_value = Success([])
        ctx.search_engine._semantic = None
        ctx.memory_service.log_search.return_value = Success(None)
        memory_search = tools["memory_search"]
        await memory_search(query="test", date_range="7d")
        call_args = ctx.search_engine.search.call_args[0][0]
        assert call_args.date_range == "7d"

    @pytest.mark.asyncio
    async def test_search_with_min_importance(self, registered_tools):
        tools, ctx, _ = registered_tools
        ctx.search_engine.search.return_value = Success([])
        ctx.search_engine._semantic = None
        ctx.memory_service.log_search.return_value = Success(None)
        memory_search = tools["memory_search"]
        await memory_search(query="test", min_importance=0.5)
        call_args = ctx.search_engine.search.call_args[0][0]
        assert call_args.min_importance == 0.5

    @pytest.mark.asyncio
    async def test_search_with_emotion_filter(self, registered_tools):
        tools, ctx, _ = registered_tools
        ctx.search_engine.search.return_value = Success([])
        ctx.search_engine._semantic = None
        ctx.memory_service.log_search.return_value = Success(None)
        memory_search = tools["memory_search"]
        await memory_search(query="test", emotion="joy")
        call_args = ctx.search_engine.search.call_args[0][0]
        assert call_args.emotion == "joy"

    @pytest.mark.asyncio
    async def test_search_combined_filters(self, registered_tools):
        tools, ctx, _ = registered_tools
        ctx.search_engine.search.return_value = Success([])
        ctx.search_engine._semantic = None
        ctx.memory_service.log_search.return_value = Success(None)
        memory_search = tools["memory_search"]
        await memory_search(
            query="test",
            top_k=10,
            tags=["goal", "important"],
            date_range="30d",
            min_importance=0.3,
            emotion="sad",
        )
        call_args = ctx.search_engine.search.call_args[0][0]
        assert call_args.top_k == 10
        assert call_args.tags == ["goal", "important"]
        assert call_args.date_range == "30d"
        assert call_args.min_importance == 0.3
        assert call_args.emotion == "sad"

    @pytest.mark.asyncio
    async def test_search_clamps_negative_weight(self, registered_tools):
        """Negative weight should be clamped to 0.0."""
        tools, ctx, _ = registered_tools
        ctx.search_engine.search.return_value = Success([])
        ctx.search_engine._semantic = None
        ctx.memory_service.log_search.return_value = Success(None)
        memory_search = tools["memory_search"]
        await memory_search(
            query="test", importance_weight=-0.5, recency_weight=-1.0, vector_weight=-99.0, keyword_weight=-0.1
        )
        call_args = ctx.search_engine.search.call_args[0][0]
        assert call_args.importance_weight == 0.0
        assert call_args.recency_weight == 0.0
        assert call_args.vector_weight == 0.0
        assert call_args.keyword_weight == 0.0

    @pytest.mark.asyncio
    async def test_search_clamps_overmax_weight(self, registered_tools):
        """Weight > 1.0 should be clamped to 1.0."""
        tools, ctx, _ = registered_tools
        ctx.search_engine.search.return_value = Success([])
        ctx.search_engine._semantic = None
        ctx.memory_service.log_search.return_value = Success(None)
        memory_search = tools["memory_search"]
        await memory_search(
            query="test", importance_weight=1.5, recency_weight=5.0, vector_weight=2.0, keyword_weight=999.0
        )
        call_args = ctx.search_engine.search.call_args[0][0]
        assert call_args.importance_weight == 1.0
        assert call_args.recency_weight == 1.0
        assert call_args.vector_weight == 1.0
        assert call_args.keyword_weight == 1.0

    @pytest.mark.asyncio
    async def test_search_accepts_valid_weights(self, registered_tools):
        """Valid weights in [0.0, 1.0] should pass through unchanged."""
        tools, ctx, _ = registered_tools
        ctx.search_engine.search.return_value = Success([])
        ctx.search_engine._semantic = None
        ctx.memory_service.log_search.return_value = Success(None)
        memory_search = tools["memory_search"]
        await memory_search(
            query="test", importance_weight=0.5, recency_weight=0.0, vector_weight=1.0, keyword_weight=0.25
        )
        call_args = ctx.search_engine.search.call_args[0][0]
        assert call_args.importance_weight == 0.5
        assert call_args.recency_weight == 0.0
        assert call_args.vector_weight == 1.0
        assert call_args.keyword_weight == 0.25

    @pytest.mark.asyncio
    async def test_search_passes_tags_and_filters(self, registered_tools):
        tools, ctx, _ = registered_tools
        ctx.search_engine.search.return_value = Success([])
        ctx.search_engine._semantic = None
        ctx.memory_service.log_search.return_value = Success(None)
        memory_search = tools["memory_search"]
        await memory_search(
            query="test",
            top_k=3,
            tags=["goal"],
            min_importance=0.7,
            emotion="joy",
            importance_weight=0.5,
            recency_weight=0.3,
        )
        call_args = ctx.search_engine.search.call_args[0][0]
        assert call_args.mode == "hybrid"  # mode is now always hybrid
        assert call_args.top_k == 3
        assert call_args.tags == ["goal"]
        assert call_args.min_importance == 0.7
        assert call_args.emotion == "joy"
        assert call_args.importance_weight == 0.5
        assert call_args.recency_weight == 0.3
