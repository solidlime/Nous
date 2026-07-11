"""Auto-generated from tools.py split — _tools_item.py."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

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
    result = ctx.equipment_service.add_item(item_name, category, description, quantity, tags)
    if result.is_ok:
        await ctx.event_bus.publish(
            "tool.called",
            {
                "persona": persona,
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
            "tool_name": "item_add",
            "params_summary": f"item_name={item_name}, qty={quantity}",
            "result_summary": str(result.error),
            "success": False,
        },
    )
    return f"Error: {result.error}"


async def _tool_item_equip(ctx: AppContext, persona: str, equipment: dict | None = None, auto_add: bool = True) -> str:
    if not equipment:
        return 'Error: equipment dict required (e.g. {"top": "白いドレス"})'
    result = ctx.equipment_service.equip(equipment, auto_add)
    if result.is_ok:
        await ctx.event_bus.publish(
            "tool.called",
            {
                "persona": persona,
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
            "tool_name": "item_equip",
            "params_summary": f"equipment={equipment}",
            "result_summary": str(result.error),
            "success": False,
        },
    )
    return f"Error: {result.error}"


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
            "tool_name": "item_search",
            "params_summary": f"query={query}, category={category}",
            "result_summary": str(result.error),
            "success": False,
        },
    )
    return f"Error: {result.error}"
