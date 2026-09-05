"""InferenceStep: LLMストリームループとツール実行。"""

from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime
from typing import TYPE_CHECKING

from nous.application.chat.events import (
    ErrorSSE,
    ImageGenResultSSE,
    ImageGenStartSSE,
    TextDeltaSSE,
    ThinkingDeltaSSE,
    ToolCallSSE,
    ToolResultSSE,
)
from nous.infrastructure.llm.base import (
    DoneEvent,
    ErrorEvent,
    LLMMessage,
    TextDeltaEvent,
    ThinkingDeltaEvent,
    ToolCallEvent,
)
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
    ) -> AsyncIterator[
        TextDeltaSSE | ThinkingDeltaSSE | ToolCallSSE | ToolResultSSE | ErrorSSE | ImageGenStartSSE | ImageGenResultSSE
    ]:
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

        messages = list(session_messages)

        # §1 Recency digest: 最新 user 発言の直前に合成メッセージ（非永続化・毎ターン再構築）
        if getattr(turn_ctx, "recency_digest", ""):
            messages.append(LLMMessage(role="user", content=turn_ctx.recency_digest))

        if turn_ctx.images:
            if not provider.supports_vision():
                logger.info(
                    "Provider %s does not support vision, captioning %d images",
                    config.provider,
                    len(turn_ctx.images),
                )
                from nous.infrastructure.llm.image_caption import ImageCaptioner

                captioner = ImageCaptioner(config=config.tool_config)
                captions = await captioner.caption_batch(turn_ctx.images)
                caption_text = "\n".join(f"[Image {i + 1}]: {c}" for i, c in enumerate(captions) if c)
                if caption_text:
                    turn_ctx.user_message = (
                        f"{turn_ctx.user_message}\n\n---\nAttached images described:\n{caption_text}"
                    )
                else:
                    logger.warning(
                        "Image captioning failed for %d images, attaching fallback note",
                        len(turn_ctx.images),
                    )
                    turn_ctx.user_message = (
                        f"[User attached {len(turn_ctx.images)} image(s) but current model does not support vision]\n"
                        f"{turn_ctx.user_message}"
                    )
                messages.append(LLMMessage(role="user", content=turn_ctx.user_message, timestamp=datetime.now()))
            else:
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
                messages.append(
                    LLMMessage(
                        role="user", content=turn_ctx.user_message, content_parts=parts, timestamp=datetime.now()
                    )
                )
        else:
            messages.append(LLMMessage(role="user", content=turn_ctx.user_message, timestamp=datetime.now()))

        temperature = effective_temp if effective_temp is not None else config.temperature
        max_continuation_rounds = 3
        _continuation_rounds = 0
        while turn_ctx.tool_call_count <= config.max_tool_calls:
            pending_tool_calls: list[ToolCallEvent] = []
            current_text = ""
            _seg_text = ""  # text accumulator for segment ordering
            _thinking_text = ""  # thinking accumulator for CoT segments (SPEC R5)
            _finish_reason = ""  # set by DoneEvent handler inside stream loop
            # 既に実行済みの tool_use_id（同一ターン内の再送を排除するため。
            # tool_call segment / SSE / pending への記録より先に除外しないと
            # 「結果無し tool_call」が履歴に永続化され、次ターン以降プロバイダが 400 を返す）
            executed_ids = {tc.get("id", "") for tc in (turn_ctx.tool_calls_log or [])}
            seen_ids: set[str] = set()

            # 各ループ反復で visible tools を再評価（search_tools で新発見を拾う）
            # max_tool_calls の予算を使い切ったらツールを渡さない（0 設定なら最初から渡さない）
            visible_tools = registry.get_visible_tools() if turn_ctx.tool_call_count < config.max_tool_calls else []

            # タイムスタンプ注入（設定ON時のみ）— debug dumpより先に注入
            # HTML comment format: LLM sees timestamp but does not echo it in output
            # 注入はコピーに対して行う（session_messages の LLMMessage は共有オブジェクトのため）
            if getattr(config, "show_message_timestamps", False):
                from dataclasses import replace
                from zoneinfo import ZoneInfo

                from nous.config.settings import get_settings

                tz = ZoneInfo(get_settings().timezone)
                for i, msg in enumerate(messages):
                    if msg.timestamp and msg.role in ("user", "assistant"):
                        ts = msg.timestamp if msg.timestamp.tzinfo else msg.timestamp.replace(tzinfo=tz)
                        ts_str = ts.astimezone(tz).strftime("%Y-%m-%d %H:%M")
                        prefix = f"<!-- msg_at: {ts_str} -->"
                        if not str(msg.content).startswith("<!-- msg_at:"):
                            messages[i] = replace(msg, content=f"{prefix}{msg.content}")

            # Debug: capture the full prompt sent to LLM
            if getattr(config, "debug_mode", False):
                import tempfile

                _ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
                _debug_dir = os.path.join(tempfile.gettempdir(), "nous_debug")
                os.makedirs(_debug_dir, exist_ok=True)
                _path = os.path.join(_debug_dir, f"prompt_{_ts}.txt")
                with open(_path, "w", encoding="utf-8") as _f:
                    _f.write(f"=== SYSTEM PROMPT ({len(turn_ctx.system_prompt)} chars) ===\n")
                    _f.write(turn_ctx.system_prompt)
                    _f.write(f"\n\n=== MESSAGES ({len(messages)} total) ===\n")
                    for _i, _m in enumerate(messages):
                        role = _m.role if hasattr(_m, "role") else "?"
                        content = str(_m.content)[:2000] if hasattr(_m, "content") else str(_m)[:2000]
                        _f.write(f"\n[{_i}] {role}: {content}\n")
                    _f.write(f"\n\n=== TOOLS ({len(visible_tools)} total) ===\n")
                    for _t in visible_tools:
                        name = (
                            _t.get("function", {}).get("name", "?")
                            if isinstance(_t, dict)
                            else getattr(_t, "name", "?")
                        )
                        _f.write(f"  - {name}\n")
                logger.info("Debug prompt saved: %s", _path)

            async for event in provider.stream(
                messages=messages,
                system=turn_ctx.system_prompt,
                tools=visible_tools,
                temperature=temperature,
                max_tokens=config.max_tokens,
                top_p=config.top_p,
                reasoning_effort=config.reasoning_effort if config.reasoning_enabled else None,
            ):
                if isinstance(event, TextDeltaEvent):
                    current_text += event.content
                    turn_ctx.full_response += event.content
                    _seg_text += event.content
                    yield TextDeltaSSE(content=event.content)
                elif isinstance(event, ThinkingDeltaEvent):
                    # CoT: accumulate separately — never mixed into text/full_response (TTS excluded)
                    _thinking_text += event.content
                    yield ThinkingDeltaSSE(content=event.content)
                elif isinstance(event, ToolCallEvent):
                    # Skip tool calls already executed this turn or duplicated within
                    # this batch — record nothing (no SSE / segment / pending entry),
                    # otherwise a result-less tool_call would be persisted and the
                    # provider would reject the rebuilt history next turn.
                    if event.tool_use_id in executed_ids or event.tool_use_id in seen_ids:
                        logger.info("Skipping duplicate tool call (id=%s)", event.tool_use_id)
                        continue
                    # Guard against None from buggy provider implementations.
                    # Note: {} is a valid tool input (parameterless tools).
                    if event.tool_input is None:
                        logger.warning("Skipping tool call with None input (id=%s)", event.tool_use_id)
                        continue
                    seen_ids.add(event.tool_use_id)
                    # Flush accumulated text as segment before tool call
                    if _seg_text:
                        turn_ctx.segments.append({"type": "text", "content": _seg_text})
                        _seg_text = ""
                    # Flush accumulated thinking as segment before tool call
                    if _thinking_text:
                        turn_ctx.segments.append({"type": "thinking", "content": _thinking_text})
                        _thinking_text = ""
                    yield ToolCallSSE(name=event.tool_name, input=event.tool_input, id=event.tool_use_id)
                    turn_ctx.segments.append(
                        {
                            "type": "tool_call",
                            "name": event.tool_name,
                            "input": event.tool_input,
                            "id": event.tool_use_id,
                        }
                    )
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
            # Flush remaining thinking segment after inner loop (SPEC R5)
            if _thinking_text:
                turn_ctx.segments.append({"type": "thinking", "content": _thinking_text})
                _thinking_text = ""

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
                    # Non-empty placeholder: Anthropic rejects empty user messages (400)
                    messages.append(LLMMessage(role="user", content="(continue)"))
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

            # 重複排除はストリーム中の ToolCallEvent 処理時に実施済み（executed_ids / seen_ids）

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
                    logger.info(
                        "ImageGenResultSSE: yielding %d image(s) to frontend",
                        len(imgs) if isinstance(imgs, list) else 0,
                    )
                    yield ImageGenResultSSE(
                        provider=tool_result.get("provider", "comfyui"),
                        images=tool_result["images"],
                        tool_use_id=tc.tool_use_id,
                        self_portrait=tool_result.get("self_portrait", False),
                    )
                turn_ctx.segments.append(
                    {"type": "tool_result", "name": tc.tool_name, "result": truncated, "id": tc.tool_use_id}
                )
                # result_raw は DB 保存用: base64 を除去し url を残す（SSE では使わない）
                result_for_log = tool_result
                if isinstance(tool_result, dict) and tool_result.get("images"):
                    result_for_log = dict(tool_result)
                    result_for_log["images"] = [
                        {k: v for k, v in img.items() if k != "base64"} for img in tool_result["images"]
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
                len(results),
            )
            for _tc, _truncated, raw_result in results:
                result = raw_result
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
                                        "image_url": {
                                            "url": f"data:image/png;base64,{img['base64']}",
                                            "detail": "auto",
                                        },
                                    }
                                )

            if image_parts:
                if not provider.supports_vision():
                    logger.info(
                        "InferenceStep: omitting %d image(s) for text-only model",
                        len(image_parts),
                    )
                    messages.append(
                        LLMMessage(
                            role="user",
                            content=(
                                f"The previous tool execution produced {len(image_parts)} image(s), "
                                "but the current model does not support vision. "
                                "Continuing text-only."
                            ),
                        )
                    )
                else:
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
