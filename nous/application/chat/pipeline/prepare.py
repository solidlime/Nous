"""PrepareStep: ターン開始時の準備（感情減衰 + コンテキスト取得 + 記憶検索）。"""

from __future__ import annotations

import asyncio
import math
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from nous.domain.memory.recall_annotator import RecallAnnotator
from nous.domain.persona.emotion_decay import apply_emotion_decay_if_needed
from nous.domain.search.engine import SearchQuery
from nous.domain.shared.time_utils import get_now, relative_time_str
from nous.infrastructure.logging.structured import get_logger

if TYPE_CHECKING:
    from nous.application.chat.pipeline.context import ChatTurnContext
    from nous.application.chat.session_store import SessionWindow
    from nous.application.use_cases import AppContext
    from nous.domain.chat_config import ChatConfig

logger = get_logger(__name__)

_RECENCY_LAMBDA = 0.5  # half-life ≈ 1.4 days

RECALL_ANNOTATION_GUIDELINES = """
## Memory Recall Annotations
Each recalled memory includes annotations: [certainty: X, time: Y, source: Z, kind: W].
Use these as hints for natural recall expression — not as literal text to output.

(Examples below include English and Japanese phrases for multilingual reference.
Use whichever matches your persona's natural language — never copy-paste.)

### Certainty hints:
- confident → Recall with assertion. No hedging needed.
- tentative → Use hedging: "I think...", "たしか...", etc. in your persona's voice.
- vague → Use stronger hedging: "I vaguely remember...", "〜だった気がする...", etc.
- forgotten → Do NOT mention this memory (should_mention is false).

### Time hints:
- recent / days_7 → "just now", "the other day", "さっき", "この前"
- days_30 → "a while ago", "こないだ"
- days_90 → "a few months back", "前に"
- years → "long ago", "昔"

### Source hints:
- user_stated → Recall with confidence (user said it directly).
- llm_inferred → Slightly hedged (inferred, not explicitly stated).
- reflected → Express as an insight: "Thinking about it...", "考えてみると..."
- consolidated → Express as a summary of multiple memories.

### Kind hints:
- episodic → Include time/place context if available.
- semantic → State as fact or preference.
- prospective → Frame as future intention or reminder.

IMPORTANT:
- Express everything naturally in your persona's voice.
- NEVER output the annotation labels themselves.
- NEVER say "database", "retrieved", "record", "search result" or any technical term.
"""


def _compute_recency_decay(created_at: datetime | None) -> float:
    """Compute recency decay: exp(-λ * days_elapsed) with λ=0.5."""
    if created_at is None:
        return 0.5
    now = datetime.now(tz=UTC)
    # Ensure tz-aware comparison
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=UTC)
    days_elapsed = max(0.0, (now - created_at).total_seconds() / 86400.0)
    return math.exp(-_RECENCY_LAMBDA * days_elapsed)


