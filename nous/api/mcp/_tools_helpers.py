"""Auto-generated from tools.py split — _tools_helpers.py."""

from __future__ import annotations

import difflib
import functools
import json
import logging
import re
import unicodedata
from typing import TYPE_CHECKING, ParamSpec, TypeVar, cast

from nous.domain.persona.emotion_trend import clean_context
from nous.domain.shared.time_utils import relative_time_str

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from nous.application.use_cases import AppContext
    from nous.domain.persona.emotion_decay import EmotionDecayResult
    from nous.domain.persona.entities import PersonaState

P = ParamSpec("P")
R = TypeVar("R")

logger = logging.getLogger(__name__)

_DEFAULT_METRIC_LABELS = {
    "fatigue": "fatigue",
    "warmth": "warmth",
    "arousal": "arousal",
    "heart_rate": "heart",
    "pain": "pain",
}

# 近傍重複（paraphrase）の表示側threshold。保守的に 0.85 を維持する:
# 実測 fixture（chezmoi 5連）の最強ペア 3-5=0.8589 だけが落ち、次点 2-3=0.3626 とは
# 明確な余白がある。文字列類似 (difflib) は意味的同一性を測る道具ではないため、
# 閾値を下げて「意味的同一」を偽装するのは将来の誤圧縮リスクが高い。
# 近傍重複の根本対策は書き込み側 duplicate check（memory_create の skip_duplicate_check 運用）であり、
# 表示側は文字列レベルで明らかな重複の除去までを担当する。
_NEAR_DUP_THRESHOLD = 0.85


# ── tool.called self-publication (F3 invariant) ──
# Invariant: MCP tools publish their own tool.called events on ALL paths;
# ToolRegistry skips MCP tools.  Tools that already publish inline
# (memory_read/search/stats, get_context, goal_manage, item_*) keep their
# rich summaries; the 5 tools below had zero self-publication and use the
# audited wrapper to guarantee coverage on every success/failure path.


def _tool_called_result_success(result: object) -> bool:
    """Classify a tool return value as success/failure (audit C1: structural).

    Envelope payloads (``{ok, data, error}``) are the primary contract — the
    ``ok`` field is the signal. Legacy plain-text strings keep prefix
    heuristics for pre-envelope results emitted inside core functions.
    """
    from nous.api.mcp._envelope import parse_envelope

    envelope = parse_envelope(result)
    if envelope is not None:
        return bool(envelope.get("ok"))
    if isinstance(result, dict):
        if "success" in result:
            return bool(result["success"])
        if "ok" in result:
            return bool(result["ok"])
        if "status" in result:
            return bool(result["status"] == "ok")
        return True
    if isinstance(result, str):
        try:
            payload = json.loads(result)
        except ValueError:
            payload = None
        if isinstance(payload, dict):
            return _tool_called_result_success(payload)
        return not (
            result.startswith("Error") or result.startswith("No memory") or result.startswith("Ambiguous match")
        )
    return True


def _tool_called_result_summary(result: object) -> str:
    """Extract a human-readable summary from a tool return value."""
    if isinstance(result, str):
        try:
            payload = json.loads(result)
        except ValueError:
            payload = None
        if isinstance(payload, dict):
            result = payload
        else:
            return str(result)
    if isinstance(result, dict):
        for key in ("result_summary", "result", "error", "message"):
            if result.get(key):
                return str(result[key])
        return ""
    return str(result)


def _truncate_event_text(value: object, limit: int) -> str:
    """切る場合は末尾に … を付ける（切れた生JSONをそのまま見せない）。"""
    text = str(value)
    return text if len(text) <= limit else text[: max(0, limit - 1)] + "…"


