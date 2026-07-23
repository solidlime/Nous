"""ChatService: パイプライン型チャットオーケストレーター。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from nous.application.chat.pipeline.compress import CompressStep
from nous.application.chat.pipeline.context import ChatTurnContext
from nous.application.chat.pipeline.inference import InferenceStep
from nous.application.chat.pipeline.post import PostProcessStep
from nous.application.chat.pipeline.prepare import PrepareStep
from nous.application.chat.pipeline.prompt import PromptBuildStep
from nous.application.chat.session_store import SessionManager
from nous.application.chat.tools.definitions import get_filtered_tools
from nous.application.chat.tools.registry import ToolRegistry
from nous.domain.shared.time_utils import get_now
from nous.infrastructure.logging.structured import get_logger
from nous.infrastructure.mcp_client import MCPClientPool

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from nous.application.use_cases import AppContext
    from nous.domain.chat_config import ChatConfig

logger = get_logger(__name__)

_session_manager = SessionManager()


class ChatService:
    async def chat(
        self,
        ctx: AppContext,
        config: ChatConfig,
        session_id: str,
        user_message: str,
        debug: bool = False,
        images: list[dict] | None = None,
    ) -> AsyncIterator[str]:
        persona = ctx.persona
        db = ctx.connection.get_memory_db()
        session = _session_manager.get_or_create(persona, session_id, max_messages=config.max_stored_messages, db=db)

        turn_ctx = ChatTurnContext(session_id=session_id, user_message=user_message, images=images or [])

        # Publish chat.message event for server-side history
        await ctx.event_bus.publish(
            "chat.message",
            {
                "persona": persona,
                "session_id": session_id,
                "content": user_message,
                "timestamp": get_now().isoformat(),
            },
        )

        # Send SSE heartbeat immediately so the frontend stream reader doesn't time out
        # during the potentially heavy PrepareStep (memory retrieval, context building).
        yield ": heartbeat\n\n"

        # Progressive disclosure: fast keyword search for immediate feedback
        # Send memory_activity SSE with keyword-matched results before full PrepareStep
        from nous.application.chat.events import MemoryActivitySSE
        from nous.application.chat.pipeline.prepare import _search_keyword_fast

        _last_assistant = session.get_last_assistant_content()
        _fast_memories = await _search_keyword_fast(ctx, turn_ctx.user_message, _last_assistant, top_k=5)
        if _fast_memories:
            yield MemoryActivitySSE(retrieved=_fast_memories, saved=[], goals=[]).to_sse()

        # PrepareStep: pending_memory_task 待機 + EmotionDecay + コンテキスト取得
        await PrepareStep().run(ctx, session, turn_ctx, config=config)

        # PromptBuildStep: system プロンプト組み立て
        PromptBuildStep().run(ctx, config, turn_ctx)

        # TA03: Compute effective temperature from persona emotion
        from nous.domain.sampling import EmotionDrivenSampler

        effective_temp: float | None = None
        if config.dynamic_temperature:
            state_raw = turn_ctx.state_raw
            emotion = state_raw.get("emotion", "neutral")
            intensity = float(state_raw.get("emotion_intensity", 0.5))
            effective_temp = EmotionDrivenSampler.compute(
                base_temp=config.temperature,
                emotion=emotion,
                intensity=intensity,
                scale=config.emotion_temperature_scale,
            )

        # InferenceStep + PostProcessStep: MCPプール共有
        async with MCPClientPool(config.mcp_servers) as mcp_pool:
            builtin = get_filtered_tools(config) if config.enable_memory_tools else []
            _tool_names = [t.name for t in builtin]
            has_img = "image_generate" in _tool_names
            logger.warning(
                "Chat tools assembled: image_gen_enabled=%s, tools=%d, has_image_generate=%s, names=%s",
                getattr(config, "image_gen_enabled", "MISSING"),
                len(builtin),
                has_img,
                _tool_names,
            )
            registry = ToolRegistry(builtin, mcp_pool)

            # スキル一覧を invoke_skill ツールの description に注入（システムプロンプトから移行）
            if turn_ctx.skills_raw:
                registry.add_skills_info(turn_ctx.skills_raw)

            session_messages = session.get_labeled_messages()

            # CompressStep: コンテキスト圧縮（トークン予算超過 / max_stored_messages 超過時に圧縮）
            messages = await CompressStep().run(ctx, config, turn_ctx, session_messages)

            # max_stored_messages によるメッセージ数制限（LLMMessage数でカウント）
            max_msgs = config.max_stored_messages
            if len(messages) >= max_msgs:
                logger.info(
                    "Truncated session messages: %d → %d (max_stored_messages=%d)",
                    len(messages),
                    max_msgs,
                    max_msgs,
                )
                messages = messages[-max_msgs:]

            # Notify frontend if compression occurred
            comp_info = getattr(turn_ctx, "_compression_info", None)
            if comp_info:
                # Publish compaction event
                await ctx.event_bus.publish(
                    "session.compact",
                    {
                        "persona": persona,
                        "session_id": session_id,
                        "before_tokens": comp_info["before_tokens"],
                        "after_tokens": comp_info["after_tokens"],
                        "timestamp": get_now().isoformat(),
                    },
                )
                from nous.application.chat.events import ContextCompressedSSE

                yield ContextCompressedSSE(
                    before_tokens=comp_info["before_tokens"],
                    after_tokens=comp_info["after_tokens"],
                    budget=comp_info["budget"],
                    mode=config.context_compression_mode,
                ).to_sse()

            # Save user message BEFORE inference (so it's persisted even if client disconnects)
            now = get_now()
            user_msg_id = session.add("user", turn_ctx.user_message, now)
            turn_ctx.user_msg_id = user_msg_id

            # Collect and stream LLM response
            full_response = ""
            async for event in InferenceStep().run(
                ctx, config, messages, turn_ctx, registry, effective_temp=effective_temp
            ):
                yield event.to_sse()
                # Collect text deltas for chat.llm_response event
                from nous.application.chat.events import TextDeltaSSE

                if isinstance(event, TextDeltaSSE):
                    full_response += event.content

            # Save assistant response BEFORE PostProcessStep
            if full_response or turn_ctx.tool_calls_log:
                assistant_msg_id = session.add(
                    "assistant",
                    full_response,
                    get_now(),
                    tool_calls=turn_ctx.tool_calls_log if turn_ctx.tool_calls_log else None,
                    segments=turn_ctx.segments if turn_ctx.segments else None,
                )
                turn_ctx.assistant_msg_id = assistant_msg_id
                turn_ctx.full_response = full_response

            # Publish chat.llm_response event
            if full_response:
                await ctx.event_bus.publish(
                    "chat.llm_response",
                    {
                        "persona": persona,
                        "session_id": session_id,
                        "content": full_response,
                        "timestamp": get_now().isoformat(),
                    },
                )

        async for post_event in PostProcessStep().run(ctx, config, session, turn_ctx, debug=debug):
            yield post_event.to_sse()

        # Force-persist to SQLite immediately so GET /api/chat/.../sessions/:id returns current data
        session.flush()