async def _search_memories(
    ctx: AppContext,
    user_message: str,
    last_assistant: str | None,
    config: ChatConfig,
    top_k: int = 8,
) -> tuple[str, dict, list]:
    """2クエリ並行検索 + 複合スコアリングマージ。

    Returns:
        (formatted_str, debug_info, memories_list)
    """
    recency_w: float = getattr(config, "retrieval_recency_weight", 0.3)
    importance_w: float = getattr(config, "retrieval_importance_weight", 0.3)
    relevance_w: float = getattr(config, "retrieval_relevance_weight", 0.4)

    queries = [user_message]
    if last_assistant:
        queries.append(last_assistant[:200])

    async def _run(q: str) -> list:
        try:
            result = await ctx.search_engine.search(SearchQuery(text=q, top_k=top_k))
            return result.value if result.is_ok else []
        except Exception as e:
            logger.warning("search_memory failed (query=%s): %s", q[:40], e)
            return []

    results = await asyncio.gather(*[_run(q) for q in queries])

    # Collect all candidates with RRF position scores per content
    seen: set[str] = set()
    mem_by_content: dict[str, object] = {}
    rrf_scores: dict[str, float] = {}

    for _rank_idx, result_list in enumerate(results):
        for pos, item in enumerate(result_list):
            if isinstance(item, tuple):
                mem = item[0]
            elif hasattr(item, "memory"):
                mem = item.memory
            else:
                mem = item
            content = getattr(mem, "content", str(mem))
            rrf_score = 1.0 / (60 + pos + 1)
            if content in seen:
                rrf_scores[content] = rrf_scores.get(content, 0.0) + rrf_score
            else:
                seen.add(content)
                mem_by_content[content] = mem
                rrf_scores[content] = rrf_score

    # Compute composite score for each unique memory
    scored: list[tuple[float, object]] = []
    for content, mem in mem_by_content.items():
        importance = float(getattr(mem, "importance", 0.5))
        created_at = getattr(mem, "created_at", None)
        recency = _compute_recency_decay(created_at)
        relevance = rrf_scores.get(content, 0.0)
        composite = recency_w * recency + importance_w * importance + relevance_w * relevance
        scored.append((composite, mem))

    scored.sort(key=lambda x: x[0], reverse=True)
    top = scored[:top_k]

    if not top:
        return "", {"queries": queries, "results": []}, []

    annotator = RecallAnnotator()
    now = datetime.now(tz=UTC)
    lines: list[str] = []
    for _, m in top:
        created_at = getattr(m, "created_at", None)
        if created_at is not None:
            if created_at.tzinfo is None:
                created_at = created_at.replace(tzinfo=UTC)
            age_days = max(0.0, (now - created_at).total_seconds() / 86400.0)
        else:
            age_days = 30.0  # default fallback
        ann = annotator.annotate(
            confidence=float(getattr(m, "confidence", 1.0)),
            age_days=age_days,
            source_type=str(getattr(m, "source_type", "user_stated")),
            kind=str(getattr(m, "kind", "semantic")),
        )
        if not ann.should_mention:
            continue
        lines.append(
            f"[certainty: {ann.certainty}, time: {ann.time_hint}, source: {ann.source_hint}, kind: {ann.kind_hint}] "
            f"{getattr(m, 'content', str(m))}"
        )
    memories_list: list[object] = [m for _, m in top]
    debug_results = [
        {
            "content": getattr(m, "content", str(m)),
            "importance": round(float(getattr(m, "importance", 0.5)), 2),
            "score": round(score, 4),
        }
        for score, m in top
    ]
    return "\n".join(lines), {"queries": queries, "results": debug_results}, memories_list


async def _search_episodes(
    ctx: AppContext,
    query: str,
    top_k: int = 3,
) -> list[dict]:
    """Fallback: search Episode Memory (session_events) when Note Memory is insufficient.

    Returns list of dicts with 'topic', 'summary', 'content' keys.
    """
    session_event_repo = getattr(ctx, "_session_event_repo", None)
    if session_event_repo is None:
        return []

    try:
        from nous.domain.search.engine import SearchQuery

        # Use semantic search via search_engine for relevance if available
        if hasattr(ctx, "search_engine") and ctx.search_engine is not None:
            search_result = await ctx.search_engine.search(SearchQuery(text=query, top_k=top_k, mode="semantic"))
            if search_result.is_ok and search_result.value:
                episodes = []
                for hit in search_result.value:
                    mem = hit.memory if hasattr(hit, "memory") else hit
                    content = getattr(mem, "content", str(mem))[:200]
                    tags = getattr(mem, "tags", [])
                    source = getattr(mem, "source_context", "")
                    episodes.append(
                        {
                            "topic": tags[0] if tags else "episode",
                            "summary": content[:100],
                            "content": content,
                            "episode_id": source,
                        }
                    )
                return episodes

        # Fallback to keyword search on session event summaries
        events = session_event_repo.get_by_persona(ctx.persona, limit=top_k * 5)
        # Simple keyword scoring
        query_lower = query.lower()
        scored = []
        for ev in events:
            summary = (ev.summary or "").lower()
            detail = (ev.detail or "").lower()
            # Count query term occurrences
            score = summary.count(query_lower) * 2 + detail.count(query_lower)
            if score > 0:
                scored.append(
                    (
                        score,
                        {
                            "topic": ev.event_type or "session_event",
                            "summary": (ev.summary or "")[:100],
                            "content": (ev.detail or ev.summary or "")[:200],
                            "episode_id": str(ev.id or ""),
                        },
                    )
                )
        scored.sort(key=lambda x: -x[0])
        return [s[1] for s in scored[:top_k]]
    except Exception:
        logger.debug("_search_episodes failed (best-effort)", exc_info=True)
        return []


