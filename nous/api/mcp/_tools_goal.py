"""Auto-generated from tools.py split — _tools_goal.py."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from nous.domain.search.engine import SearchQuery
from nous.domain.value_objects import importance_to_label

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from nous.application.use_cases import AppContext


async def _tool_goal_manage(
    ctx: AppContext,
    persona: str,
    operation: str,
    content: str = "",
    importance: float = 0.75,
    scope: str = "self",
    memory_key: str | None = None,
    tags: list[str] | None = None,
) -> dict:
    if operation == "list":
        base_tags = ["goal", "active"]
        search_tags = base_tags + ["interpersonal"] if scope == "interpersonal" else base_tags
        search_tags = search_tags + (tags or [])
        tag_result = ctx.memory_service.get_by_tags(search_tags)
        if not tag_result.is_ok:
            await ctx.event_bus.publish(
                "tool.called",
                {
                    "persona": persona,
                    "tool_name": "goal_manage",
                    "params_summary": "operation=list",
                    "result_summary": str(tag_result.error),
                    "success": False,
                },
            )
            return {"ok": False, "error": tag_result.error}
        memories = tag_result.value or []
        # scope="self" の場合は interpersonal タグ付きを除外
        if scope == "self":
            memories = [m for m in memories if "interpersonal" not in (getattr(m, "tags", []) or [])]
        lines = [f"Active goals (scope={scope}):"]
        if not memories:
            lines.append("  (none)")
        else:
            for m in memories:
                content_str = getattr(m, "content", "?")[:80]
                imp = getattr(m, "importance", 0.5) or 0.5
                label = importance_to_label(imp)
                lines.append(f"  - [{label}] {content_str} (imp={imp:.2f}) [key={m.key}]")
        result_text = "\n".join(lines)
        await ctx.event_bus.publish(
            "tool.called",
            {
                "persona": persona,
                "tool_name": "goal_manage",
                "params_summary": f"operation=list, scope={scope}, tags={tags}",
                "result_summary": f"Listed {len(memories)} goals",
                "success": True,
            },
        )
        return {"ok": True, "result": result_text}

    if operation == "create":
        create_tags = ["goal", "active"]
        if scope == "interpersonal":
            create_tags.append("interpersonal")
        create_tags += tags or []
        result = await ctx.memory_service.create_memory(
            content=content,
            importance=importance,
            tags=create_tags,
            emotion="neutral",
        )
        if result.is_ok:
            await ctx.event_bus.publish(
                "tool.called",
                {
                    "persona": persona,
                    "tool_name": "goal_manage",
                    "params_summary": f"operation=create, scope={scope}, tags={tags}, content={content[:50]}",
                    "result_summary": f"Goal created: {result.value.key}",
                    "success": True,
                },
            )
            return {"ok": True, "key": result.value.key}
        await ctx.event_bus.publish(
            "tool.called",
            {
                "persona": persona,
                "tool_name": "goal_manage",
                "params_summary": f"operation=create, scope={scope}, tags={tags}, content={content[:50]}",
                "result_summary": str(result.error),
                "success": False,
            },
        )
        return {"ok": False, "error": result.error}
    elif operation in ("achieve", "cancel"):
        new_status = "achieved" if operation == "achieve" else "cancelled"
        search_tags = ["goal", "active"]
        if scope == "interpersonal":
            search_tags.append("interpersonal")
        search_tags = search_tags + (tags or [])
        if memory_key and memory_key.strip():
            get_result = ctx.memory_service.get_memory(memory_key)
            if not get_result.is_ok:
                await ctx.event_bus.publish(
                    "tool.called",
                    {
                        "persona": persona,
                        "tool_name": "goal_manage",
                        "params_summary": f"operation={operation}, memory_key={memory_key}",
                        "result_summary": str(get_result.error),
                        "success": False,
                    },
                )
                return {"ok": False, "error": get_result.error}
            match = get_result.value
            if "goal" not in match.tags or "active" not in match.tags:
                await ctx.event_bus.publish(
                    "tool.called",
                    {
                        "persona": persona,
                        "tool_name": "goal_manage",
                        "params_summary": f"operation={operation}, memory_key={memory_key}",
                        "result_summary": f"Memory '{memory_key}' is not an active goal",
                        "success": False,
                    },
                )
                return {"ok": False, "error": f"Memory '{memory_key}' is not an active goal."}
        else:
            # Hybrid search first
            ctx.search_engine.set_persona(persona)
            search_query = SearchQuery(
                text=content,
                tags=search_tags,
                top_k=3,
                mode="hybrid",
                vector_weight=1.0,
                keyword_weight=0.5,
            )
            search_result = await ctx.search_engine.search(search_query)

            match = None
            if search_result.is_ok and search_result.value:
                top = search_result.value[0]
                if isinstance(top.score, (int, float)) and top.score > 0.3:
                    match = top.memory

            # Fallback: exact match by tags + content
            if match is None:
                tag_result = ctx.memory_service.get_by_tags(search_tags)
                if not tag_result.is_ok:
                    await ctx.event_bus.publish(
                        "tool.called",
                        {
                            "persona": persona,
                            "tool_name": "goal_manage",
                            "params_summary": f"operation={operation}, content={content[:50]}",
                            "result_summary": str(tag_result.error),
                            "success": False,
                        },
                    )
                    return {"ok": False, "error": tag_result.error}
                candidates = tag_result.value or []
                match = next((m for m in candidates if content.strip().lower() == m.content.strip().lower()), None)

            if match is None:
                await ctx.event_bus.publish(
                    "tool.called",
                    {
                        "persona": persona,
                        "tool_name": "goal_manage",
                        "params_summary": f"operation={operation}, content={content[:50]}",
                        "result_summary": f"No active goal matching '{content[:40]}' found",
                        "success": False,
                    },
                )
                return {"ok": False, "error": f"No active goal matching '{content}' found."}
        new_importance = max(match.importance, 0.9)
        new_tags = ["goal", new_status, "archived"]
        update_result = ctx.memory_service.update_memory(match.key, importance=new_importance, tags=new_tags)
        if update_result.is_ok:
            await ctx.event_bus.publish(
                "tool.called",
                {
                    "persona": persona,
                    "tool_name": "goal_manage",
                    "params_summary": f"operation={operation}, content={match.content[:50]}",
                    "result_summary": f"Goal {new_status}: {match.content[:80]}",
                    "success": True,
                },
            )
            return {"ok": True, "status": new_status, "content": match.content[:80]}
        await ctx.event_bus.publish(
            "tool.called",
            {
                "persona": persona,
                "tool_name": "goal_manage",
                "params_summary": f"operation={operation}, memory_key={match.key}",
                "result_summary": str(update_result.error),
                "success": False,
            },
        )
        return {"ok": False, "error": update_result.error}
    else:
        await ctx.event_bus.publish(
            "tool.called",
            {
                "persona": persona,
                "tool_name": "goal_manage",
                "params_summary": f"operation={operation}, content={content[:50]}",
                "result_summary": f"Unknown operation: {operation}",
                "success": False,
            },
        )
        return {"ok": False, "error": f"Unknown operation: {operation}. Use create/list/achieve/cancel."}