async def _emit_tool_called(
    ctx: AppContext,
    tool_name: str,
    result_summary: str,
    success: bool,
    params_summary: str = "",
    error: str | None = None,
    source: str = "direct",
    persona: str = "",
    session_id: str = "",
) -> None:
    """Publish a tool.called event (best-effort — never breaks the tool flow)."""
    try:
        data: dict = {
            "tool_name": tool_name,
            "params_summary": _truncate_event_text(params_summary, 200),
            "result_summary": _truncate_event_text(result_summary, 80),
            "success": success,
            # session_id は明示指定を優先。内省などセッション外は "introspection" を
            # 渡し、Activity で "unknown" に混ざらないようにする。
            "session_id": session_id or getattr(ctx, "session_id", None),
            # 呼び出し元の識別子。通常ツールは "direct"、内省 curiosity は
            # "introspection" を渡し、フロントが二重表示を排他できるようにする (spec C)。
            "source": source,
        }
        # persona は str の時だけ載せる (後方互換: 未指定なら recorder は "unknown")。
        # MagicMock 等の非 str は載せない（SQLite bind 不能で記録落ちするため）。
        if isinstance(persona, str) and persona:
            data["persona"] = persona
        if error:
            data["error"] = error
        # source は data 直下（front のライブフィルタ用）に加え metadata にも載せる。
        # recorder は metadata_json しか保存しないため、これで履歴側でも識別可能になる。
        data["metadata"] = {"source": source}
        await ctx.event_bus.publish("tool.called", data)
    except Exception:
        logger.warning("tool.called publication failed for %s", tool_name, exc_info=True)


def tool_called_audited(
    tool_name: str,
) -> Callable[[Callable[P, Awaitable[R]]], Callable[P, Awaitable[R]]]:
    """Decorator: guarantee tool.called publication on all paths of an MCP tool.

    Success/failure is classified from the return value; exceptions emit a
    failure event and re-raise. Generic over the wrapped signature (ParamSpec)
    so return-type annotations (str/dict) survive decoration.
    """

    def deco(fn: Callable[P, Awaitable[R]]) -> Callable[P, Awaitable[R]]:
        @functools.wraps(fn)
        async def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            ctx = cast("AppContext", args[0] if args else kwargs["ctx"])
            params_summary = str(kwargs)
            # persona を付与して recorder が "unknown" 行にしない (Activity 帰属)。
            persona = getattr(ctx, "persona", "")
            if not isinstance(persona, str):
                persona = ""
            try:
                result = await fn(*args, **kwargs)
            except Exception as e:
                await _emit_tool_called(
                    ctx, tool_name, str(e), success=False, params_summary=params_summary, error=str(e), persona=persona
                )
                raise
            await _emit_tool_called(
                ctx,
                tool_name,
                _tool_called_result_summary(result),
                _tool_called_result_success(result),
                params_summary=params_summary,
                persona=persona,
            )
            return result

        return wrapper

    return deco


def _format_body_metrics(state: PersonaState, labels: dict[str, str] | None = None) -> str:
    """身体メトリクスを 'fatigue:40% | warmth:74% | ...' 形式で返す。
    labels でラベルをカスタマイズ可能。デフォルトは英語ラベル。"""
    resolved = _DEFAULT_METRIC_LABELS if labels is None else labels
    parts = []
    for key, label in resolved.items():
        val = getattr(state, key, None)
        if val is not None:
            parts.append(f"{label}:{val:.0%}" if isinstance(val, (int, float)) else f"{label}:{val}")
    return " | ".join(parts)


def _format_state_block(state: PersonaState) -> str:
    """Format body + emotions + action + speech as compact state block."""
    lines = ["📊 CURRENT STATE"]

    # Body line
    body_str = _format_body_metrics(state)
    if body_str:
        lines.append(f"  Body  : {body_str}")

    # Mind (emotions) line
    if state.emotion:
        lines.append(f"  Mind  : {state.emotion}:{state.emotion_intensity:.2f}")

    return "\n".join(lines)


