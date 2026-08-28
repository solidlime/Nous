"""PostProcessStep: MemoryLLM await実行 + Reflection SSE + セッション更新 + DebugInfo SSE。"""

from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING

from nous.application.chat.events import (
    CharacterFlagSSE,
    ContextUpdateSSE,
    DebugInfoSSE,
    DoneSSE,
    InventoryUpdateSSE,
    MemoryActivitySSE,
    SessionSummarizedSSE,
)
from nous.application.chat.memory_llm import run_memory_llm
from nous.application.chat.pattern_detector import maybe_run_mental_model
from nous.application.chat.reflection import maybe_run_reflection
from nous.application.chat.response_validator import validate_response
from nous.application.chat.summarizer import summarize_and_store
from nous.infrastructure.logging.structured import get_logger

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from nous.application.chat.pipeline.context import ChatTurnContext
    from nous.application.chat.session_store import TreeSessionWindow
    from nous.application.use_cases import AppContext
    from nous.domain.chat_config import ChatConfig

logger = get_logger(__name__)

# persona ごとの最終 auto_capture 実行時刻（monotonic）。
# PostProcessStep は毎ターン新規インスタンス化されるためモジュールレベルで保持。
_last_auto_capture_at: dict[str, float] = {}


async def _do_summarize(ctx: AppContext, config: ChatConfig, turns: list[dict]) -> str | None:
    """Summarization helper. Returns summary if generated."""
    try:
        summary = await summarize_and_store(ctx, config, turns)
        if summary:
            logger.info("Session summarized: %s...", summary[:50])
        return summary
    except Exception as e:
        logger.warning("_do_summarize error: %s", e)
        return None


async def _safe_reflection(
    ctx: AppContext,
    config: ChatConfig,
    memory_result: dict,
    turn_ctx: ChatTurnContext,
) -> None:
    """Background task: run reflection after DoneSSE."""
    if not config.reflection_enabled:
        return
    importance_sum = (
        sum(float(f.get("importance", 0.6)) for f in memory_result.get("facts", []))
        + len(turn_ctx.tool_calls_log) * 0.1
    )
    threshold = config.reflection_threshold
    if importance_sum < threshold:
        return
    try:
        insights = await maybe_run_reflection(ctx, config, importance_sum)
        logger.info("background reflection completed: %d insights", len(insights or []))
    except Exception:
        logger.warning("background reflection failed", exc_info=True)


async def _safe_mental_model(ctx: AppContext, config: ChatConfig) -> None:
    """Background task: run mental model after DoneSSE."""
    if not config.mental_model_enabled:
        return
    try:
        await maybe_run_mental_model(ctx, config)
        logger.info("background mental model completed")
    except Exception:
        logger.warning("background mental model failed", exc_info=True)


