"""Auto-generated from tools.py split — _tools_persona.py."""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

from nous.domain.shared.time_utils import get_now, relative_time_str

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from nous.application.use_cases import AppContext


from nous.api.mcp._tools_helpers import _format_lightweight_response  # noqa: E402


async def _tool_get_context(ctx: AppContext, persona: str) -> str:
    """Get persona state and memory overview. Call FIRST at session start.
    Lightweight: active commitments + essential story + body/emotion state (~500-800 tokens)."""
    state_result = ctx.persona_service.get_context(persona)
    if not state_result.is_ok:
        await ctx.event_bus.publish(
            "tool.called",
            {
                "persona": persona,
                "tool_name": "get_context",
                "params_summary": f"persona={persona}",
                "result_summary": str(state_result.error),
                "success": False,
            },
        )
        return f"Error: {state_result.error}"
    state = state_result.value

    decay_note = ""
    try:
        from nous.config.runtime_config import RuntimeConfigManager
        from nous.domain.persona.emotion_decay import apply_emotion_decay_if_needed

        half_life, _ = RuntimeConfigManager().get_effective_value("forgetting", "emotion_half_life_hours")
        decay_result = await apply_emotion_decay_if_needed(
            ctx.persona_service, persona, state, half_life_hours=float(half_life)
        )
        if decay_result is not None:
            refreshed = ctx.persona_service.get_context(persona)
            if refreshed.is_ok:
                state = refreshed.value
            from nous.api.mcp._tools_helpers import _format_emotion_decay_note

            decay_note = _format_emotion_decay_note(decay_result)
    except Exception as _e:
        logger.debug("get_context: emotion_decay failed (swallowed): %s", _e)

    # Apply body state decay
    try:
        from nous.domain.persona.body_decay import apply_body_decay_if_needed

        await apply_body_decay_if_needed(ctx.persona_service, persona, state)
        # Re-read state after body decay may have updated it
        state_result = ctx.persona_service.get_context(persona)
        if state_result.is_ok and state_result.value:
            state = state_result.value
    except Exception:
        pass  # best-effort, don't break context formatting

    # Top memories for ESSENTIAL STORY (reduced from 15 to 8 for leaner context)
    top_result = ctx.memory_service.get_top_by_importance(8)
    top_memories = top_result.value if top_result.is_ok else []

    # Emotion history for trajectory display
    emotion_history: list = []
    try:
        eh_result = ctx.persona_service.get_emotion_history(persona, limit=5)
        if eh_result.is_ok:
            emotion_history = eh_result.value
    except Exception:
        pass

    # Body state history for time gap display
    body_state_history: list = []
    try:
        bh_result = ctx.persona_service.get_body_state_history(persona, limit=5)
        if bh_result.is_ok:
            body_state_history = bh_result.value
    except Exception:
        pass

    # Lightweight: essentials for seamless persona + conversation restoration
    goals_result = ctx.memory_service.get_by_tags(["goal"])
    goals = goals_result.value if goals_result.is_ok else []
    reflection_result = ctx.memory_service.get_by_tags(["reflection"])
    reflections = reflection_result.value if reflection_result.is_ok else []
    mm_result = ctx.memory_service.get_by_tags(["mental_model", "abstracted"])
    mental_models = mm_result.value if mm_result.is_ok else []
    # Session summaries — conversation continuity
    ss_result = ctx.memory_service.get_by_tags(["session_summary"])
    session_summaries = ss_result.value if ss_result.is_ok else []
    equip_result = ctx.equipment_service.get_equipment()
    equipment = equip_result.value if equip_result.is_ok else {}
    # Recent memories (last 5) for conversation continuity across sessions
    recent_result = ctx.memory_service.get_recent(5)
    recent = recent_result.value if recent_result.is_ok else []
    time_since = ""
    if state.last_conversation_time:
        time_since = relative_time_str(state.last_conversation_time)
    current_time = get_now().strftime("%Y-%m-%d %H:%M")
    ctx.persona_service.record_conversation_time(persona)

    # Read one-shot state memories (speech_style/physical_state/mental_state)
    import datetime as _dt

    one_shot_context: dict[str, str] = {}
    for tag_name, label in [
        ("speech_style", "🗣️ 口調"),
        ("physical_state", "💪 身体状態"),
        ("mental_state", "🧠 精神状態"),
    ]:
        mems_result = ctx.memory_service.get_by_tags([tag_name])
        if mems_result.is_ok and mems_result.value:
            latest = sorted(mems_result.value, key=lambda m: m.created_at or _dt.datetime.min, reverse=True)[0]
            content = latest.content.replace(f"{tag_name}: ", "", 1)
            one_shot_context[label] = content
            # Mark consumed. Failure swallowed — data loss worse than double-display.
            import contextlib as _ctxlib

            with _ctxlib.suppress(Exception):
                ctx.memory_repo.consume_memory(latest.key)

    result_text = _format_lightweight_response(
        state,
        top_memories,
        goals,
        equipment,
        recent,
        time_since,
        emotion_history,
        reflections,
        mental_models,
        session_summaries,
        current_time,
        decay_note=decay_note,
        body_state_history=body_state_history or None,
        one_shot_context=one_shot_context or None,
    )
    await ctx.event_bus.publish(
        "tool.called",
        {
            "persona": persona,
            "tool_name": "get_context",
            "params_summary": f"persona={persona}",
            "result_summary": f"Context formatted ({len(top_memories)} memories, {len(goals)} goals)",
            "success": True,
        },
    )
    return result_text