async def _build_context_section(
    ctx: AppContext,
    state,
    turn_ctx: ChatTurnContext | None = None,
    compress_mode: str = "auto",
    decay_note: str = "",
) -> str:
    """get_context() 同等の充実したコンテキストサマリーを構築する。

    compress_mode が "light"/"normal"/"aggressive" の場合は、
    重いセクション（reflection insight, mental model, session summary, emotion history）をスキップする。
    """
    t1: list[str] = []  # Tier 1: 現在の状態
    t2: list[str] = []  # Tier 2: 身体・環境
    t3: list[str] = []  # Tier 3: 参照情報
    _is_light = compress_mode in ("light", "normal", "aggressive")

    # === Tier 1: 現在の状態 ===
    now_jst = get_now()
    t1.append(f"Now: {now_jst.strftime('%Y-%m-%d %H:%M')} (JST)")

    last_conv = getattr(state, "last_conversation_time", None)
    if last_conv:
        time_since = relative_time_str(last_conv)
        t1.append(f"Last conversation: {time_since}")
        # Elapsed time note (minimal - LLM uses this naturally)
        try:
            _now = get_now()
            if last_conv.tzinfo is None:
                from zoneinfo import ZoneInfo  # noqa: PLC0415

                last_conv = last_conv.replace(tzinfo=ZoneInfo("Asia/Tokyo"))
            elapsed_hours = (_now - last_conv).total_seconds() / 3600.0
            if elapsed_hours >= 24:
                days = elapsed_hours / 24
                t1.append(f"About {days:.0f} day(s) since last conversation.")
            elif elapsed_hours >= 6:
                t1.append(f"{elapsed_hours:.0f} hour(s) since last conversation.")
        except (TypeError, AttributeError) as e:
            logger.debug("Failed to compute elapsed time: %s", e)

    if getattr(state, "emotion", None):
        intensity = getattr(state, "emotion_intensity", 0.5)
        intensity_label = "強い" if intensity > 0.6 else "やや強い" if intensity > 0.3 else "弱い"
        t1.append(f"感情: {state.emotion}（{intensity_label}）")

    # Emotion decay notification (English per T02 unification)
    if decay_note:
        t1.append(f"  Emotion: {decay_note}")

    if getattr(state, "mental_state", None):
        t1.append(f"精神状態: {state.mental_state}")

    if getattr(state, "speech_style", None):
        t1.append(f"話し方: {state.speech_style}")

    # === Tier 2: 身体・環境 ===
    # Body state — qualitative summary, flag only significantly elevated metrics
    high_metrics: list[str] = []
    for key, label in [("fatigue", "疲労"), ("pain", "痛み"), ("arousal", "過覚醒")]:
        val = getattr(state, key, None)
        if val is not None and val > 0.7:
            high_metrics.append(label)
    physical_text = getattr(state, "physical_state", None)
    if physical_text:
        body_line = f"身体: {physical_text}"
        if high_metrics:
            body_line += f"（{'・'.join(high_metrics)}が強め）"
        t2.append(body_line)
    elif high_metrics:
        t2.append(f"身体: {'・'.join(high_metrics)}が強めです")

    if getattr(state, "environment", None):
        t2.append(f"場所: {state.environment}")

    if getattr(state, "relationship_status", None):
        t2.append(f"関係: {state.relationship_status}")

    user_info = getattr(state, "user_info", None) or {}
    if user_info:
        ui_lines = "\n".join(f"  {k}: {v}" for k, v in user_info.items())
        t2.append(f"ユーザー情報:\n{ui_lines}")

    _hidden = {"goals", "promises", "active_promises", "current_goals"}
    persona_info = getattr(state, "persona_info", None) or {}
    filtered_pi = {k: v for k, v in persona_info.items() if k not in _hidden}
    if filtered_pi:
        pi_lines = "\n".join(f"  {k}: {v}" for k, v in filtered_pi.items())
        t2.append(f"ペルソナ情報:\n{pi_lines}")

    # === Tier 3: 参照情報 ===
    try:
        goals_result = ctx.memory_service.get_by_tags(["goal"])
        goals = goals_result.value if goals_result.is_ok else []
        active_goals = [g for g in goals if "active" in (g.tags or [])]
        promises_result = ctx.memory_service.get_by_tags(["promise"])
        promises = promises_result.value if promises_result.is_ok else []
        active_promises = [p for p in promises if "active" in (p.tags or [])]
        if turn_ctx is not None:
            turn_ctx.cached_active_goals = active_goals
            turn_ctx.cached_active_promises = active_promises
        if active_goals or active_promises:
            commit_lines: list[str] = []
            for g in active_goals:
                ts = relative_time_str(g.created_at) if getattr(g, "created_at", None) else ""
                ts_str = f" ({ts})" if ts else ""
                commit_lines.append(f"  🎯 [Goal] {g.content}{ts_str}")
            for p in active_promises:
                ts = relative_time_str(p.created_at) if getattr(p, "created_at", None) else ""
                ts_str = f" ({ts})" if ts else ""
                commit_lines.append(f"  🤝 [Promise] {p.content}{ts_str}")
            t3.append("Active commitments:\n" + "\n".join(commit_lines))
    except Exception as e:
        logger.debug("Failed to fetch goals/promises: %s", e)

    # Emotion trend — skip in light mode
    if not _is_light:
        try:
            eh_result = ctx.persona_service.get_emotion_history(state.persona, limit=5)
            if eh_result.is_ok and eh_result.value:
                recent_emotions = eh_result.value
                if len(recent_emotions) >= 2:
                    prev = recent_emotions[-2]
                    if prev.emotion != state.emotion:

                        def _fmt(emotion: str, context: str | None = None) -> str:
                            return f"{emotion}({context})" if context else emotion

                        trend = " → ".join(_fmt(r.emotion, r.context) for r in recent_emotions[-4:])
                        last_ctx = recent_emotions[-1].context if recent_emotions else None
                        trend += f" → {_fmt(state.emotion, last_ctx)}"
                        t3.append(f"感情推移: {trend}")
        except Exception as e:
            logger.debug("Failed to build emotion trend: %s", e)

    # Reflection insights — skip in light mode
    if not _is_light:
        try:
            reflection_result = ctx.memory_service.get_by_tags(["reflection"])
            if reflection_result.is_ok and reflection_result.value:
                insights = [r.content for r in reflection_result.value[:3] if r.content]
                if insights:
                    t3.append("最近の洞察:\n" + "\n".join(f"  💡 {i}" for i in insights))
        except Exception as e:
            logger.debug("Failed to fetch reflections: %s", e)

    # Mental model — skip in light mode
    if not _is_light:
        try:
            mm_result = ctx.memory_service.get_by_tags(["mental_model", "abstracted"])
            if mm_result.is_ok and mm_result.value:
                patterns = [m.content for m in mm_result.value[:3] if m.content]
                if patterns:
                    t3.append("行動パターン:\n" + "\n".join(f"  🧩 {p}" for p in patterns))
        except Exception as e:
            logger.debug("Failed to fetch mental models: %s", e)

    # Session summaries — skip in light mode
    if not _is_light:
        try:
            summary_result = ctx.memory_service.get_by_tags(["session_summary"])
            if summary_result.is_ok and summary_result.value:
                summaries = [s.content for s in summary_result.value[:2] if s.content]
                if summaries:
                    t3.append("最近の会話要約:\n" + "\n".join(f"  📝 {s}" for s in summaries))
        except Exception as e:
            logger.debug("Failed to fetch session summaries: %s", e)

    try:
        equip_result = ctx.equipment_service.get_equipment()
        if equip_result.is_ok:
            equipped = {k: v for k, v in equip_result.value.items() if v}
            if equipped:
                equip_lines = "\n".join(f"  {slot}: {item}" for slot, item in equipped.items())
                t3.append(f"装備:\n{equip_lines}")
    except Exception as e:
        logger.debug("Failed to fetch equipment: %s", e)

    # Assemble 3-tier output
    result = "【現在の状態】\n" + "\n".join(t1)
    if t2:
        result += "\n\n【身体・環境】\n" + "\n".join(t2)
    if t3:
        result += "\n\n【参照情報】\n" + "\n".join(t3)
    return result