def _format_emotion_decay_note(decay_result: EmotionDecayResult | None) -> str:
    """自然言語の減衰通知。ペルソナの主観的体験として表現する。"""
    if decay_result is None:
        return ""
    before = decay_result.before_emotion
    after = decay_result.after_emotion
    hours = decay_result.elapsed_hours

    if hours >= 24:
        time_str = f"{hours / 24:.0f}日"
    elif hours >= 1:
        time_str = f"{hours:.0f}時間"
    else:
        time_str = f"{hours * 60:.0f}分"

    if after == "neutral" or decay_result.after_intensity < 0.01:
        return f"{time_str}の間に、{before}の感情は減衰して消失した"
    else:
        return f"{time_str}の間に、{before}の感情は減衰した（現在の強度: {after}）"


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


def _normalize_content(text: str) -> str:
    """内容ベース dedupe 用の正規化。NFKC → 空白列圧縮 → lowercase → 先頭の日時トークン除去 → strip。
    本文中の日時・スコア（3:2 等）は正当な差異なので保持する。
    ただし内容先頭の意味を持つ日付（例: 「2026-09-30 にリリースする予定」）も除去される——
    ログ接頭辞タイムスタンプの除去を優先した設計上の許容。"""
    t = unicodedata.normalize("NFKC", str(text))
    t = re.sub(r"\s+", " ", t)
    t = t.lower()
    mid = t.strip()
    # 内容先頭の日付（+時間）トークンのみ除去。本文中の日時は消さない。
    # [ tT]: lower() 済みだが T 接続（ISO 8601）も確実にアンカーするため大文字も許容
    t = re.sub(r"^\s*\[?\d{4}-\d{2}-\d{2}([ tT]\d{1,2}:\d{2})?\]?\s*", "", mid)
    t = t.strip()
    # 内容が裸の日時のみで正規化が空になった場合は、日時除去前の文字列に fallback
    return t if t else mid


def _dedupe_memories(memories: list, seen_normalized: set[str]) -> list:
    """正規化内容の完全一致で重複を排除。通過した分を seen_normalized に追加（破壊的更新で節間共有）。"""
    out: list = []
    for m in memories:
        norm = _normalize_content(m.content)
        if norm in seen_normalized:
            continue
        seen_normalized.add(norm)
        out.append(m)
    return out


