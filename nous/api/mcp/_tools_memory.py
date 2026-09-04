"""Auto-generated from tools.py split — _tools_memory.py."""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

from nous.domain.search.engine import SearchQuery
from nous.domain.shared.errors import DuplicateMemoryError
from nous.domain.value_objects import _VALID_EMOTIONS, normalize_importance

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from nous.application.use_cases import AppContext


async def _tool_memory_create(
    ctx: AppContext,
    persona: str,
    content: str = "",
    importance: float | None = None,
    tags: list[str] | None = None,
    privacy_level: str = "internal",
    source_context: str | None = None,
    kind: str = "semantic",
    defer_vector: bool = False,
    skip_duplicate_check: bool = True,
) -> str:
    """Create a memory. Current persona state (emotion, body_state) is automatically
    snapshotted at creation time. Always call context_update/update_context *before*
    memory_create if your emotional/physical state has changed, so the snapshot
    captures your latest state."""
    if not content:
        return {"success": False, "data": None, "result_summary": "content is required"}
    if importance is not None and not (0.0 <= importance <= 1.0):
        return {"success": False, "data": None, "result_summary": "importance must be between 0.0 and 1.0"}
    importance = importance if importance is not None else 0.5

    # Auto-snapshot current persona state
    emotion_snap, intensity_snap, body_snap, snapped_at = ctx.persona_service.get_state_snapshot(persona)

    result = await ctx.memory_service.create_memory(
        content=content,
        importance=importance,
        tags=tags,
        privacy_level=privacy_level or "internal",
        source_context=source_context,
        kind=kind,
        emotion=emotion_snap,
        emotion_intensity=intensity_snap,
        body_state=body_snap,
        state_snapped_at=snapped_at,
        skip_duplicate_check=skip_duplicate_check,
        session_id=getattr(ctx, "session_id", None),
    )
    if result.is_ok:
        m = result.value
        ctx.record_memory_access(m.key)
        await ctx.event_bus.publish(
            "memory.created",
            {
                "key": m.key,
                "persona": persona,
                "content_preview": content[:100],
                "tags": tags or [],
                "importance": importance,
            },
        )
        return json.dumps({"ok": True, "key": m.key, "auto_emotion": True}, ensure_ascii=False)

    # Handle duplicate errors with the same response format as before
    if isinstance(result.error, DuplicateMemoryError):
        dup = result.error
        response: dict = {"ok": True, "status": "duplicate", "message": str(dup)}
        if dup.similar_to:
            response["similar_to"] = dup.similar_to
        if dup.duplicate_key:
            response["duplicate_of"] = dup.duplicate_key
        return json.dumps(response, ensure_ascii=False)

    return {"success": False, "data": None, "result_summary": str(result.error)}


async def _tool_memory_read(
    ctx: AppContext,
    persona: str,
    memory_key: str | None = None,
    limit: int = 10,
    offset: int = 0,
) -> str:
    """Read a memory by key, or list most recent if key omitted. Use limit/offset for pagination."""
    if memory_key:
        result = ctx.memory_service.get_memory(memory_key)
        if result.is_ok:
            try:
                ctx.memory_service.boost_recall(memory_key)
            except Exception as e:
                logger.warning(f"boost_recall failed: {e}")
            m = result.value
            ctx.record_memory_access(m.key)
            emotion_line = f"Emotion: {m.emotion}"
            if m.emotion_intensity:
                emotion_line += f" (intensity: {m.emotion_intensity})"
            result_text = (
                f"Key: {m.key}\nContent: {m.content}\n"
                f"Importance: {m.importance}\n{emotion_line}\n"
                f"Tags: {m.tags}\nCreated: {m.created_at}"
            )
            await ctx.event_bus.publish(
                "tool.called",
                {
                    "persona": persona,
                    "session_id": getattr(ctx, "session_id", None),
                    "tool_name": "memory_read",
                    "params_summary": f"memory_key={memory_key}",
                    "result_summary": f"Read memory: {m.key}",
                    "success": True,
                },
            )
            return result_text
        await ctx.event_bus.publish(
            "tool.called",
            {
                "persona": persona,
                "session_id": getattr(ctx, "session_id", None),
                "tool_name": "memory_read",
                "params_summary": f"memory_key={memory_key}",
                "result_summary": str(result.error),
                "success": False,
            },
        )
        return f"Error: {result.error}"
    else:
        memories_result = ctx.memory_service.get_recent(limit=limit + offset)
        if memories_result.is_ok:
            items = memories_result.value[offset : offset + limit]
            count_result = ctx.memory_service.count_memories()
            total_count = count_result.value if count_result.is_ok else len(items)
            return json.dumps(
                {
                    "ok": True,
                    "memories": [
                        {
                            "key": m.key,
                            "content": m.content,
                            "importance": m.importance,
                            "emotion": m.emotion,
                            "tags": m.tags,
                            "created_at": str(m.created_at) if m.created_at else None,
                        }
                        for m in items
                    ],
                    "total_count": total_count,
                },
                ensure_ascii=False,
            )
        await ctx.event_bus.publish(
            "tool.called",
            {
                "persona": persona,
                "session_id": getattr(ctx, "session_id", None),
                "tool_name": "memory_read",
                "params_summary": f"limit={limit}, offset={offset}",
                "result_summary": str(memories_result.error),
                "success": False,
            },
        )
        return {"success": False, "data": None, "result_summary": str(memories_result.error)}


