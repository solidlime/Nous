"""Tests for item-related MCP tool handlers (equip, add, remove, unequip, search, update)."""

from __future__ import annotations

import json
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
        ctx.equipment_service.add_item.assert_called_once_with(
            "red shoes", category="shoes", description=None, quantity=1, tags=None
        )

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
        # audit M9-b: LLM 面の auto_add 既定は False（幻アイテムを生成しない）
        ctx.equipment_service.equip.assert_called_once_with({"top": "red dress"}, False)

    @pytest.mark.asyncio
    async def test_item_equip_explicit_auto_add_true(self, registered_tools):
        """LLM が auto_add=true を明示した時だけ自動追加を許可する (audit M9-b)。"""
        tools, ctx, _ = registered_tools
        ctx.equipment_service.equip.return_value = Success(None)
        item_tool = tools["item_equip"]
        with (
            patch("nous.api.mcp.tools.AppContextRegistry") as mock_reg_cls,
            patch("nous.api.mcp.tools.get_current_persona", return_value="test_persona"),
        ):
            mock_reg_cls.get.return_value = ctx
            result = await item_tool(equipment={"top": "red dress"}, auto_add=True)
        assert "Equipped" in result
        ctx.equipment_service.equip.assert_called_once_with({"top": "red dress"}, True)

    @pytest.mark.asyncio
    async def test_item_equip_syncs_appearance_to_persona_state(self, registered_tools):
        """equip 成功時、appearance 再計算を Service 層の単一経路に委譲する (audit C2)."""
        tools, ctx, _ = registered_tools
        ctx.equipment_service.equip.return_value = Success({"top": "red dress"})
        item_tool = tools["item_equip"]
        with (
            patch("nous.api.mcp.tools.AppContextRegistry") as mock_reg_cls,
            patch("nous.api.mcp.tools.get_current_persona", return_value="test_persona"),
        ):
            mock_reg_cls.get.return_value = ctx
            result = await item_tool(equipment={"top": "red dress"})
        assert "Equipped" in result
        ctx.equipment_service.recompute_appearance.assert_called_once_with(ctx.persona_service, "test_persona")

    @pytest.mark.asyncio
    async def test_item_unequip_syncs_appearance_to_persona_state(self, registered_tools):
        """unequip 成功時も appearance を再計算する (audit C2/L4)."""
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
        ctx.equipment_service.recompute_appearance.assert_called_once_with(ctx.persona_service, "test_persona")

    @pytest.mark.asyncio
    async def test_item_equip_skips_appearance_sync_on_failure(self, registered_tools):
        """equip 失敗時は appearance を更新しない."""
        from nous.domain.shared.errors import DomainError
        from nous.domain.shared.result import Failure

        tools, ctx, _ = registered_tools
        ctx.equipment_service.equip.return_value = Failure(DomainError("slot full"))
        item_tool = tools["item_equip"]
        with (
            patch("nous.api.mcp.tools.AppContextRegistry") as mock_reg_cls,
            patch("nous.api.mcp.tools.get_current_persona", return_value="test_persona"),
        ):
            mock_reg_cls.get.return_value = ctx
            result = await item_tool(equipment={"top": "red dress"})
        assert json.loads(result)["ok"] is False
        ctx.persona_service.update_state.assert_not_called()

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
    async def test_item_add_missing_name(self, registered_tools):
        tools, ctx, _ = registered_tools
        item_tool = tools["item_add"]
        with (
            patch("nous.api.mcp.tools.AppContextRegistry") as mock_reg_cls,
            patch("nous.api.mcp.tools.get_current_persona", return_value="test_persona"),
        ):
            mock_reg_cls.get.return_value = ctx
            result = await item_tool(item_name="")
        assert json.loads(result)["ok"] is False