def _collapse_near_duplicates(
    memories: list,
    threshold: float = _NEAR_DUP_THRESHOLD,
    seen_normalized: set[str] | None = None,
) -> list:
    """同一リスト内で SequenceMatcher ratio >= threshold の組は前方（古い方）を残し後方を落とす。
    O(n²)（n<=20程度の想定）。落とした項目の正規化済み内容も seen_normalized に登録し、
    後続節の完全一致 dedupe が素通りしないようにする。"""
    kept_norm: list[str] = []
    out: list = []
    for m in memories:
        norm = _normalize_content(m.content)
        if any(difflib.SequenceMatcher(None, n, norm).ratio() >= threshold for n in kept_norm):
            # 落とした項目の norm を seen に登録し、後続節の完全一致が素通りしないようにする。
            # ただし kept 内と完全一致する norm は、残った前方項目が dedupe 側で seen に登録するので
            # ここで登録すると前方項目まで消えてしまう（同一 norm は重複登録しない）。
            if seen_normalized is not None and norm and norm not in kept_norm:
                seen_normalized.add(norm)
            continue
        kept_norm.append(norm)
        out.append(m)
    return out


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
    project_memories: list | None = None,
    project_name: str | None = None,
    due_labels: dict[str, str] | None = None,
) -> str:
    """Lightweight context (~700-900 tokens): persona + conversation continuity + body state."""
    lines: list[str] = []

    # 節跨ぎ dedupe 用の正規化済み seen set。節の構築順（active goals → recent →
    # essential story → insights/patterns → summaries → project）で共有する。
    seen: set[str] = set()

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
                ctx_str = clean_context(context)
                return f"{emotion}({ctx_str})" if ctx_str else emotion

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
        active_goals = _dedupe_memories(active_goals, seen)
    if active_goals:
        lines.append("\n⚠️ YOUR ACTIVE COMMITMENTS:")
        for g in active_goals:
            ts = relative_time_str(g.created_at) if getattr(g, "created_at", None) else ""
            ts_str = f" ({ts})" if ts else ""
            # audit M2 — prospective cue: the deadline this commitment fired on
            due = (due_labels or {}).get(getattr(g, "key", ""), "")
            due_str = f" ⏰ {due}" if due else ""
            lines.append(f"  🎯 {g.content[:100]}{ts_str}{due_str}")

    # Recent memories — conversation continuity across sessions
    if recent:
        recent = _collapse_near_duplicates(list(recent), seen_normalized=seen)
        recent = _dedupe_memories(recent, seen)
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
        top_memories = _collapse_near_duplicates(list(top_memories), seen_normalized=seen)
        top_memories = _dedupe_memories(top_memories, seen)
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
            # 各記憶の created_at 基準の相対時刻（updated_at はエンリッチで若返るため錨にしない）
            ts = relative_time_str(m.created_at) if getattr(m, "created_at", None) else ""
            ts_part = f" ({ts})" if ts else ""
            line = f"- {snippet}{tag_part}{ts_part}"
            if used + len(line) > char_budget:
                lines.append(f"  ... ({len(top_memories) - shown} more)")
                break
            lines.append(line)
            used += len(line)

    # ── Provenance (audit C4): one line, derived from source_type ──
    if top_memories:
        modality_counts: dict[str, int] = {}
        for m in top_memories:
            mod = getattr(m, "modality", None)
            if isinstance(mod, str) and mod:
                modality_counts[mod] = modality_counts.get(mod, 0) + 1
        if modality_counts:
            lines.append("Provenance: " + ", ".join(f"{k}={v}" for k, v in sorted(modality_counts.items())))

    # ── Insights: reflection + mental model ──
    if reflections:
        reflections = _dedupe_memories(list(reflections), seen)
    if reflections:
        # リフレクションの各行末に created_at 基準の相対時刻を付与
        lines.append("\n--- Recent Insights ---")
        for r in reflections[:2]:
            if not r.content:
                continue
            ts = relative_time_str(r.created_at) if getattr(r, "created_at", None) else ""
            ts_part = f" ({ts})" if ts else ""
            lines.append(f"💡 {r.content}{ts_part}")
    if mental_models:
        mental_models = _dedupe_memories(list(mental_models), seen)
        patterns = [m.content for m in mental_models[:2] if m.content]
        if patterns:
            lines.append("\n--- Behavior Patterns ---")
            for p in patterns:
                # 集約概念に単一時刻を与えると誤った時間性を持たせるため、時刻は付けない
                lines.append(f"🧩 {p}")
    if session_summaries:
        # collapse は上限つきスライスに限定（全件 collapse は履歴蓄積で非有界になるため）
        session_summaries = _collapse_near_duplicates(list(session_summaries[:20]), seen_normalized=seen)
        session_summaries = _dedupe_memories(session_summaries, seen)
    if session_summaries:
        # サマリーの各行末に created_at 基準の相対時刻を付与
        lines.append("\n--- Recent Summaries ---")
        for s in session_summaries[:2]:
            if not s.content:
                continue
            ts = relative_time_str(s.created_at) if getattr(s, "created_at", None) else ""
            ts_part = f" ({ts})" if ts else ""
            lines.append(f"📝 {s.content}{ts_part}")

    # ── Project memories（project:<slug> タグ付きの直近記憶）──
    project_memories = _dedupe_memories(project_memories or [], seen)
    if project_memories:
        slug = project_name or ""
        lines.append(f"\n--- PROJECT MEMORIES (project:{slug}) ---")
        for m in project_memories:
            snippet = m.content.replace("\n", " ")
            if len(snippet) > 400:
                snippet = snippet[:400].rstrip() + "… (full via memory_read: " + m.key + ")"
            ts = relative_time_str(m.created_at) if getattr(m, "created_at", None) else ""
            ts_str = f" ({ts})" if ts else ""
            lines.append(f"- {snippet}{ts_str}")

    lines.append("\n💡 Use memory_search() for deeper context on specific topics.")
    return "\n".join(lines)


