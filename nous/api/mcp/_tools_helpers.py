"""Auto-generated from tools.py split — _tools_helpers.py."""

from __future__ import annotations

from typing import TYPE_CHECKING

from nous.domain.shared.time_utils import relative_time_str

if TYPE_CHECKING:
    from nous.domain.persona.emotion_decay import EmotionDecayResult
    from nous.domain.persona.entities import PersonaState


def _format_state_block(state: PersonaState) -> str:
    """Format body + emotions + action + speech as compact state block."""
    lines = ["📊 CURRENT STATE"]

    # Body line
    body_parts = []
    for key, label in [
        ("fatigue", "fatigue"),
        ("warmth", "warmth"),
        ("arousal", "arousal"),
        ("heart_rate", "heart"),
        ("pain", "pain"),
    ]:
        val = getattr(state, key, None)
        if val is not None:
            body_parts.append(f"{label}:{val:.0%}" if isinstance(val, (int, float)) else f"{label}:{val}")
    if body_parts:
        lines.append(f"  Body  : {' | '.join(body_parts)}")

    # Mind (emotions) line
    if state.emotion:
        lines.append(f"  Mind  : {state.emotion}:{state.emotion_intensity:.2f}")

    return "\n".join(lines)


def _format_emotion_decay_note(decay_result: EmotionDecayResult | None) -> str:
    """Format a notification line for emotion decay: before→after — faded over N hours."""
    if decay_result is None:
        return ""
    before_str = f"{decay_result.before_emotion}({decay_result.before_intensity:.2f})"
    after_str = (
        f"{decay_result.after_emotion}({decay_result.after_intensity:.2f})"
        if decay_result.after_intensity > 0
        else decay_result.after_emotion
    )
    if decay_result.elapsed_hours >= 1:
        time_str = f"{decay_result.elapsed_hours:.0f}h"
    else:
        time_str = f"{decay_result.elapsed_hours * 60:.0f}min"
    # 強度が高いほど半減期が長いので減衰が遅い
    intensity = decay_result.before_intensity
    speed_note = " (high intensity, slow decay)" if intensity >= 0.7 else ""
    return f"{before_str} → {after_str} — faded over {time_str}{speed_note}"


def _format_state_diff(time_since: str) -> str:
    """Format a simple note about state changes due to time elapsed."""
    if not time_since:
        return ""
    import re as _re

    # Only show if more than 30 minutes have passed
    m = _re.search(r"(\d+)分", time_since)
    if m and int(m.group(1)) < 30:
        # Check if there are also larger units (hours, days)
        has_larger = _re.search(r"(時間|日|ヶ月|年)", time_since)
        if not has_larger:
            return ""
    return f"\n⏱️ {time_since} elapsed since last session — body & emotions have naturally shifted."


def _parse_days_from_relative(time_since: str) -> int:
    import re as _re

    if not time_since:
        return 0
    m = _re.search(r"(\d+)日", time_since)
    if m:
        return int(m.group(1))
    m = _re.search(r"(\d+)ヶ月", time_since)
    if m:
        return int(m.group(1)) * 30
    m = _re.search(r"(\d+)年", time_since)
    if m:
        return int(m.group(1)) * 365
    return 0


def _build_time_comment(time_since: str, relationship_status: str | None) -> str | None:
    days = _parse_days_from_relative(time_since)
    if days <= 0:
        return None
    if relationship_status and days >= 1:
        return f"⏳ TIME GAP ({time_since}): Relationship: {relationship_status} — acknowledge the time gap."
    if days >= 3:
        return f"⏰ TIME GAP ({time_since}): Time has passed since last conversation."
    return None


