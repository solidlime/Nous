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


async def _tool_item_remove(ctx: AppContext, persona: str, item_name: str = "") -> str:
    if not item_name:
        return "Error: item_name required"
    result = ctx.equipment_service.remove_item(item_name)
    if result.is_ok:
        await ctx.event_bus.publish(
            "tool.called",
            {
                "persona": persona,
                "tool_name": "item_remove",
                "params_summary": f"item_name={item_name}",
                "result_summary": f"Item removed: {item_name}",
                "success": True,
            },
        )
        return f"Item removed: {item_name}"
    await ctx.event_bus.publish(
        "tool.called",
        {
            "persona": persona,
            "tool_name": "item_remove",
            "params_summary": f"item_name={item_name}",
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


async def _tool_item_unequip(ctx: AppContext, persona: str, slots: list[str] | str | None = None) -> str:
    target_slots = slots if isinstance(slots, list) else [slots] if slots else []
    if not target_slots:
        return "Error: slots required"
    result = ctx.equipment_service.unequip(target_slots)
    if result.is_ok:
        await ctx.event_bus.publish(
            "tool.called",
            {
                "persona": persona,
                "tool_name": "item_unequip",
                "params_summary": f"slots={target_slots}",
                "result_summary": f"Unequipped: {target_slots}",
                "success": True,
            },
        )
        return f"Unequipped: {target_slots}"
    await ctx.event_bus.publish(
        "tool.called",
        {
            "persona": persona,
            "tool_name": "item_unequip",
            "params_summary": f"slots={target_slots}",
            "result_summary": str(result.error),
            "success": False,
        },
    )
    return f"Error: {result.error}"


async def _tool_item_update(
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
    updates: dict = {}
    if description is not None:
        updates["description"] = description
    if category is not None:
        updates["category"] = category
    if quantity != 1:
        updates["quantity"] = quantity
    if tags is not None:
        updates["tags"] = tags
    result = ctx.equipment_service.update_item(item_name, **updates)
    if result.is_ok:
        await ctx.event_bus.publish(
            "tool.called",
            {
                "persona": persona,
                "tool_name": "item_update",
                "params_summary": f"item_name={item_name}, updates={list(updates.keys())}",
                "result_summary": f"Item updated: {item_name}",
                "success": True,
            },
        )
        return f"Item updated: {item_name}"
    await ctx.event_bus.publish(
        "tool.called",
        {
            "persona": persona,
            "tool_name": "item_update",
            "params_summary": f"item_name={item_name}, updates={list(updates.keys())}",
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


async def _tool_item_history(ctx: AppContext, persona: str, days: int = 7) -> str:
    result = ctx.equipment_service.get_history(days)
    if result.is_ok:
        history = result.value
        if not history:
            await ctx.event_bus.publish(
                "tool.called",
                {
                    "persona": persona,
                    "tool_name": "item_history",
                    "params_summary": f"days={days}",
                    "result_summary": "No history found",
                    "success": True,
                },
            )
            return "No history found."
        result_text = "\n".join(f"[{h.timestamp}] {h.action}: {h.item_name} ({h.slot})" for h in history)
        await ctx.event_bus.publish(
            "tool.called",
            {
                "persona": persona,
                "tool_name": "item_history",
                "params_summary": f"days={days}",
                "result_summary": f"Found {len(history)} history entries",
                "success": True,
            },
        )
        return result_text
    await ctx.event_bus.publish(
        "tool.called",
        {
            "persona": persona,
            "tool_name": "item_history",
            "params_summary": f"days={days}",
            "result_summary": str(result.error),
            "success": False,
        },
    )
    return f"Error: {result.error}"
