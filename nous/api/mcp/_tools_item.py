"""Auto-generated from tools.py split — _tools_item.py."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from nous.domain.shared.result import Failure

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from nous.application.use_cases import AppContext


async def _tool_item_add(
    ctx: AppContext,
    persona: str,
    item_name: str = "",
    category: str | None = None,
    description: str | None = None,
    quantity: int = 1,
    tags: list[str] | None = None,
) -> str:
    if not item_name:
        return "Error: item_name required"
    # audit:C2 fix — must be keyword args: add_item's 4th positional param is visual_desc,
    # not quantity (passing positionally landed quantity in visual_desc, tags in quantity).
    result = ctx.equipment_service.add_item(
        item_name, category=category, description=description, quantity=quantity, tags=tags
    )
    if result.is_ok:
        await ctx.event_bus.publish(
            "tool.called",
            {
                "persona": persona,
                "session_id": getattr(ctx, "session_id", None),
                "tool_name": "item_add",
                "params_summary": f"item_name={item_name}, qty={quantity}",
                "result_summary": f"Item added: {item_name}",
                "success": True,
            },
        )
        return f"Item added: {item_name}"
    await ctx.event_bus.publish(
        "tool.called",
        {
            "persona": persona,
            "session_id": getattr(ctx, "session_id", None),
            "tool_name": "item_add",
            "params_summary": f"item_name={item_name}, qty={quantity}",
            "result_summary": str(result.error),
            "success": False,
        },
    )
    return f"Error: {result.error}"


async def _tool_item_equip(ctx: AppContext, persona: str, equipment: dict | None = None, auto_add: bool = False) -> str:
    """Equip items to slots.

    audit M9-b (v4.0): ``auto_add`` defaults to False on the LLM-facing surfaces
    (MCP tool + chat built-in tool), so an unregistered item is *not* silently
    created. The LLM must pass ``auto_add=true`` explicitly to opt in (the HTTP
    route keeps the legacy True default for external-client compatibility).
    """
    if not equipment:
        return 'Error: equipment dict required (e.g. {"top": "白いドレス"})'
    result = ctx.equipment_service.equip(equipment, auto_add)
    if result.is_ok:
        # 装備スロットから appearance を自動合成して persona state に反映する
        # (audit C2: 再計算は Service 層の単一経路に集約)
        ctx.equipment_service.recompute_appearance(ctx.persona_service, persona)
        await ctx.event_bus.publish(
            "tool.called",
            {
                "persona": persona,
                "session_id": getattr(ctx, "session_id", None),
                "tool_name": "item_equip",
                "params_summary": f"equipment={equipment}",
                "result_summary": f"Equipped: {equipment}",
                "success": True,
            },
        )
        return f"Equipped: {equipment}"
    await ctx.event_bus.publish(
        "tool.called",
        {
            "persona": persona,
            "session_id": getattr(ctx, "session_id", None),
            "tool_name": "item_equip",
            "params_summary": f"equipment={equipment}",
            "result_summary": str(result.error),
            "success": False,
        },
    )
    return f"Error: {result.error}"


async def _tool_item_unequip(ctx: AppContext, persona: str, slots: list[str] | str = "") -> str:
    """Unequip one or more slots (audit L4: HTTP-only capability moved to MCP)."""
    if not slots:
        return "Error: slots required (e.g. ['top'] or 'top')"
    result = ctx.equipment_service.unequip(slots)
    slot_list = [slots] if isinstance(slots, str) else list(slots)
    if isinstance(result, Failure):
        await ctx.event_bus.publish(
            "tool.called",
            {
                "persona": persona,
                "session_id": getattr(ctx, "session_id", None),
                "tool_name": "item_unequip",
                "params_summary": f"slots={slot_list}",
                "result_summary": str(result.error),
                "success": False,
            },
        )
        return f"Error: {result.error}"
    # Rebuild appearance from the remaining equipment (audit C2: single path)
    ctx.equipment_service.recompute_appearance(ctx.persona_service, persona)
    await ctx.event_bus.publish(
        "tool.called",
        {
            "persona": persona,
            "session_id": getattr(ctx, "session_id", None),
            "tool_name": "item_unequip",
            "params_summary": f"slots={slot_list}",
            "result_summary": f"Unequipped: {slot_list}",
            "success": True,
        },
    )
    return f"Unequipped: {slot_list}"


async def _tool_item_search(
    ctx: AppContext, persona: str, query: str | None = None, category: str | None = None
) -> str:
    result = ctx.equipment_service.search_items(query, category)
    if result.is_ok:
        items = result.value
        if not items:
            await ctx.event_bus.publish(
                "tool.called",
                {
                    "persona": persona,
                    "session_id": getattr(ctx, "session_id", None),
                    "tool_name": "item_search",
                    "params_summary": f"query={query}, category={category}",
                    "result_summary": "No items found",
                    "success": True,
                },
            )
            return "No items found."
        result_text = "\n".join(f"- {i.name} (category={i.category}, qty={i.quantity})" for i in items)
        await ctx.event_bus.publish(
            "tool.called",
            {
                "persona": persona,
                "session_id": getattr(ctx, "session_id", None),
                "tool_name": "item_search",
                "params_summary": f"query={query}, category={category}",
                "result_summary": f"Found {len(items)} items",
                "success": True,
            },
        )
        return result_text
    await ctx.event_bus.publish(
        "tool.called",
        {
            "persona": persona,
            "session_id": getattr(ctx, "session_id", None),
            "tool_name": "item_search",
            "params_summary": f"query={query}, category={category}",
            "result_summary": str(result.error),
            "success": False,
        },
    )
    return f"Error: {result.error}"