async def _tool_memory_update(
    ctx: AppContext,
    persona: str,
    memory_key: str = "",
    query: str = "",
    content: str | None = None,
    importance: float | None = None,
    emotion: str | None = None,
    emotion_intensity: float | None = None,
    tags: list[str] | None = None,
    privacy_level: str | None = None,
    new_content: str | None = None,
) -> str:
    """Update a memory. Only provided fields are changed.
    importance must be 0.0-1.0. Invalid emotion returns error.
    query: search query to resolve memory_key (alternative to direct memory_key)."""
    # query から key を解決（builtin互換）
    if query and not memory_key:
        search_result = await ctx.search_engine.search(SearchQuery(text=query, top_k=1))
        if not search_result.is_ok or not search_result.value:
            return {"success": False, "data": None, "result_summary": f"No memory found for query: {query}"}
        item = search_result.value[0]
        mem = item[0] if isinstance(item, tuple) else item
        memory_key = getattr(mem, "key", "")
        if not memory_key:
            return {"success": False, "data": None, "result_summary": "memory key not found"}

    # builtin からの new_content フォールバック
    if content is None and new_content is not None:
        content = new_content

    if not memory_key:
        return {"success": False, "data": None, "result_summary": "memory_key is required for update"}

    # ── Input validation ──
    if content is not None and len(content) > 50000:
        return {"success": False, "data": None, "result_summary": "content too long (max 50000 chars)"}

    if importance is not None and not (0.0 <= importance <= 1.0):
        return {"success": False, "data": None, "result_summary": "importance must be between 0.0 and 1.0"}

    if emotion is not None and emotion not in _VALID_EMOTIONS:
        return {"success": False, "data": None, "result_summary": f"invalid emotion: {emotion}"}

    if emotion_intensity is not None:
        try:
            emotion_intensity = float(emotion_intensity)
            emotion_intensity = max(0.0, min(1.0, emotion_intensity))
        except (TypeError, ValueError):
            return {"success": False, "data": None, "result_summary": "emotion_intensity must be a number"}

    if tags is not None:
        if not isinstance(tags, list):
            return {"success": False, "data": None, "result_summary": "tags must be a list"}
        if not all(isinstance(t, str) for t in tags):
            return {"success": False, "data": None, "result_summary": "all tags must be strings"}
        if any(len(t) > 100 for t in tags):
            return {"success": False, "data": None, "result_summary": "tag too long (max 100 chars)"}

    valid_privacy = {"internal", "private", "public"}
    if privacy_level is not None and privacy_level not in valid_privacy:
        return {
            "success": False,
            "data": None,
            "result_summary": f"invalid privacy_level: {privacy_level}. Must be: {', '.join(sorted(valid_privacy))}",
        }

    updates: dict = {}
    if content is not None:
        updates["content"] = content
    if importance is not None:
        updates["importance"] = normalize_importance(importance)
    if emotion is not None:
        updates["emotion"] = emotion
    if emotion_intensity is not None:
        updates["emotion_intensity"] = emotion_intensity
    if tags is not None:
        updates["tags"] = tags
    if privacy_level is not None:
        updates["privacy_level"] = privacy_level

    if not updates:
        return {"success": False, "data": None, "result_summary": "no fields to update"}

    result = ctx.memory_service.update_memory(memory_key, **updates)
    if result.is_ok:
        await ctx.event_bus.publish(
            "memory.updated",
            {
                "key": memory_key,
                "persona": persona,
                "content_preview": (content or "...")[:100],
                "changes": list(updates.keys()),
            },
        )
        return json.dumps({"ok": True, "key": memory_key}, ensure_ascii=False)
    return {"success": False, "data": None, "result_summary": str(result.error)}


async def _tool_memory_delete(
    ctx: AppContext, persona: str, memory_key: str | None = None, query: str | None = None
) -> str:
    """Delete (tombstone) a memory by key or query. Returns key and content snippet of deleted memory."""
    if not memory_key and not query:
        return "Error: memory_key or query required"

    # If query provided without key, search first
    key = memory_key
    content_preview = "..."
    if not key and query:
        search_result = await ctx.search_engine.search(SearchQuery(text=query, top_k=1))
        if search_result.is_ok and search_result.value:
            m = search_result.value[0].memory
            key = m.key
            content_preview = m.content[:100]
            snippet = f"\nContent: 「{m.content[:80]}{'...' if len(m.content) > 80 else ''}」"
        else:
            return f"No memory found for query: {query}"
    else:
        snippet = ""
        pre_fetch = ctx.memory_service.get_memory(key)
        if pre_fetch.is_ok:
            content_preview = pre_fetch.value.content[:100]
            snippet = (
                f"\nContent: 「{pre_fetch.value.content[:80]}{'...' if len(pre_fetch.value.content) > 80 else ''}」"
            )

    result = ctx.memory_service.delete_memory(key)
    if result.is_ok:
        await ctx.event_bus.publish(
            "memory.deleted",
            {
                "key": key,
                "persona": persona,
                "content_preview": content_preview,
            },
        )
        return f"Memory tombstoned: {key}{snippet}"
    return f"Error: {result.error}"


