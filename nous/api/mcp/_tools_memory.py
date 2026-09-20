"""Auto-generated from tools.py split — _tools_memory.py."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import TYPE_CHECKING

from nous.api.mcp._envelope import ToolErrorCode, tool_error, tool_ok
from nous.api.mcp._tools_helpers import tool_called_audited
from nous.domain.search.engine import SearchQuery, SearchResult
from nous.domain.shared.errors import DuplicateMemoryError
from nous.domain.shared.result import Success
from nous.domain.shared.time_utils import format_iso, get_now, relative_time_str
from nous.domain.value_objects import _VALID_EMOTIONS, normalize_importance

# Default recency boost for memory_search (RRF recency bonus multiplier).
# Single source of truth — tools.py schema default references this.
# 0.05: recent-but-weak memories must not displace clearly-more-relevant
# older ones (the 1/(1+age_days) bonus decays to ~0.03 at 30 days, so
# larger defaults invert rankings — see test_memory_time_context.py).
MEMORY_SEARCH_RECENCY_WEIGHT_DEFAULT = 0.05

# Minimum similarity for query-based destructive resolution (memory_delete /
# memory_update by query) and goal resolution. Single source — audit:M6:
# an unrelated query must never resolve to a delete/update target.
# 0.3 matches the goal-resolution threshold previously used in _tools_goal.py.
QUERY_RESOLVE_MIN_SCORE = 0.3

logger = logging.getLogger(__name__)


def _ok(payload: dict) -> str:
    """Success wrapper: dict → common envelope JSON (audit C1)."""
    return tool_ok(payload)


def _err(msg: str) -> str:
    """Error wrapper: message → common envelope JSON, VALIDATION_ERROR (audit C1)."""
    return tool_error(ToolErrorCode.VALIDATION_ERROR, msg)


if TYPE_CHECKING:
    from nous.application.use_cases import AppContext


@tool_called_audited("memory_create")
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
    skip_duplicate_check: bool = False,
) -> str:
    """Create a memory. Current persona state (emotion, body_state) is automatically
    snapshotted at creation time. Always call context_update/update_context *before*
    memory_create if your emotional/physical state has changed, so the snapshot
    captures your latest state."""
    if not content:
        return _err("content is required")
    if importance is not None and not (0.0 <= importance <= 1.0):
        return _err("importance must be between 0.0 and 1.0")
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
        return tool_ok({"key": m.key, "auto_emotion": True})

    # Handle duplicate errors with the same response format as before
    if isinstance(result.error, DuplicateMemoryError):
        dup = result.error
        response: dict = {"status": "duplicate", "message": str(dup)}
        if dup.similar_to:
            response["similar_to"] = dup.similar_to
        if dup.duplicate_key:
            response["duplicate_of"] = dup.duplicate_key
        return tool_ok(response)

    return _err(str(result.error))


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
            # Defer enrichment to the idle worker (has_processed guard avoids re-enrich)
            try:
                if not ctx.enrichment_queue.has_processed(m.key):
                    ctx.enrichment_queue.enqueue(m.key)
            except Exception:
                logger.debug("enrichment enqueue failed for %s", m.key, exc_info=True)
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
        return tool_error(
            ToolErrorCode.INTERNAL,
            str(result.error),
        )
    else:
        memories_result = ctx.memory_service.get_recent(limit=limit + offset)
        if memories_result.is_ok:
            items = memories_result.value[offset : offset + limit]
            count_result = ctx.memory_service.count_memories()
            total_count = count_result.value if count_result.is_ok else len(items)
            return tool_ok(
                {
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
                }
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
        return _err(str(memories_result.error))


@tool_called_audited("memory_update")
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
    # query から key を解決（builtin互換・audit:M6: threshold-guarded）
    if query and not memory_key:
        search_result = await ctx.search_engine.search(SearchQuery(text=query, top_k=1))
        if not search_result.is_ok or not search_result.value:
            return _err(f"No memory found for query: {query}")
        item = search_result.value[0]
        mem = item[0] if isinstance(item, tuple) else item
        score = getattr(item, "score", None) if not isinstance(item, tuple) else None
        if not isinstance(score, (int, float)) or score < QUERY_RESOLVE_MIN_SCORE:
            return _err(
                f"Ambiguous match: top score {score} is below {QUERY_RESOLVE_MIN_SCORE}. "
                "Nothing updated. Use the exact memory_key."
            )
        memory_key = getattr(mem, "key", "")
        if not memory_key:
            return _err("memory key not found")

    # builtin からの new_content フォールバック
    if content is None and new_content is not None:
        content = new_content

    if not memory_key:
        return _err("memory_key is required for update")

    # ── Input validation ──
    if content is not None and len(content) > 50000:
        return _err("content too long (max 50000 chars)")

    if importance is not None and not (0.0 <= importance <= 1.0):
        return _err("importance must be between 0.0 and 1.0")

    if emotion is not None and emotion not in _VALID_EMOTIONS:
        return _err(f"invalid emotion: {emotion}")

    if emotion_intensity is not None:
        try:
            emotion_intensity = float(emotion_intensity)
            emotion_intensity = max(0.0, min(1.0, emotion_intensity))
        except (TypeError, ValueError):
            return _err("emotion_intensity must be a number")

    if tags is not None:
        if not isinstance(tags, list):
            return _err("tags must be a list")
        if not all(isinstance(t, str) for t in tags):
            return _err("all tags must be strings")
        if any(len(t) > 100 for t in tags):
            return _err("tag too long (max 100 chars)")

    valid_privacy = {"internal", "private", "public"}
    if privacy_level is not None and privacy_level not in valid_privacy:
        return _err(f"invalid privacy_level: {privacy_level}. Must be: {', '.join(sorted(valid_privacy))}")

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
        return _err("no fields to update")

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
        return tool_ok({"key": memory_key})
    return _err(str(result.error))


@tool_called_audited("memory_delete")
async def _tool_memory_delete(
    ctx: AppContext, persona: str, memory_key: str | None = None, query: str | None = None
) -> str:
    """Delete (tombstone) a memory by key or query. Returns key and content snippet of deleted memory."""
    if not memory_key and not query:
        return "Error: memory_key or query required"

    # If query provided without key, search first (audit:M6: threshold-guarded)
    key = memory_key
    content_preview = "..."
    if not key and query:
        search_result = await ctx.search_engine.search(SearchQuery(text=query, top_k=3))
        if not search_result.is_ok or not search_result.value:
            return tool_error(ToolErrorCode.NOT_FOUND, f"No memory found for query: {query}")
        top = search_result.value[0]
        score = getattr(top, "score", None)
        if not isinstance(score, (int, float)) or score < QUERY_RESOLVE_MIN_SCORE:
            candidates = "\n".join(
                f"- {r.memory.key}: 「{r.memory.content[:60]}」 (score={r.score:.2f})" for r in search_result.value
            )
            return tool_error(
                ToolErrorCode.AMBIGUOUS_MATCH,
                f"Ambiguous match: top score {score} is below {QUERY_RESOLVE_MIN_SCORE}. "
                f"Nothing deleted. Use the exact memory_key, or pick one of:\n{candidates}",
            )
        m = top.memory
        key = m.key
        content_preview = m.content[:100]
        snippet = f"\nContent: 「{m.content[:80]}{'...' if len(m.content) > 80 else ''}」"
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
    profile: str | None = None,
    importance_weight: float = 0.0,
    recency_weight: float = MEMORY_SEARCH_RECENCY_WEIGHT_DEFAULT,
    vector_weight: float = 1.0,
    keyword_weight: float = 0.5,
    kind: str | None = None,
    sort: str | None = None,
) -> str:
    """Search memories with hybrid retrieval. sort: "updated_at" 指定で更新日時降順（最新優先）"""
    if top_k is not None and (top_k < 1 or top_k > 200):
        return _err("top_k must be between 1 and 200")
    top_k = min(top_k or 5, 200)
    # audit:M7 — weight presets replace hand-tuned per-call weights
    if profile is not None:
        presets: dict[str, dict[str, float]] = {
            "recent": {
                "importance_weight": 0.0,
                "recency_weight": 0.4,
                "vector_weight": 0.8,
                "keyword_weight": 0.3,
            },
            "deep": {
                "importance_weight": 0.3,
                "recency_weight": MEMORY_SEARCH_RECENCY_WEIGHT_DEFAULT,
                "vector_weight": 1.0,
                "keyword_weight": 0.5,
            },
        }
        preset = presets.get(profile)
        if preset is None:
            return _err(f"Unknown profile: {profile}. Use 'recent' or 'deep'")
        importance_weight = preset["importance_weight"]
        recency_weight = preset["recency_weight"]
        vector_weight = preset["vector_weight"]
        keyword_weight = preset["keyword_weight"]
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
        return _err(str(result.error))
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
        # audit M3 — metamemory: an empty hit is “I don't find this”, which is
        # distinct from returning something irrelevant. stored_total lets the
        # caller tell “nothing stored at all” from “not in what I know”.
        return tool_ok(
            {"memories": [], "total_count": total_count}, meta={"unknown": True, "stored_total": total_count}
        )
    ctx.memory_service.log_search(query, "hybrid", len(result.value))

    # Boost the top hits (cap 10) and record co-access (cap 3 — don't churn
    # the 20-item co-access window), then queue unprocessed memories for the
    # idle enrichment worker.
    hits: list[SearchResult] = result.value if isinstance(result, Success) else []
    for sr in hits[: min(10, len(hits))]:
        try:
            ctx.memory_service.boost_recall(sr.memory.key)
        except Exception as e:
            logger.warning(f"boost_recall failed: {e}")
    for sr in hits[: min(3, len(hits))]:
        ctx.record_memory_access(sr.memory.key)
    for sr in hits:
        try:
            if not ctx.enrichment_queue.has_processed(sr.memory.key):
                ctx.enrichment_queue.enqueue(sr.memory.key)
        except Exception:
            logger.debug("enrichment enqueue failed for %s", sr.memory.key, exc_info=True)

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
            "created_at": format_iso(m.created_at) if getattr(m, "created_at", None) else None,
            # updated_at = last edit/enrichment time (refreshes without content
            # being new). Freshness questions should use created_at / age.
            "updated_at": format_iso(m.updated_at) if getattr(m, "updated_at", None) else None,
            # age is anchored on created_at (updated_at refreshes on enrichment edits)
            "age": relative_time_str(m.created_at) if getattr(m, "created_at", None) else None,
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
    return tool_ok({"memories": memories, "total_count": total_count})


def _compute_retrievability_health(ctx: AppContext) -> dict | None:
    """audit M3 — metamemory health: how much of the store is retrievable *now*.

    Averages the FSRS R(t) of every stored strength row; the label is the plain
    operational read of that number (healthy / decaying / critical). None when
    nothing is stored yet — “no data” is not “healthy”.
    """
    try:
        res = ctx.memory_repo.get_all_strengths()
        if not res.is_ok or not res.value:  # type: ignore[union-attr]
            return None
        now = get_now()
        # Stored timestamps may be naive or aware depending on when they were
        # written; compare both sides in the same frame (decay_worker does the same).
        if now.tzinfo is not None:
            now = now.replace(tzinfo=None)
        values: list[float] = []
        for strength in res.value:  # type: ignore[union-attr]
            last = getattr(strength, "last_decay", None) or getattr(strength, "last_recall", None)
            if not isinstance(last, datetime):
                # Never decayed/recalled: still fully retrievable, and a malformed
                # stored value must not be mistaken for a real timestamp.
                values.append(1.0)
                continue
            if getattr(last, "tzinfo", None) is not None:
                last = last.replace(tzinfo=None)
            elapsed_hours = max(0.0, (now - last).total_seconds() / 3600.0)
            values.append(float(strength.compute_recall(elapsed_hours)))
        if not values:
            return None
        avg = sum(values) / len(values)
        label = "healthy" if avg >= 0.7 else "decaying" if avg >= 0.4 else "critical"
        return {"average_retrievability": round(avg, 3), "label": label, "counted": len(values)}
    except Exception:
        logger.debug("retrievability health failed", exc_info=True)
        return None


async def _tool_memory_stats(ctx: AppContext, persona: str, top_n: int = 20) -> str:
    """Get memory statistics."""
    result = ctx.memory_service.get_stats(top_n=top_n)
    if result.is_ok:
        # audit M3 — metamemory health. Merged only when stats is a mapping so
        # non-dict payloads keep their shape.
        health = _compute_retrievability_health(ctx)
        if health is not None and isinstance(result.value, dict):
            stats: object = {**result.value, "retrievability_health": health}
        else:
            stats = result.value
        result_text = tool_ok(stats)
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