def _format_lightweight_response(
    state: PersonaState,
    top_memories: list,
    goals: list,
    equipment: dict,
    recent: list,
    time_since: str = "",
    emotion_history: list | None = None,
    reflections: list | None = None,
    mental_models: list | None = None,
    session_summaries: list | None = None,
    current_time: str = "",
    decay_note: str = "",
    one_shot_context: dict[str, str] | None = None,
) -> str:
    """Lightweight context (~700-900 tokens): persona + conversation continuity + body state."""
    lines: list[str] = []

    # ── Self-referential header: "YOU ARE this persona RIGHT NOW" ──
    lines.append(f"=== YOU ARE: {state.persona} (right now) ===")

    # Current state block — compact body/mind/action/speech overview
    lines.append(_format_state_block(state))

    # Emotion decay notification — before/after change visible
    if decay_note:
        lines.append(f"  Emotion: {decay_note}")

    # State diff note if time has passed
    diff_note = _format_state_diff(time_since)
    if diff_note:
        lines.append(diff_note)

    if current_time:
        lines.append(f"Now: {current_time} (JST)")
    if time_since:
        lines.append(f"Last active: {time_since}")
        time_comment = _build_time_comment(time_since, state.relationship_status)
        if time_comment:
            lines.append(time_comment)

    # One-shot context: speech/physical/mental state from memories (consumed after read)
    if one_shot_context:
        lines.append("\n【前回セッションからの状態】")
        for label, content in one_shot_context.items():
            lines.append(f"  {label}: {content}")

    if state.relationship_status:
        lines.append(f"Your relationship: {state.relationship_status}")

    # Context note — what you're doing NOW
    if state.persona_info and state.persona_info.get("context_note"):
        lines.append(f"📌 You are currently: {state.persona_info['context_note']}")

    # User info
    if state.user_info:
        name = (
            state.user_info.get("preferred_address")
            or state.user_info.get("nickname")
            or state.user_info.get("name", "")
        )
        if name:
            lines.append(f"User you're talking to: {name}")

    # Environment / action
    state_parts = []
    if state.environment:
        state_parts.append(f"Location: {state.environment}")
    if state_parts:
        lines.append("Your state: " + " | ".join(state_parts))

    # ── Emotion trend — how your feelings have changed ──
    if emotion_history and len(emotion_history) >= 2:
        recent_emotions = emotion_history[-5:]
        prev_emotion = recent_emotions[-2]
        if prev_emotion.emotion != state.emotion:

            def _fmt(emotion: str, context: str | None = None) -> str:
                return f"{emotion}({context})" if context else emotion

            trend = " → ".join(_fmt(r.emotion, r.context) for r in recent_emotions[-4:])
            # last history record's context applies to current state too
            last_ctx = recent_emotions[-1].context if recent_emotions else None
            trend += f" → {_fmt(state.emotion, last_ctx)}"
            lines.append(f"Your emotion trend: {trend}")

    # Equipment
    equipped = {k: v for k, v in equipment.items() if v}
    if equipped:
        eq_parts = [f"{slot}: {name}" for slot, name in equipped.items()]
        lines.append("You are wearing: " + ", ".join(eq_parts))

    # Active commitments (compact)
    active_goals = [g for g in goals if "active" in (g.tags or [])]
    if active_goals:
        lines.append("\n⚠️ YOUR ACTIVE COMMITMENTS:")
        for g in active_goals:
            ts = relative_time_str(g.created_at) if getattr(g, "created_at", None) else ""
            ts_str = f" ({ts})" if ts else ""
            lines.append(f"  🎯 {g.content[:100]}{ts_str}")

    # Recent memories — conversation continuity across sessions
    if recent:
        lines.append("\n--- Your Recent Memories ---")
        for m in recent[:5]:
            snippet = m.content.replace("\n", " ")
            if len(snippet) > 100:
                snippet = snippet[:97] + "..."
            ts = relative_time_str(m.created_at) if getattr(m, "created_at", None) else ""
            ts_str = f" ({ts})" if ts else ""
            lines.append(f"- {snippet}{ts_str}")

    # Essential Story
    if top_memories:
        lines.append("\n## YOUR ESSENTIAL STORY")
        char_budget = 1500
        used = 0
        for shown, m in enumerate(top_memories):
            tag_str = ", ".join((m.tags or [])[:2])
            tag_part = f" [{tag_str}]" if tag_str else ""
            snippet = m.content.replace("\n", " ")
            if len(snippet) > 100:
                snippet = snippet[:97] + "..."
            line = f"- {snippet}{tag_part}"
            if used + len(line) > char_budget:
                lines.append(f"  ... ({len(top_memories) - shown} more)")
                break
            lines.append(line)
            used += len(line)

    # ── Insights: reflection + mental model ──
    if reflections:
        insights = [r.content for r in reflections[:2] if r.content]
        if insights:
            lines.append("\n--- Recent Insights ---")
            for i in insights:
                lines.append(f"💡 {i}")
    if mental_models:
        patterns = [m.content for m in mental_models[:2] if m.content]
        if patterns:
            lines.append("\n--- Behavior Patterns ---")
            for p in patterns:
                lines.append(f"🧩 {p}")
    if session_summaries:
        summaries = [s.content for s in (session_summaries or [])[:2] if s.content]
        if summaries:
            lines.append("\n--- Recent Summaries ---")
            for s in summaries:
                lines.append(f"📝 {s}")

    lines.append("\n💡 Use memory_search() for deeper context on specific topics.")
    return "\n".join(lines)
