"""Tests for item-related MCP tool handlers (equip, add, remove, unequip, search, update)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nous.domain.shared.result import Success

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_app_context():
    ctx = MagicMock()
    ctx.memory_service = MagicMock()
    ctx.search_engine = MagicMock()
    ctx.persona_service = MagicMock()
    ctx.equipment_service = MagicMock()
    ctx.entity_service = MagicMock()
    ctx.event_bus = AsyncMock()
    ctx.vector_store = None  # no Qdrant by default
    ctx.settings = MagicMock()
    ctx.settings.contradiction_threshold = 0.85
    return ctx


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
# Split item tools (individual wrappers replacing operation-based dispatch)
# ---------------------------------------------------------------------------


class TestItemTools:
    """Tests for the individual item tools (item_add, item_remove, etc.)."""

    @pytest.mark.asyncio
    async def test_item_add(self, registered_tools):
        tools, ctx, _ = registered_tools
        ctx.equipment_service.add_item.return_value = Success(None)
        item_tool = tools["item_add"]
        with (
            patch("nous.api.mcp.tools.AppContextRegistry") as mock_reg_cls,
            patch("nous.api.mcp.tools.get_current_persona", return_value="test_persona"),
        ):
            mock_reg_cls.get.return_value = ctx
            result = await item_tool(item_name="red shoes", category="shoes")
        assert "added" in result.lower()
        ctx.equipment_service.add_item.assert_called_once_with("red shoes", "shoes", None, 1, None)

    @pytest.mark.asyncio
    async def test_item_remove(self, registered_tools):
        tools, ctx, _ = registered_tools
        ctx.equipment_service.remove_item.return_value = Success(None)
        item_tool = tools["item_remove"]
        with (
            patch("nous.api.mcp.tools.AppContextRegistry") as mock_reg_cls,
            patch("nous.api.mcp.tools.get_current_persona", return_value="test_persona"),
        ):
            mock_reg_cls.get.return_value = ctx
            result = await item_tool(item_name="red shoes")
        assert "removed" in result.lower()

    @pytest.mark.asyncio
    async def test_item_equip(self, registered_tools):
        tools, ctx, _ = registered_tools
        ctx.equipment_service.equip.return_value = Success(None)
        item_tool = tools["item_equip"]
        with (
            patch("nous.api.mcp.tools.AppContextRegistry") as mock_reg_cls,
            patch("nous.api.mcp.tools.get_current_persona", return_value="test_persona"),
        ):
            mock_reg_cls.get.return_value = ctx
            result = await item_tool(equipment={"top": "red dress"})
        assert "Equipped" in result

    @pytest.mark.asyncio
    async def test_item_unequip(self, registered_tools):
        tools, ctx, _ = registered_tools
        ctx.equipment_service.unequip.return_value = Success(None)
        item_tool = tools["item_unequip"]
        with (
            patch("nous.api.mcp.tools.AppContextRegistry") as mock_reg_cls,
            patch("nous.api.mcp.tools.get_current_persona", return_value="test_persona"),
        ):
            mock_reg_cls.get.return_value = ctx
            result = await item_tool(slots=["top"])
        assert "Unequipped" in result

    @pytest.mark.asyncio
    async def test_item_update(self, registered_tools):
        tools, ctx, _ = registered_tools
        ctx.equipment_service.update_item.return_value = Success(None)
        item_tool = tools["item_update"]
        with (
            patch("nous.api.mcp.tools.AppContextRegistry") as mock_reg_cls,
            patch("nous.api.mcp.tools.get_current_persona", return_value="test_persona"),
        ):
            mock_reg_cls.get.return_value = ctx
            result = await item_tool(item_name="red shoes", quantity=3)
        assert "updated" in result.lower()

    @pytest.mark.asyncio
    async def test_item_search(self, registered_tools):
        tools, ctx, _ = registered_tools
        item_obj = MagicMock()
        item_obj.name = "red shoes"
        item_obj.category = "shoes"
        item_obj.quantity = 1
        ctx.equipment_service.search_items.return_value = Success([item_obj])
        item_tool = tools["item_search"]
        with (
            patch("nous.api.mcp.tools.AppContextRegistry") as mock_reg_cls,
            patch("nous.api.mcp.tools.get_current_persona", return_value="test_persona"),
        ):
            mock_reg_cls.get.return_value = ctx
            result = await item_tool(query="shoes")
        assert "red shoes" in result

    @pytest.mark.asyncio
    async def test_item_history(self, registered_tools):
        tools, ctx, _ = registered_tools
        h = MagicMock()
        h.timestamp = "2024-01-15 10:00:00"
        h.action = "equip"
        h.item_name = "red shoes"
        h.slot = "shoes"
        ctx.equipment_service.get_history.return_value = Success([h])
        item_tool = tools["item_history"]
        with (
            patch("nous.api.mcp.tools.AppContextRegistry") as mock_reg_cls,
            patch("nous.api.mcp.tools.get_current_persona", return_value="test_persona"),
        ):
            mock_reg_cls.get.return_value = ctx
            result = await item_tool(days=7)
        assert "red shoes" in result

    @pytest.mark.asyncio
    async def test_item_add_missing_name(self, registered_tools):
        tools, ctx, _ = registered_tools
        item_tool = tools["item_add"]
        with (
            patch("nous.api.mcp.tools.AppContextRegistry") as mock_reg_cls,
            patch("nous.api.mcp.tools.get_current_persona", return_value="test_persona"),
        ):
            mock_reg_cls.get.return_value = ctx
            result = await item_tool(item_name="")
        assert "Error" in result