class PostProcessStep:
    """MemoryLLM await実行 + Reflection SSE + セッション更新 + debug_info/done SSEの送出。

    Validation gaps (2026-07-26):
    - No character consistency / tone verification exists
    - No contradiction detection against persona settings
    - Author's Note (injected at prompt.py:118) has no contradiction check
    - LLM output trusted as-is; verification relies solely on system prompt quality
    - Response validation added via ResponseValidator (see response_validator.py)
    """

    def __init__(self) -> None:
        self._background_tasks: list[asyncio.Task] = []

    async def run(
        self,
        ctx: AppContext,
        config: ChatConfig,
        session: TreeSessionWindow,
        turn_ctx: ChatTurnContext,
        debug: bool = False,
    ) -> AsyncIterator[
        DebugInfoSSE
        | DoneSSE
        | MemoryActivitySSE
        | SessionSummarizedSSE
        | ContextUpdateSSE
        | InventoryUpdateSSE
        | CharacterFlagSSE
    ]:
        # evict_callback を設定（session.add は service.py で既に実行済み）
        _summary_tasks: list[asyncio.Task] = []
        if config.session_summarize:

            def _evict_cb(evicted: list[dict]) -> None:
                _summary_tasks.append(asyncio.create_task(_do_summarize(ctx, config, evicted)))

            session.evict_callback = _evict_cb

        # SessionSummarizedSSE: await collected summary tasks
        for task in _summary_tasks:
            try:
                summary = await task
                if summary:
                    yield SessionSummarizedSSE(summary=summary)
            except Exception as e:
                logger.warning("SessionSummarizedSSE failed: %s", e)

        # Auto-capture: セッション会話から重要情報を記憶として抽出（interval throttle 付き）
        try:
            interval = max(0, int(getattr(config, "auto_capture_interval", 300)))
            now = time.monotonic()
            last = _last_auto_capture_at.get(ctx.persona)
            due = interval <= 0 or last is None or (now - last) >= interval
            if config.auto_capture_enabled and session._messages and due:
                _last_auto_capture_at[ctx.persona] = now
                from nous.application.chat.pipeline.auto_capture import run_auto_capture

                self._background_tasks.append(
                    asyncio.create_task(
                        run_auto_capture(
                            ctx=ctx,
                            config=config,
                            persona=ctx.persona,
                            messages=list(session._messages),
                            max_memories=config.auto_capture_max_memories,
                        )
                    )
                )
        except Exception as e:
            logger.warning("PostProcessStep: auto_capture failed: %s", e)

        # 最終会話時刻を記録
        try:
            ctx.persona_service.record_conversation_time(ctx.persona)
        except Exception as e:
            logger.warning("PostProcessStep: record_conversation_time failed: %s", e)

        # Validate response before marking as done
        response_warnings = validate_response(turn_ctx.full_response)
        for w in response_warnings:
            logger.warning("Response validation: %s", w)

        # DoneSSE: memory_llmの前に送出（was_truncatedは事前に設定済み）
        yield DoneSSE(
            truncated=turn_ctx.was_truncated,
            usage=turn_ctx.usage,
            user_msg_id=turn_ctx.user_msg_id,
            assistant_msg_id=turn_ctx.assistant_msg_id,
        )

        # MemoryLLM + CharacterJudge: DoneSSE後に並走実行（asyncio.gather・互待ち時間なし）
        memory_result: dict = {}
        judgment: dict | None = None
        if turn_ctx.full_response:
            payload = {"user": turn_ctx.user_message, "assistant": turn_ctx.full_response}
            coros: list = []  # 戻り値型が混在（dict / dict|None）するため Any 許容
            wants_memory = config.auto_extract
            wants_judge = getattr(config, "character_judge_enabled", True)
            if wants_memory:
                coros.append(run_memory_llm(ctx, config, payload))
            if wants_judge:
                from nous.application.chat.character_judge import judge_character

                coros.append(judge_character(config, turn_ctx.system_prompt, turn_ctx.full_response))
            if coros:
                results = await asyncio.gather(*coros, return_exceptions=True)
                idx = 0
                if wants_memory:
                    r = results[idx]
                    idx += 1
                    if isinstance(r, Exception):
                        logger.warning("PostProcessStep: run_memory_llm failed: %s", r)
                    elif isinstance(r, dict):
                        memory_result = r
                if wants_judge:
                    r = results[idx]
                    if isinstance(r, Exception):
                        logger.warning("PostProcessStep: judge_character failed: %s", r)
                    elif isinstance(r, dict):
                        judgment = r

        # MemoryActivitySSE: 取得された記憶と保存された記憶・goals・promises を通知
        retrieved_for_sse = turn_ctx.memories_raw[:5]

        def _ensure_str(val: object, default: str = "") -> str:
            if isinstance(val, str):
                return val
            if val is None:
                return default
            import json

            return json.dumps(val, ensure_ascii=False)

        saved_facts = [
            {
                "content": _ensure_str(f.get("content")),
                "tags": f.get("tags", []),
                "emotion": f.get("emotion", "neutral"),
            }
            for f in memory_result.get("facts", [])
            if f.get("content")
        ]
        saved_goals = [
            {"content": _ensure_str(g.get("content"))} for g in memory_result.get("goals", []) if g.get("content")
        ]
        saved_promises = [
            {"content": _ensure_str(p.get("content"))} for p in memory_result.get("promises", []) if p.get("content")
        ]
        yield MemoryActivitySSE(
            retrieved=retrieved_for_sse,
            saved=saved_facts,
            goals=saved_goals,
            promises=saved_promises,
        )

        # ContextUpdateSSE: notify frontend of persona state changes
        context_update = memory_result.get("context_update")
        if context_update:
            non_null = {k: v for k, v in context_update.items() if v is not None}
            if non_null:
                yield ContextUpdateSSE(update=non_null)

        # InventoryUpdateSSE: notify frontend of equipment changes
        inventory_update = memory_result.get("inventory_update")
        if inventory_update:
            # Ensure string values — LLM may return objects instead of strings
            _inv = {}
            for k, v in inventory_update.items():
                if not v:
                    continue
                if k == "equip" and isinstance(v, dict):
                    _inv[k] = {sk: _ensure_str(sv) for sk, sv in v.items() if sv}
                elif k in ("unequip", "remove_items") and isinstance(v, list):
                    _inv[k] = [_ensure_str(i) for i in v if i]
                elif k in ("add_items", "update_items") and isinstance(v, list):
                    _inv[k] = [
                        {ik: _ensure_str(iv) if isinstance(iv, (str, dict)) else iv for ik, iv in i.items()}
                        for i in v
                        if isinstance(i, dict)
                    ]
                else:
                    _inv[k] = v
            if _inv:
                yield InventoryUpdateSSE(update=_inv)

        # ExpressionUpdate: 感情変化に対応する表情画像を通知（無ければ非同期生成）
        emotion = str((memory_result.get("context_update") or {}).get("emotion") or "")
        if emotion:
            try:
                await update_expression(ctx, config, emotion)
            except Exception as e:
                logger.warning("PostProcessStep: update_expression failed: %s", e)

        # CharacterFlagSSE: キャラ一貫性違反のフラグ（非破壊・表示のみ）
        if judgment and judgment.get("violation") not in (None, "none"):
            yield CharacterFlagSSE(violation=judgment["violation"], detail=judgment.get("detail", ""))

        # debug_info SSE — only when debug flag is enabled
        if debug:
            debug_data = {
                "session_id": turn_ctx.session_id,
                "provider": config.provider,
                "model": config.get_effective_model(),
                "auto_extract": config.auto_extract,
                "system_prompt": turn_ctx.system_prompt,
                "context_state": turn_ctx.state_raw,
                "context_summary": turn_ctx.context_section,
                "memories_raw": turn_ctx.memories_raw,
                "memory_queries": turn_ctx.memory_debug.get("queries", []),
                "skills_raw": turn_ctx.skills_raw,
                "tools_injected": [],
                "messages_sent": [
                    {"role": m.role, "content": m.content[:500] + "..." if len(m.content or "") > 500 else m.content}
                    for m in turn_ctx.messages
                ],
                "tool_calls": turn_ctx.tool_calls_log,
                "assistant_response": turn_ctx.full_response,
            }
            try:
                yield DebugInfoSSE(data=debug_data)
            except Exception as e:
                logger.warning("PostProcessStep: debug_info SSE failed: %s", e)
                yield DebugInfoSSE(data={"error": str(e), "system_prompt": turn_ctx.system_prompt[:500]})

        # DoneSSE は run_memory_llm の前に移動済み（L175）

        # Fire-and-forget: DoneSSE後に後処理を非同期タスクとして実行
        self._background_tasks.append(asyncio.create_task(_safe_reflection(ctx, config, memory_result, turn_ctx)))
        self._background_tasks.append(asyncio.create_task(_safe_mental_model(ctx, config)))
        return


