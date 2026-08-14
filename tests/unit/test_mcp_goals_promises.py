"""Tests for MCP tool handlers: goal_manage (self + interpersonal scope)."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pytest

from nous.domain.memory.entities import Memory
from nous.domain.shared.errors import RepositoryError
from nous.domain.shared.result import Failure, Success

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mem(
    key: str = "mem_001",
    content: str = "test content",
    tags: list[str] | None = None,
    importance: float = 0.5,
) -> Memory:
    now = datetime.now(UTC)
    return Memory(key=key, content=content, created_at=now, updated_at=now, tags=tags or [], importance=importance)


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

        yield tools, mock_app_context, mock_registry_cls


# ===========================================================================
# goal_manage
# ===========================================================================


class TestGoalManage:
    """Tests for goal_manage tool."""

    # -- Create ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_create_goal(self, registered_tools):
        """Creating a self goal should create a memory with ['goal', 'active'] tags."""
        tools, ctx, _ = registered_tools
        ctx.memory_service.create_memory.return_value = Success(_mem("goal_001", tags=["goal", "active"]))
        goal_manage = tools["goal_manage"]
        result = await goal_manage(operation="create", content="learn python", scope="self")

        assert "Goal created: goal_001" in result
        ctx.memory_service.create_memory.assert_called_once_with(
            content="learn python",
            importance=0.75,
            tags=["goal", "active"],
            emotion="neutral",
        )

    @pytest.mark.asyncio
    async def test_create_goal_interpersonal(self, registered_tools):
        """Creating an interpersonal goal should include 'interpersonal' in tags."""
        tools, ctx, _ = registered_tools
        ctx.memory_service.create_memory.return_value = Success(
            _mem("goal_002", tags=["goal", "active", "interpersonal"])
        )
        goal_manage = tools["goal_manage"]
        result = await goal_manage(operation="create", content="I will help", scope="interpersonal", importance=0.8)

        assert "Goal created: goal_002" in result
        ctx.memory_service.create_memory.assert_called_once_with(
            content="I will help",
            importance=0.8,
            tags=["goal", "active", "interpersonal"],
            emotion="neutral",
        )

    @pytest.mark.asyncio
    async def test_create_goal_custom_importance(self, registered_tools):
        """Custom importance should be passed through to create_memory."""
        tools, ctx, _ = registered_tools
        ctx.memory_service.create_memory.return_value = Success(_mem("goal_003"))
        goal_manage = tools["goal_manage"]
        result = await goal_manage(operation="create", content="important", importance=0.9, scope="self")

        assert "Goal created" in result
        ctx.memory_service.create_memory.assert_called_once_with(
            content="important",
            importance=0.9,
            tags=["goal", "active"],
            emotion="neutral",
        )

    @pytest.mark.asyncio
    async def test_create_goal_with_extra_tags(self, registered_tools):
        """Creating a goal with tags should merge them into the memory tags."""
        tools, ctx, _ = registered_tools
        ctx.memory_service.create_memory.return_value = Success(
            _mem("goal_004", tags=["goal", "active", "project:nous"])
        )
        goal_manage = tools["goal_manage"]
        result = await goal_manage(
            operation="create", content="nous project goal", scope="self", tags=["project:nous"]
        )

        assert "Goal created: goal_004" in result
        ctx.memory_service.create_memory.assert_called_once_with(
            content="nous project goal",
            importance=0.75,
            tags=["goal", "active", "project:nous"],
            emotion="neutral",
        )

    @pytest.mark.asyncio
    async def test_create_goal_with_extra_tags_interpersonal(self, registered_tools):
        """Interpersonal + extra tags should both be merged, in order."""
        tools, ctx, _ = registered_tools
        ctx.memory_service.create_memory.return_value = Success(
            _mem("goal_005", tags=["goal", "active", "interpersonal", "project:nous"])
        )
        goal_manage = tools["goal_manage"]
        result = await goal_manage(
            operation="create", content="help with nous", scope="interpersonal", tags=["project:nous"]
        )

        assert "Goal created: goal_005" in result
        ctx.memory_service.create_memory.assert_called_once_with(
            content="help with nous",
            importance=0.75,
            tags=["goal", "active", "interpersonal", "project:nous"],
            emotion="neutral",
        )

    @pytest.mark.asyncio
    async def test_create_goal_service_failure(self, registered_tools):
        """Service failure on create should return error message."""
        tools, ctx, _ = registered_tools
        ctx.memory_service.create_memory.return_value = Failure(RepositoryError("db error"))
        goal_manage = tools["goal_manage"]
        result = await goal_manage(operation="create", content="test", scope="self")

        assert "Error" in result

    # -- Achieve ----------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_achieve_goal_by_key(self, registered_tools):
        """Achieving a self goal by memory_key should update its tags."""
        tools, ctx, _ = registered_tools
        m = _mem("goal_001", content="learn python", tags=["goal", "active"])
        ctx.memory_service.get_memory.return_value = Success(m)
        ctx.memory_service.update_memory.return_value = Success(_mem("goal_001", tags=["goal", "achieved"]))
        goal_manage = tools["goal_manage"]
        result = await goal_manage(operation="achieve", memory_key="goal_001", scope="self")

        assert "Goal achieved" in result
        assert "learn python" in result
        ctx.memory_service.get_memory.assert_called_once_with("goal_001")
        ctx.memory_service.update_memory.assert_called_once_with(
            "goal_001", importance=0.9, tags=["goal", "achieved", "archived"]
        )

    @pytest.mark.asyncio
    async def test_achieve_goal_by_content(self, registered_tools):
        """Achieving a self goal by content matching should find and update."""
        tools, ctx, _ = registered_tools
        m = _mem("goal_001", content="learn python", tags=["goal", "active"])
        ctx.memory_service.get_by_tags.return_value = Success([m])
        ctx.memory_service.update_memory.return_value = Success(_mem("goal_001", tags=["goal", "achieved"]))
        goal_manage = tools["goal_manage"]
        result = await goal_manage(operation="achieve", content="learn python", scope="self")

        assert "Goal achieved" in result
        assert "learn python" in result
        ctx.memory_service.get_by_tags.assert_called_once_with(["goal", "active"])
        ctx.memory_service.update_memory.assert_called_once_with(
            "goal_001", importance=0.9, tags=["goal", "achieved", "archived"]
        )

    @pytest.mark.asyncio
    async def test_achieve_goal_by_content_case_insensitive(self, registered_tools):
        """Content matching should be case-insensitive."""
        tools, ctx, _ = registered_tools
        m = _mem("goal_001", content="LEARN PYTHON", tags=["goal", "active"])
        ctx.memory_service.get_by_tags.return_value = Success([m])
        ctx.memory_service.update_memory.return_value = Success(_mem("goal_001", tags=["goal", "achieved"]))
        goal_manage = tools["goal_manage"]
        result = await goal_manage(operation="achieve", content="learn python", scope="self")

        assert "Goal achieved" in result

    @pytest.mark.asyncio
    async def test_achieve_goal_interpersonal_by_key(self, registered_tools):
        """Achieving an interpersonal goal by memory_key should use interpersonal in search tags."""
        tools, ctx, _ = registered_tools
        m = _mem("goal_002", content="I will help", tags=["goal", "active", "interpersonal"])
        ctx.memory_service.get_memory.return_value = Success(m)
        ctx.memory_service.update_memory.return_value = Success(_mem("goal_002", tags=["goal", "achieved", "archived"]))
        goal_manage = tools["goal_manage"]
        result = await goal_manage(operation="achieve", memory_key="goal_002", scope="interpersonal")

        assert "Goal achieved" in result
        assert "I will help" in result

    @pytest.mark.asyncio
    async def test_achieve_goal_not_active(self, registered_tools):
        """Achieving a memory that is not an active goal should return error."""
        tools, ctx, _ = registered_tools
        m = _mem("goal_001", content="learn python", tags=["goal", "achieved"])
        ctx.memory_service.get_memory.return_value = Success(m)
        goal_manage = tools["goal_manage"]
        result = await goal_manage(operation="achieve", memory_key="goal_001", scope="self")

        assert "Error" in result
        assert "not an active goal" in result

    @pytest.mark.asyncio
    async def test_achieve_goal_key_not_found(self, registered_tools):
        """Achieving a goal with non-existent key should return error."""
        tools, ctx, _ = registered_tools
        ctx.memory_service.get_memory.return_value = Failure(RepositoryError("not found"))
        goal_manage = tools["goal_manage"]
        result = await goal_manage(operation="achieve", memory_key="missing", scope="self")

        assert "Error" in result

    @pytest.mark.asyncio
    async def test_achieve_goal_no_match_by_content(self, registered_tools):
        """Achieving a goal by content when no match exists should return error."""
        tools, ctx, _ = registered_tools
        ctx.memory_service.get_by_tags.return_value = Success(
            [_mem("goal_001", content="something else", tags=["goal", "active"])]
        )
        goal_manage = tools["goal_manage"]
        result = await goal_manage(operation="achieve", content="nonexistent", scope="self")

        assert "Error" in result
        assert "No active goal matching" in result

    @pytest.mark.asyncio
    async def test_achieve_goal_update_failure(self, registered_tools):
        """Service failure on update should return error."""
        tools, ctx, _ = registered_tools
        m = _mem("goal_001", content="learn python", tags=["goal", "active"])
        ctx.memory_service.get_memory.return_value = Success(m)
        ctx.memory_service.update_memory.return_value = Failure(RepositoryError("update failed"))
        goal_manage = tools["goal_manage"]
        result = await goal_manage(operation="achieve", memory_key="goal_001", scope="self")

        assert "Error" in result

    # -- Cancel -----------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_cancel_goal_by_key(self, registered_tools):
        """Cancelling a goal by memory_key should update tags to cancelled."""
        tools, ctx, _ = registered_tools
        m = _mem("goal_001", content="learn python", tags=["goal", "active"])
        ctx.memory_service.get_memory.return_value = Success(m)
        ctx.memory_service.update_memory.return_value = Success(_mem("goal_001", tags=["goal", "cancelled"]))
        goal_manage = tools["goal_manage"]
        result = await goal_manage(operation="cancel", memory_key="goal_001", scope="self")

        assert "Goal cancelled" in result
        assert "learn python" in result
        ctx.memory_service.get_memory.assert_called_once_with("goal_001")
        ctx.memory_service.update_memory.assert_called_once_with(
            "goal_001", importance=0.9, tags=["goal", "cancelled", "archived"]
        )

    @pytest.mark.asyncio
    async def test_cancel_goal_by_content(self, registered_tools):
        """Cancelling a goal by content matching should find and update."""
        tools, ctx, _ = registered_tools
        m = _mem("goal_001", content="learn python", tags=["goal", "active"])
        ctx.memory_service.get_by_tags.return_value = Success([m])
        ctx.memory_service.update_memory.return_value = Success(_mem("goal_001", tags=["goal", "cancelled"]))
        goal_manage = tools["goal_manage"]
        result = await goal_manage(operation="cancel", content="learn python", scope="self")

        assert "Goal cancelled" in result
        assert "learn python" in result

    # -- List -------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_list_goals_self(self, registered_tools):
        """Listing self goals should query with tags=['goal','active']."""
        tools, ctx, _ = registered_tools
        ctx.memory_service.get_by_tags.return_value = Success([_mem("g1", content="goal 1", tags=["goal", "active"])])
        goal_manage = tools["goal_manage"]
        result = await goal_manage(operation="list", scope="self")

        assert "Active goals" in result
        assert "goal 1" in result
        assert "[normal]" in result
        ctx.memory_service.get_by_tags.assert_called_once_with(["goal", "active"])

    @pytest.mark.asyncio
    async def test_list_goals_shows_importance_label(self, registered_tools):
        """Goal list should show importance label for each goal."""
        tools, ctx, _ = registered_tools
        ctx.memory_service.get_by_tags.return_value = Success(
            [
                _mem("g1", content="critical goal", tags=["goal", "active"], importance=0.95),
                _mem("g2", content="high goal", tags=["goal", "active"], importance=0.75),
                _mem("g3", content="normal goal", tags=["goal", "active"], importance=0.5),
                _mem("g4", content="low goal", tags=["goal", "active"], importance=0.2),
            ]
        )
        goal_manage = tools["goal_manage"]
        result = await goal_manage(operation="list", scope="self")

        assert "[critical]" in result
        assert "critical goal" in result
        assert "[high]" in result
        assert "high goal" in result
        assert "[normal]" in result
        assert "normal goal" in result
        assert "[low]" in result
        assert "low goal" in result

    @pytest.mark.asyncio
    async def test_list_goals_interpersonal(self, registered_tools):
        """Listing interpersonal goals should query with ['goal','active','interpersonal']."""
        tools, ctx, _ = registered_tools
        ctx.memory_service.get_by_tags.return_value = Success(
            [_mem("g2", content="interpersonal goal", tags=["goal", "active", "interpersonal"])]
        )
        goal_manage = tools["goal_manage"]
        result = await goal_manage(operation="list", scope="interpersonal")

        assert "Active goals" in result
        assert "interpersonal goal" in result
        ctx.memory_service.get_by_tags.assert_called_once_with(["goal", "active", "interpersonal"])

    @pytest.mark.asyncio
    async def test_list_goals_empty(self, registered_tools):
        """Listing goals when none exist should show (none)."""
        tools, ctx, _ = registered_tools
        ctx.memory_service.get_by_tags.return_value = Success([])
        goal_manage = tools["goal_manage"]
        result = await goal_manage(operation="list", scope="self")

        assert "(none)" in result

    @pytest.mark.asyncio
    async def test_list_goals_with_extra_tags(self, registered_tools):
        """Listing goals with tags should pass them to get_by_tags for filtering."""
        tools, ctx, _ = registered_tools
        ctx.memory_service.get_by_tags.return_value = Success(
            [_mem("g5", content="nous goal", tags=["goal", "active", "project:nous"])]
        )
        goal_manage = tools["goal_manage"]
        result = await goal_manage(operation="list", scope="self", tags=["project:nous"])

        assert "Active goals" in result
        assert "nous goal" in result
        ctx.memory_service.get_by_tags.assert_called_once_with(["goal", "active", "project:nous"])

    @pytest.mark.asyncio
    async def test_list_goals_with_extra_tags_interpersonal(self, registered_tools):
        """Listing interpersonal goals with tags should merge both."""
        tools, ctx, _ = registered_tools
        ctx.memory_service.get_by_tags.return_value = Success([])
        goal_manage = tools["goal_manage"]
        result = await goal_manage(operation="list", scope="interpersonal", tags=["project:nous"])

        assert "Active goals" in result
        ctx.memory_service.get_by_tags.assert_called_once_with(
            ["goal", "active", "interpersonal", "project:nous"]
        )

    @pytest.mark.asyncio
    async def test_list_goals_without_tags_unchanged(self, registered_tools):
        """Omitting tags should keep legacy behavior (all active goals)."""
        tools, ctx, _ = registered_tools
        ctx.memory_service.get_by_tags.return_value = Success(
            [_mem("g6", content="plain goal", tags=["goal", "active"])]
        )
        goal_manage = tools["goal_manage"]
        result = await goal_manage(operation="list", scope="self", tags=None)

        assert "plain goal" in result
        ctx.memory_service.get_by_tags.assert_called_once_with(["goal", "active"])

    # -- Edge cases -------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_unknown_operation(self, registered_tools):
        """Unknown operation should return error."""
        tools, ctx, _ = registered_tools
        goal_manage = tools["goal_manage"]
        result = await goal_manage(operation="invalid", scope="self")

        assert "Error" in result
        assert "Unknown operation" in result