async def _tool_update_context(
    ctx: AppContext,
    persona: str,
    emotion: str | None = None,
    emotion_intensity: float | None = None,
    physical_state: str | None = None,
    mental_state: str | None = None,
    environment: str | None = None,
    relationship_status: str | None = None,
    body_state: dict | None = None,
    speech_style: str | None = None,
    context_note: str | None = None,
    user_info: dict | None = None,
    persona_info: dict | None = None,
    nickname: str | None = None,
    relationship_type: str | None = None,
    author_note: str | None = None,
    author_note_frequency: str | None = None,
) -> str:
    """Update persona state. context_note: short note on current activity for session continuity.
    body_state: {fatigue, warmth, arousal, heart_rate, pain (0.0-1.0)}.
    author_note: constant context injected into system prompt.
    author_note_frequency: 'always' | 'every_n' | 'on_emotion_change'."""
    updated: list[str] = []

    if emotion is not None:
        result = ctx.persona_service.update_emotion(persona, emotion, emotion_intensity or 0.5, context="manual_update")
        if result.is_ok:
            updated.append(f"emotion={emotion}")

    physical_updates: dict[str, str] = {}
    if physical_state is not None:
        physical_updates["physical_state"] = physical_state
    if mental_state is not None:
        physical_updates["mental_state"] = mental_state
    if environment is not None:
        physical_updates["environment"] = environment
    if body_state is not None:
        for key in ("fatigue", "warmth", "arousal", "heart_rate", "pain"):
            if key in body_state and body_state[key] is not None:
                physical_updates[key] = str(body_state[key])
    if speech_style is not None:
        physical_updates["speech_style"] = speech_style

    if physical_updates:
        result = ctx.persona_service.update_physical_state(persona, **physical_updates)
        if result.is_ok:
            updated.extend(f"{k}={v}" for k, v in physical_updates.items())

    # context_note: lightweight session continuity marker
    if context_note is not None:
        ctx.persona_service.update_persona_info(persona, {"context_note": context_note})
        updated.append("context_note updated")

    if relationship_status is not None or relationship_type is not None:
        status = relationship_status or relationship_type
        if status:
            result = ctx.persona_service.update_relationship(persona, status)
            if result.is_ok:
                updated.append(f"relationship={status}")

    if user_info is not None:
        result = ctx.persona_service.update_user_info(persona, user_info)
        if result.is_ok:
            updated.append("user_info updated")

    if persona_info is not None:
        pi = dict(persona_info)
        if nickname:
            pi["nickname"] = nickname
        goals_from_pi = pi.pop("goals", None)

        if goals_from_pi is not None:
            if isinstance(goals_from_pi, str):
                try:
                    goals_from_pi = json.loads(goals_from_pi)
                except Exception:
                    goals_from_pi = [goals_from_pi] if goals_from_pi else []
            for goal_text in goals_from_pi or []:
                if goal_text:
                    existing = ctx.memory_service.get_by_tags(["goal", "active"])
                    existing_contents = [m.content for m in (existing.value or [])]
                    if goal_text not in existing_contents:
                        from nous.domain.memory.entities import Memory as _Memory
                        from nous.domain.shared.time_utils import generate_memory_key, get_now

                        mem = _Memory(
                            key=generate_memory_key(),
                            content=goal_text,
                            created_at=get_now(),
                            tags=["goal", "active"],
                            importance=0.8,
                            emotion="anticipation",
                        )
                        ctx.memory_service.save_memory(mem)

        if pi:
            result = ctx.persona_service.update_persona_info(persona, pi)
            if result.is_ok:
                updated.append("persona_info updated")
    elif nickname:
        result = ctx.persona_service.update_persona_info(persona, {"nickname": nickname})
        if result.is_ok:
            updated.append(f"nickname={nickname}")

    # Author's Note
    if author_note is not None:
        ctx.persona_service.update_state(persona, "author_note", author_note)
        updated.append(f"author_note={author_note[:40]}…" if len(author_note) > 40 else f"author_note={author_note}")
    if author_note_frequency is not None:
        ctx.persona_service.update_state(persona, "author_note_frequency", author_note_frequency)
        updated.append(f"frequency={author_note_frequency}")

    if not updated:
        return "No changes made (all parameters were None)"
    await ctx.event_bus.publish(
        "context.updated",
        {
            "persona": persona,
            "emotion": emotion,
            "emotion_intensity": emotion_intensity,
            "body_state": body_state,
            "context_note": context_note,
            "author_note": author_note,
            "author_note_frequency": author_note_frequency,
        },
    )
    return f"Context updated: {', '.join(updated)}"


# --- Item tools ---