class PrepareStep:
    """ターン開始時の準備ステップ。"""

    async def run(
        self,
        ctx: AppContext,
        session: SessionWindow,
        turn_ctx: ChatTurnContext,
        config: ChatConfig | None = None,
    ) -> None:
        """
        1. 前ターンのMemoryLLMを待機
        2. EmotionDecay適用
        3. get_context() + 記憶検索を並行実行
        4. ChatTurnContextに結果を格納
        """
        from nous.domain.chat_config import ChatConfig as _ChatConfig

        if config is None:
            config = _ChatConfig()

        # 1. 前ターンのMemoryLLMタスクを待つ
        if session.pending_memory_task is not None:
            try:
                await session.pending_memory_task
            except Exception as e:
                logger.warning("PrepareStep: pending MemoryLLM task error: %s", e)
            finally:
                session.pending_memory_task = None

        persona = ctx.persona

        # 2. PersonaState取得 + EmotionDecay適用
        state_result = ctx.persona_service.get_context(persona)
        if state_result.is_ok:
            state = state_result.value
            decay_note = ""
            try:
                from nous.config.runtime_config import RuntimeConfigManager

                half_life, _ = RuntimeConfigManager().get_effective_value("forgetting", "emotion_half_life_hours")
                decay_result = await apply_emotion_decay_if_needed(
                    ctx.persona_service, persona, state, half_life_hours=float(half_life)
                )
                if decay_result is not None:
                    # decay後に再取得
                    refreshed = ctx.persona_service.get_context(persona)
                    if refreshed.is_ok:
                        state = refreshed.value
                    from nous.api.mcp._tools_helpers import _format_emotion_decay_note

                    decay_note = _format_emotion_decay_note(decay_result)
            except Exception as e:
                logger.warning("PrepareStep: EmotionDecay failed (swallowed): %s", e)

            # Author's Note: propagate to turn_ctx for PromptBuildStep
            turn_ctx.author_note = getattr(state, "author_note", None)
            turn_ctx.author_note_frequency = getattr(state, "author_note_frequency", "always")

            # state_raw: シリアライズ可能な dict
            turn_ctx.state_raw = (
                {
                    k: str(v) if not isinstance(v, (str, int, float, bool, list, dict, type(None))) else v
                    for k, v in vars(state).items()
                }
                if hasattr(state, "__dict__")
                else {}
            )

            # context_section 構築
            last_assistant = session.get_last_assistant_content()
            context_task = asyncio.create_task(
                _build_context_section(
                    ctx, state, turn_ctx, compress_mode=config.context_compression_mode, decay_note=decay_note
                )
            )
            # Progressive disclosure: only preload N memories; LLM searches for more if needed
            preload_count = getattr(config, "memory_preload_count", 3)
            memory_task = asyncio.create_task(
                _search_memories(
                    ctx,
                    turn_ctx.user_message,
                    last_assistant,
                    config,
                    top_k=max(preload_count, 1) if preload_count > 0 else 0,
                )
            )
            turn_ctx.context_section, (turn_ctx.related_memories, debug, memories_list) = await asyncio.gather(
                context_task, memory_task
            )
            turn_ctx.memory_debug = debug
            turn_ctx.memories_raw = debug.get("results", [])
            turn_ctx.memories_objects = memories_list

            # HiMem 2-tier: Episode Memory fallback when Note Memory insufficient
            if config.episode_search_enabled:
                retrieved_count = len(turn_ctx.memories_raw)
                if preload_count == 0 or retrieved_count < preload_count:
                    try:
                        ep_results = await _search_episodes(ctx, turn_ctx.user_message, top_k=3)
                        if ep_results:
                            ep_lines = ["\n[Recent Episodes]"]
                            for ep in ep_results:
                                ep_lines.append(f"  [{ep.get('topic', 'episode')}] {ep.get('summary', '')[:80]}")
                            turn_ctx.related_memories += "\n" + "\n".join(ep_lines)
                    except Exception:
                        logger.debug("PrepareStep: episode search fallback failed", exc_info=True)
        else:
            logger.warning("PrepareStep: get_context failed: %s", state_result.error)
            # contextなしで継続
            last_assistant = session.get_last_assistant_content()
            try:
                preload_count = getattr(config, "memory_preload_count", 3)
                turn_ctx.related_memories, debug, memories_list = await _search_memories(
                    ctx,
                    turn_ctx.user_message,
                    last_assistant,
                    config,
                    top_k=max(preload_count, 1) if preload_count > 0 else 0,
                )
                turn_ctx.memory_debug = debug
                turn_ctx.memories_raw = debug.get("results", [])
                turn_ctx.memories_objects = memories_list
            except Exception as e:
                logger.warning("PrepareStep: memory search failed: %s", e)