async def _apply_emotion_decay(ctx: AppContext, persona: str, state: PersonaState) -> tuple[PersonaState, str]:
    """感情減衰を適用し、(更新後state, decay_note) を返す。
    減衰不要の場合は (state, "") を返す。"""
    decay_note = ""
    try:
        from nous.domain.persona.emotion_decay import apply_emotion_decay_if_needed

        # Read decay params from ToolConfig (via ChatConfig if available)
        half_life_hours: float | None = None
        threshold: float | None = None
        neutral_threshold: float | None = None
        if hasattr(ctx, "_config") and ctx._config is not None:
            tc = getattr(ctx._config, "tool_config", None)
            if tc is not None:
                half_life_hours = getattr(tc, "emotion_decay_half_life_hours", None)
                threshold = getattr(tc, "emotion_decay_threshold", None)
                neutral_threshold = getattr(tc, "emotion_neutral_threshold", None)

        decay_result = await apply_emotion_decay_if_needed(
            ctx.persona_service,
            persona,
            state,
            half_life_hours=half_life_hours,
            threshold=threshold,
            neutral_threshold=neutral_threshold,
        )
        if decay_result is not None:
            refreshed = ctx.persona_service.get_context(persona)
            if refreshed.is_ok:
                state = refreshed.value
            decay_note = _format_emotion_decay_note(decay_result)
    except Exception as _e:
        logger.debug("_apply_emotion_decay failed (swallowed): %s", _e)
    return state, decay_note


async def _apply_relationship_decay(ctx: AppContext, persona: str, state: PersonaState) -> str:
    """関係性減衰ノートを生成。放置時間に応じて関係性の冷め具合を表現する文字列を返す。
    PersonaStateへの永続化は行わない（プロンプト注入のみ）。"""
    try:
        from nous.domain.shared.time_utils import get_now

        last_conv = getattr(state, "last_conversation_time", None)
        if last_conv is None:
            return ""
        now = get_now()
        if last_conv.tzinfo is None and now.tzinfo is not None:
            last_conv = last_conv.replace(tzinfo=now.tzinfo)
        elapsed_hours = (now - last_conv).total_seconds() / 3600.0
        if elapsed_hours < 3:
            return ""
        if elapsed_hours < 24:
            return f"時間経過（{elapsed_hours:.0f}時間）により、関係性がわずかに希薄化している"
        if elapsed_hours < 168:
            return f"時間経過（{elapsed_hours / 24:.0f}日）により、関係性がやや希薄化している"
        if elapsed_hours < 720:
            return f"時間経過（{elapsed_hours / 24:.0f}日）により、関係性が大きく減衰している"
        return f"長時間の放置（{elapsed_hours / 720:.0f}ヶ月）により、関係性がほぼ消失している"
    except Exception:
        return ""


async def _apply_body_decay(ctx: AppContext, persona: str, state: PersonaState) -> PersonaState:
    """身体減衰をベストエフォートで適用し、更新後stateを返す。失敗時は元のstate。"""
    try:
        from nous.domain.persona.body_decay import apply_body_decay_if_needed

        await apply_body_decay_if_needed(ctx.persona_service, persona, state)
        state_result = ctx.persona_service.get_context(persona)
        if state_result.is_ok and state_result.value:
            state = state_result.value
    except Exception:
        logger.warning(
            "_apply_body_decay: body decay failed for persona '%s', returning un-decayed state",
            persona,
            exc_info=True,
        )  # best-effort, don't break caller
    return state
