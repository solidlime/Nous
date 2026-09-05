"""ChatService: パイプライン型チャットオーケストレーター。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from nous.application.chat.pipeline.compress import CompressStep
from nous.application.chat.pipeline.context import ChatTurnContext
from nous.application.chat.pipeline.inference import InferenceStep
from nous.application.chat.pipeline.post import PostProcessStep
from nous.application.chat.pipeline.prepare import PrepareStep
from nous.application.chat.pipeline.prompt import PromptBuildStep
from nous.application.chat.pipeline.trimmer import TrimmerMixin
from nous.application.chat.session_store import SessionManager
from nous.application.chat.tools.definitions import get_filtered_tools
from nous.application.chat.tools.registry import ToolRegistry
from nous.application.event_bus import CHAT_LLM_RESPONSE, CHAT_MESSAGE, SESSION_COMPACT
from nous.domain.shared.time_utils import get_now
from nous.infrastructure.logging.structured import get_logger
from nous.infrastructure.mcp_client import MCPClientPool

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from nous.application.use_cases import AppContext
    from nous.domain.chat_config import ChatConfig
    from nous.infrastructure.tools import ToolSearchEngine

logger = get_logger(__name__)

_session_manager = SessionManager()


# ── Tool search engine (search_tools) ─────────────────────────────────────────


async def _ensure_tool_index(registry: ToolRegistry) -> ToolSearchEngine | None:
    """ツール検索エンジンを初期化し、deferred ツールを Qdrant にインデックスする。

    失敗時は None を返し、search_tools は無効化される。
    """
    try:
        from qdrant_client import AsyncQdrantClient

        from nous.config.settings import get_settings
        from nous.infrastructure.embedding.model import EmbeddingModel
        from nous.infrastructure.tools import ToolSearchEngine, ToolVectorStore

        settings = get_settings()
        client = AsyncQdrantClient(url=settings.qdrant.url, api_key=settings.qdrant.api_key, timeout=10)
        embed = EmbeddingModel()
        vector_store = ToolVectorStore(client, embed)
        await vector_store.ensure_collection()

        deferred_tools = [t for t in registry.get_all_tools() if t.defer_loading]
        if deferred_tools:
            await vector_store.index_tools(deferred_tools)

        engine = ToolSearchEngine(vector_store)
        logger.info("Tool search engine initialized (%d deferred tools indexed)", len(deferred_tools))
        return engine
    except Exception as exc:
        logger.warning("Tool search engine initialization failed (search_tools disabled): %s", exc)
        return None


async def _execute_search_tools(
    engine: ToolSearchEngine,
    registry: ToolRegistry,
    config: ChatConfig,  # noqa: ARG001
    tool_input: dict,
) -> dict:
    """search_tools 実行ハンドラ。deferred ツールを検索し、発見したツールを登録する。"""
    query = tool_input.get("query", "")
    top_k = int(tool_input.get("top_k", 5))
    results = await engine.search(query, top_k)
    for r in results:
        registry.mark_discovered(r.tool_name)
    items = [f"- {r.tool_name}: {r.description[:100]}..." for r in results]
    return {
        "status": "ok",
        "tools": "\n".join(items),
        "count": len(results),
    }


def _build_tool_only_fallback(tool_calls_log: list[dict]) -> str:
    """空テキスト＋ツール有りターンの保存用フォールバック文を合成する。"""
    import json

    for entry in tool_calls_log or []:
        if not isinstance(entry, dict):
            continue
        for key in ("result_raw", "result"):
            src = entry.get(key)
            if not isinstance(src, dict):
                continue
            if src.get("images") and isinstance(src.get("message"), str) and src["message"].strip():
                return str(src["message"]).strip()
            if isinstance(src.get("images_summary"), str) and src["images_summary"].strip():
                return str(src["images_summary"]).strip()
            content = src.get("content")
            if isinstance(content, str) and content.strip().startswith("{"):
                try:
                    data = json.loads(content)
                except Exception:
                    data = None
                if isinstance(data, dict):
                    if isinstance(data.get("images_summary"), str) and data["images_summary"].strip():
                        if isinstance(data.get("message"), str) and data["message"].strip():
                            return str(data["message"]).strip()
                        return str(data["images_summary"]).strip()
                    msg = data.get("message")
                    if isinstance(msg, str) and ("Generated" in msg or "image" in msg.lower()):
                        return msg.strip()
    return "（ツールは使ったけど、うまく言葉にできなかった…もう一度言って？）"


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
        try:
            persona = ctx.persona
            db = ctx.connection.get_memory_db()
            session = _session_manager.get_or_create(
                persona, session_id, max_messages=config.max_stored_messages, db=db
            )

            # Propagate session_id to AppContext so MCP tools can use it for
            # Hebbian co-activation linking via MemoryLinkService.
            ctx.session_id = session_id

            turn_ctx = ChatTurnContext(session_id=session_id, user_message=user_message, images=images or [])

            # Publish chat.message event for server-side history
            await ctx.event_bus.publish(
                CHAT_MESSAGE,
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
                yield MemoryActivitySSE(retrieved=_fast_memories, saved=[], goals=[], preliminary=True).to_sse()

            # PrepareStep: pending_memory_task 待機 + EmotionDecay + コンテキスト取得
            await PrepareStep().run(ctx, session, turn_ctx, config=config)

            # PromptBuildStep: system プロンプト組み立て
            PromptBuildStep().run(ctx, config, turn_ctx)

            # TA03: Compute effective temperature from persona emotion
            from nous.domain.sampling import EmotionDrivenSampler

            effective_temp: float | None = None
            if config.dynamic_temperature:
                from nous.domain.value_objects import normalize_importance

                state_raw = turn_ctx.state_raw
                emotion = state_raw.get("emotion", "neutral")
                # f2: 欠損・範囲外・非数値を境界で正規化
                try:
                    intensity = normalize_importance(
                        float(state_raw.get("emotion_intensity", 0.5))
                        if state_raw.get("emotion_intensity") is not None
                        else None
                    )
                except (TypeError, ValueError):
                    intensity = 0.5
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
                logger.info(
                    "Chat tools assembled: image_gen_enabled=%s, tools=%d, has_image_generate=%s, names=%s",
                    getattr(config, "image_gen_enabled", "MISSING"),
                    len(builtin),
                    has_img,
                    _tool_names,
                )
                registry = ToolRegistry(builtin, mcp_pool)

                # ツール検索エンジンの初期化（search_tools 機能）
                _search_engine = await _ensure_tool_index(registry)
                if _search_engine:
                    _reg_ref = registry  # closure capture
                    registry.set_search_handler(
                        lambda ctx, config, ti: _execute_search_tools(_search_engine, _reg_ref, config, ti)  # type:ignore[arg-type]
                    )
                    logger.info("search_tools handler registered (%d tools visible)", len(registry.get_visible_tools()))

                session_messages = session.get_labeled_messages()

                # CompressStep: コンテキスト圧縮（トークン予算超過 / max_stored_messages 超過時に圧縮）
                messages = await CompressStep().run(ctx, config, turn_ctx, session_messages)

                # max_stored_messages によるメッセージ数制限（LLMMessage数でカウント）
                max_msgs = config.max_stored_messages
                if len(messages) >= max_msgs:
                    before_count = len(messages)
                    # スライス先頭が tool なら assistant(tool_calls) を含むよう広げる（孤児 tool 防止）
                    start = TrimmerMixin._adjust_slice_start(messages, -max_msgs)
                    messages = messages[start:]
                    logger.info(
                        "Truncated session messages: %d → %d (max_stored_messages=%d)",
                        before_count,
                        len(messages),
                        max_msgs,
                    )

                # Notify frontend if compression occurred
                comp_info = getattr(turn_ctx, "_compression_info", None)
                if comp_info:
                    # Publish compaction event
                    await ctx.event_bus.publish(
                        SESSION_COMPACT,
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
                    if not full_response and turn_ctx.tool_calls_log:
                        full_response = _build_tool_only_fallback(turn_ctx.tool_calls_log)
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
                        CHAT_LLM_RESPONSE,
                        {
                            "persona": persona,
                            "session_id": session_id,
                            "content": full_response,
                            "timestamp": get_now().isoformat(),
                        },
                    )

                # Force-persist to SQLite BEFORE PostProcessStep (which sends DoneSSE)
                # so reload-after-response doesn't lose messages
                session.flush()

            try:
                async for post_event in PostProcessStep().run(ctx, config, session, turn_ctx, debug=debug):
                    yield post_event.to_sse()
            except Exception:
                logger.exception("Chat pipeline crashed")
                from nous.application.chat.events import ErrorSSE

                yield ErrorSSE(message="（ごめん、今のうまく処理できなかった…もう一度言って？）").to_sse()
            finally:
                # Always persist, even on GeneratorExit (client disconnect during PostProcessStep)
                session.flush()
        except Exception:
            logger.exception("Chat pipeline crashed")
            from nous.application.chat.events import ErrorSSE

            yield ErrorSSE(message="（ごめん、今のうまく処理できなかった…もう一度言って？）").to_sse()
