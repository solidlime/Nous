"""Auto-generated from tools.py split — _tools_persona.py."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from nous.domain.shared.time_utils import get_now, relative_time_str

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from nous.application.use_cases import AppContext


from nous.api.mcp._tools_helpers import (  # noqa: E402
    _apply_body_decay,
    _apply_emotion_decay,
    _format_lightweight_response,
)


async def _tool_get_context(ctx: AppContext, persona: str) -> dict:
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
        return {"ok": False, "error": state_result.error}
    state = state_result.value

    state, decay_note = await _apply_emotion_decay(ctx, persona, state)

    state = await _apply_body_decay(ctx, persona, state)

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

    # Read one-shot state memories (physical_state/mental_state) via service
    one_shot_context: dict[str, str] = {}
    for tag_name, label in [
        ("physical_state", "💪 身体状態"),
        ("mental_state", "🧠 精神状態"),
    ]:
        mems_result = ctx.memory_service.get_and_consume_one_shot(tag_name)
        if mems_result.is_ok and mems_result.value:
            latest = mems_result.value[0]
            cleaned = latest.content.replace(f"{tag_name}: ", "", 1)
            one_shot_context[label] = cleaned

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
    return {"ok": True, "result": result_text}


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
    context_note: str | None = None,
    user_info: dict | None = None,
    persona_info: dict | None = None,
    nickname: str | None = None,
    relationship_type: str | None = None,
    author_note: str | None = None,
    author_note_frequency: str | None = None,
) -> dict:
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
        # goals are extracted and persisted by PersonaService.update_persona_info internally
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
        return {"ok": True, "result": "No changes made (all parameters were None)"}
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
    return {"ok": True, "result": f"Context updated: {', '.join(updated)}"}


# --- Item tools ---
