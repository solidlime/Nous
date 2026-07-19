"""InferenceStep: LLMストリームループとツール実行。"""

from __future__ import annotations

import asyncio
import logging
import json
from typing import TYPE_CHECKING

from nous.application.chat.events import (
    ErrorSSE,
    ImageGenResultSSE,
    ImageGenStartSSE,
    TextDeltaSSE,
    ToolCallSSE,
    ToolResultSSE,
)
from nous.infrastructure.llm.base import DoneEvent, ErrorEvent, LLMMessage, TextDeltaEvent, ToolCallEvent
from nous.infrastructure.llm.factory import get_provider
from nous.infrastructure.logging.structured import get_logger

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from nous.application.chat.pipeline.context import ChatTurnContext
    from nous.application.chat.tools.registry import ToolRegistry
    from nous.application.use_cases import AppContext
    from nous.domain.chat_config import ChatConfig

logger = get_logger(__name__)


class InferenceStep:
    """LLMストリームループ。TextDelta/ToolCall/ToolResult SSEを yield する。"""

    async def run(
        self,
        ctx: AppContext,
        config: ChatConfig,
        session_messages: list[LLMMessage],
        turn_ctx: ChatTurnContext,
        registry: ToolRegistry,
        effective_temp: float | None = None,
    ) -> AsyncIterator[TextDeltaSSE | ToolCallSSE | ToolResultSSE | ErrorSSE | ImageGenStartSSE | ImageGenResultSSE]:
        api_key = config.get_effective_api_key()
        if not api_key:
            yield ErrorSSE(message="APIキーが設定されていません。チャット設定でAPIキーを入力してください。")
            return

        try:
            provider = get_provider(
                config.provider,
                api_key,
                config.get_effective_model(),
                config.get_effective_base_url(),
            )
        except Exception as e:
            yield ErrorSSE(message=f"LLMプロバイダーの初期化に失敗: {e}")
            return

        all_tools = registry.get_all_tools()
        messages = list(session_messages)
        if turn_ctx.images:
            parts: list[dict] = [{"type": "text", "text": turn_ctx.user_message}]
            for img in turn_ctx.images:
                parts.append(
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:{img['mime_type']};base64,{img['base64_data']}",
                            "detail": "auto",
                        },
                    }
                )
            messages.append(LLMMessage(role="user", content=turn_ctx.user_message, content_parts=parts))
        else:
            messages.append(LLMMessage(role="user", content=turn_ctx.user_message))

        temperature = effective_temp if effective_temp is not None else config.temperature
        max_continuation_rounds = 3
        _continuation_rounds = 0
        while turn_ctx.tool_call_count <= config.max_tool_calls:
            pending_tool_calls: list[ToolCallEvent] = []
            current_text = ""
            _seg_text = ""  # text accumulator for segment ordering
            _finish_reason = ""  # set by DoneEvent handler inside stream loop

            async for event in provider.stream(
                messages=messages,
                system=turn_ctx.system_prompt,
                tools=all_tools,
                temperature=temperature,
                max_tokens=config.max_tokens,
                top_p=config.top_p,
            ):
                if isinstance(event, TextDeltaEvent):
                    current_text += event.content
                    turn_ctx.full_response += event.content
                    _seg_text += event.content
                    yield TextDeltaSSE(content=event.content)
                elif isinstance(event, ToolCallEvent):
                    # Flush accumulated text as segment before tool call
                    if _seg_text:
                        turn_ctx.segments.append({"type": "text", "content": _seg_text})
                        _seg_text = ""
                    yield ToolCallSSE(name=event.tool_name, input=event.tool_input, id=event.tool_use_id)
                    turn_ctx.segments.append(
                        {
                            "type": "tool_call",
                            "name": event.tool_name,
                            "input": event.tool_input,
                            "id": event.tool_use_id,
                        }
                    )
                    # Guard against None from buggy provider implementations.
                    # Note: {} is a valid tool input (parameterless tools).
                    if event.tool_input is not None:
                        pending_tool_calls.append(event)
                elif isinstance(event, ErrorEvent):
                    yield ErrorSSE(message=event.message)
                    return
                elif isinstance(event, DoneEvent):
                    # Provider finished streaming this turn.
                    _finish_reason = (event.finish_reason or "").lower()
                    turn_ctx.usage = event.usage
                    if not current_text and not pending_tool_calls:
                        logger.warning(
                            "InferenceStep: provider finished with empty response (model=%s, turn=%d, finish=%s)",
                            config.get_effective_model(),
                            turn_ctx.tool_call_count,
                            _finish_reason,
                        )

            # Flush remaining text segment after inner loop
            if _seg_text:
                turn_ctx.segments.append({"type": "text", "content": _seg_text})
                _seg_text = ""

            # Auto-continue if response was truncated by max_tokens limit
            if not pending_tool_calls and _finish_reason == "length" and current_text:
                _continuation_rounds += 1
                if _continuation_rounds <= max_continuation_rounds:
                    logger.info(
                        "InferenceStep: response truncated by max_tokens, auto-continuing (round %d/%d, model=%s)",
                        _continuation_rounds,
                        max_continuation_rounds,
                        config.get_effective_model(),
                    )
                    turn_ctx.was_truncated = True
                    # Save partial text as assistant message for continuation context
                    messages.append(LLMMessage(role="assistant", content=current_text))
                    # Empty user message prompts LLM to continue from where it left off
                    messages.append(LLMMessage(role="user", content=""))
                    current_text = ""
                    _seg_text = ""
                    continue  # back to top of while loop for another stream
                else:
                    logger.warning(
                        "InferenceStep: max continuation rounds (%d) reached, giving up",
                        max_continuation_rounds,
                    )

            if not pending_tool_calls:
                break

            messages.append(
                LLMMessage(
                    role="assistant",
                    content=current_text,
                    tool_calls=[
                        {"id": tc.tool_use_id, "name": tc.tool_name, "input": tc.tool_input}
                        for tc in pending_tool_calls
                    ],
                )
            )

            # ── Deduplicate tool calls before execution ──

            # 1) Skip tool calls already executed in this turn
            executed_ids = {tc.get("id", "") for tc in (turn_ctx.tool_calls_log or [])}
            pending_tool_calls = [tc for tc in pending_tool_calls if tc.tool_use_id not in executed_ids]

            # 2) Deduplicate identical tool calls within the same pending batch
            seen_ids: set[str] = set()
            deduped_calls: list[ToolCallEvent] = []
            for tc in pending_tool_calls:
                if tc.tool_use_id not in seen_ids:
                    seen_ids.add(tc.tool_use_id)
                    deduped_calls.append(tc)
            if len(deduped_calls) < len(pending_tool_calls):
                logger.info("Deduplicated %d → %d tool calls", len(pending_tool_calls), len(deduped_calls))
            pending_tool_calls = deduped_calls

            if not pending_tool_calls:
                break

            enable_parallel = getattr(config, "enable_parallel_tools", True)

            # Yield ImageGenStartSSE before executing image_generate tools
            for tc in pending_tool_calls:
                if tc.tool_name == "image_generate":
                    ti = tc.tool_input or {}
                    n = ti.get("n", 1)
                    try:
                        n = int(n)
                    except (ValueError, TypeError):
                        n = 1
                    yield ImageGenStartSSE(
                        provider="comfyui",
                        prompt=str(ti.get("prompt", ""))[:100],
                        n=max(1, min(4, n)),
                    )

            async def _exec_one(tc: ToolCallEvent):
                result = await registry.execute(ctx, config, tc.tool_name, tc.tool_input)
                truncated = registry.truncate_result(result, config.tool_result_max_chars)
                return (tc, truncated, result)

            if enable_parallel:
                results = await asyncio.gather(*[_exec_one(tc) for tc in pending_tool_calls])
            else:
                results = [await _exec_one(tc) for tc in pending_tool_calls]

            for tc, truncated, tool_result in results:
                # ToolResultSSE must come FIRST so the tool bubble is in the DOM
                # before showImageGenResult tries to insert the image card after it
                yield ToolResultSSE(name=tc.tool_name, result=truncated, id=tc.tool_use_id)
                # If tool result contains images, emit ImageGenResultSSE to frontend
                if isinstance(tool_result, dict) and tool_result.get("images"):
                    imgs = tool_result["images"]
                    logger.info("ImageGenResultSSE: yielding %d image(s) to frontend", len(imgs) if isinstance(imgs, list) else 0)
                    yield ImageGenResultSSE(
                        provider=tool_result.get("provider", "comfyui"),
                        images=tool_result["images"],
                    )
                turn_ctx.segments.append(
                    {"type": "tool_result", "name": tc.tool_name, "result": truncated, "id": tc.tool_use_id}
                )
                # result_raw は DB 保存用: base64 を除去し url を残す（SSE では使わない）
                result_for_log = tool_result
                if isinstance(tool_result, dict) and tool_result.get("images"):
                    result_for_log = dict(tool_result)
                    result_for_log["images"] = [
                        {
                            k: v for k, v in img.items()
                            if k != "base64"
                        }
                        for img in tool_result["images"]
                    ]
                turn_ctx.tool_calls_log.append(
                    {
                        "id": tc.tool_use_id,
                        "name": tc.tool_name,
                        "input": tc.tool_input,
                        "result": truncated,
                        "result_raw": result_for_log,
                    }
                )
                messages.append(
                    LLMMessage(
                        role="tool",
                        content=json.dumps(truncated, ensure_ascii=False),
                        tool_call_id=tc.tool_use_id,
                    )
                )

            turn_ctx.tool_call_count += 1

            # Inject image data as user message content_parts
            # (OpenAI API requires image_url parts in user messages, not tool messages)
            image_parts: list[dict] = []
            logger.debug(
                "InferenceStep: checking %d tool call results for image data",
                len(pending_tool_calls),
            )
            for log_entry in turn_ctx.tool_calls_log[-len(pending_tool_calls) :]:
                result = log_entry.get("result_raw", log_entry.get("result", {}))
                if isinstance(result, dict):
                    ct = result.get("content_type", "image/png")
                    if result.get("content_base64"):
                        logger.info(
                            "InferenceStep: found content_base64 in tool result (len=%d)", len(result["content_base64"])
                        )
                        image_parts.append(
                            {
                                "type": "image_url",
                                "image_url": {"url": f"data:{ct};base64,{result['content_base64']}", "detail": "auto"},
                            }
                        )
                    if result.get("artifacts"):
                        logger.info("InferenceStep: found %d artifacts in tool result", len(result["artifacts"]))
                        for b64 in result["artifacts"]:
                            if isinstance(b64, str) and len(b64) > 100:
                                image_parts.append(
                                    {
                                        "type": "image_url",
                                        "image_url": {"url": f"data:image/png;base64,{b64}", "detail": "auto"},
                                    }
                                )
                    if result.get("images"):
                        logger.info("InferenceStep: found %d images in tool result", len(result["images"]))
                        for img in result["images"]:
                            if isinstance(img, dict) and img.get("base64"):
                                image_parts.append(
                                    {
                                        "type": "image_url",
                                        "image_url": {"url": f"data:image/png;base64,{img['base64']}", "detail": "auto"},
                                    }
                                )

            if image_parts:
                logger.info(
                    "InferenceStep: injecting %d image content_parts into user message (types: %s)",
                    len(image_parts),
                    [p.get("type", "?") for p in image_parts],
                )
                messages.append(
                    LLMMessage(
                        role="user",
                        content="The tool execution produced image(s). Please analyze:",
                        content_parts=[
                            {
                                "type": "text",
                                "text": "The previous tool execution produced the following image(s). Please analyze them carefully.",
                            },
                            *image_parts,
                        ],
                    )
                )
            else:
                logger.debug(
                    "InferenceStep: no image data found in %d tool calls",
                    len(pending_tool_calls),
                )

        # messages (with tool calls) を turn_ctx に保存（PostStep用）
        turn_ctx.messages = messages