async def update_expression(ctx, config, emotion: str) -> None:
    """感情に対応する表情画像をイベントバス経由で通知する。

    画像が既にあれば即時 publish、無ければ非同期生成タスクをスケジュールする
    （チャットストリームは応答後に閉じるため、完了が非同期になり得る表情は
    イベントバス経由で配信する）。
    """
    from nous.application.chat.expression import resolve_expression_url
    from nous.application.event_bus import EVENT_EXPRESSION_CHANGED

    if not emotion:
        return
    persona = ctx.persona
    url = resolve_expression_url(persona, emotion)
    if url is None:
        task = asyncio.create_task(_generate_and_publish_expression(ctx, config, emotion))
        if hasattr(ctx, "_expression_tasks"):
            ctx._expression_tasks.append(task)
        return
    await ctx.event_bus.publish(EVENT_EXPRESSION_CHANGED, {"emotion": emotion, "url": url})


async def _generate_and_publish_expression(ctx, config, emotion: str) -> None:
    """表情画像を非同期生成し、成功したらイベントバスへ通知する。"""
    from nous.application.chat.expression import generate_expression_image
    from nous.application.event_bus import EVENT_EXPRESSION_CHANGED

    url = await generate_expression_image(config, ctx.persona, emotion)
    if url:
        await ctx.event_bus.publish(EVENT_EXPRESSION_CHANGED, {"emotion": emotion, "url": url})