async def _tool_memory_search(
    ctx: AppContext,
    persona: str,
    query: str,
    top_k: int = 5,
    tags: list[str] | None = None,
    date_range: str | None = None,
    min_importance: float | None = None,
    emotion: str | None = None,
    importance_weight: float = 0.0,
    recency_weight: float = 0.0,
    vector_weight: float = 1.0,
    keyword_weight: float = 0.5,
    kind: str | None = None,
    sort: str | None = None,
) -> str:
    """Search memories with hybrid retrieval. sort: "updated_at" 指定で更新日時降順（最新優先）"""
    if top_k is not None and (top_k < 1 or top_k > 200):
        return {"success": False, "data": None, "result_summary": "top_k must be between 1 and 200"}
    top_k = min(top_k or 5, 200)
    # Clamp RRF weights to [0.0, 1.0]
    importance_weight = max(0.0, min(1.0, importance_weight))
    recency_weight = max(0.0, min(1.0, recency_weight))
    vector_weight = max(0.0, min(1.0, vector_weight))
    keyword_weight = max(0.0, min(1.0, keyword_weight))
    search_query = SearchQuery(
        text=query,
        top_k=top_k,
        tags=tags,
        date_range=date_range,
        min_importance=min_importance,
        emotion=emotion,
        importance_weight=importance_weight,
        recency_weight=recency_weight,
        vector_weight=vector_weight,
        keyword_weight=keyword_weight,
        kind=kind,
        sort=sort,
    )
    ctx.search_engine.set_persona(persona)
    result = await ctx.search_engine.search(search_query)
    if not result.is_ok:
        await ctx.event_bus.publish(
            "tool.called",
            {
                "persona": persona,
                "session_id": getattr(ctx, "session_id", None),
                "tool_name": "memory_search",
                "params_summary": f"query={query[:50]}, top_k={top_k}",
                "result_summary": str(result.error),
                "success": False,
            },
        )
        return {"success": False, "data": None, "result_summary": str(result.error)}
    if not result.value:
        await ctx.event_bus.publish(
            "tool.called",
            {
                "persona": persona,
                "session_id": getattr(ctx, "session_id", None),
                "tool_name": "memory_search",
                "params_summary": f"query={query[:50]}, top_k={top_k}",
                "result_summary": "No results found",
                "success": True,
            },
        )
        count_result = ctx.memory_service.count_memories()
        total_count = count_result.value if count_result.is_ok else 0
        return json.dumps({"ok": True, "memories": [], "total_count": total_count}, ensure_ascii=False)
    ctx.memory_service.log_search(query, "hybrid", len(result.value))

    # Normalize scores to 0-1 for intuitive LLM consumption
    scores = [sr.score for sr in result.value]
    max_score = max(scores) if scores else 0.0

    memories: list[dict] = []
    for sr in result.value:
        m = sr.memory
        entry: dict = {
            "key": m.key,
            "content": m.content,
            "importance": m.importance,
            "tags": m.tags,
            "emotion": m.emotion,
            "score": (sr.score / max_score) if max_score > 0 else sr.score,
        }
        if sr.similarity_flag:
            entry["similarity_flag"] = True
        memories.append(entry)
    await ctx.event_bus.publish(
        "tool.called",
        {
            "persona": persona,
            "session_id": getattr(ctx, "session_id", None),
            "tool_name": "memory_search",
            "params_summary": f"query={query[:50]}, top_k={top_k}",
            "result_summary": f"Found {len(result.value)} results",
            "success": True,
        },
    )
    count_result = ctx.memory_service.count_memories()
    total_count = count_result.value if count_result.is_ok else len(result.value)
    return json.dumps({"ok": True, "memories": memories, "total_count": total_count}, ensure_ascii=False)


async def _tool_memory_stats(ctx: AppContext, persona: str, top_n: int = 20) -> str:
    """Get memory statistics."""
    result = ctx.memory_service.get_stats(top_n=top_n)
    if result.is_ok:
        result_text = str(result.value)
        await ctx.event_bus.publish(
            "tool.called",
            {
                "persona": persona,
                "session_id": getattr(ctx, "session_id", None),
                "tool_name": "memory_stats",
                "params_summary": f"top_n={top_n}",
                "result_summary": f"Stats retrieved ({len(result_text)} chars)",
                "success": True,
            },
        )
        return result_text
    await ctx.event_bus.publish(
        "tool.called",
        {
            "persona": persona,
            "session_id": getattr(ctx, "session_id", None),
            "tool_name": "memory_stats",
            "params_summary": f"top_n={top_n}",
            "result_summary": str(result.error),
            "success": False,
        },
    )
    return f"Error: {result.error}"
