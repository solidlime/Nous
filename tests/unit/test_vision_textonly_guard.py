"""Regression: text-only models must never receive image_url parts (400 guard)."""

from __future__ import annotations

import pytest

from nous.infrastructure.llm.base import LLMMessage
from nous.infrastructure.llm.openai_compat import OpenAICompatProvider, _is_vision_model


def _provider(model: str) -> OpenAICompatProvider:
    return OpenAICompatProvider(api_key="test-key", model=model)


def test_deepseek_flash_not_vision():
    assert _is_vision_model("deepseek-v4-flash") is False


def test_deepseek_vision_exp_is_vision():
    assert _is_vision_model("deepseek-v4-flash-vision-exp") is True


def test_to_api_messages_strips_images_for_text_only():
    p = OpenAICompatProvider(api_key="k", model="deepseek-v4-flash")
    msgs = [
        LLMMessage(
            role="user",
            content="analyze",
            content_parts=[
                {"type": "text", "text": "analyze"},
                {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAA", "detail": "auto"}},
            ],
        )
    ]
    out = p._to_api_messages(msgs)
    assert out[0]["role"] == "user"
    content = out[0]["content"]
    assert isinstance(content, str)
    assert "AAA" not in content
    assert "analyze" in content


def test_to_api_messages_keeps_images_for_vision():
    p = OpenAICompatProvider(api_key="k", model="gpt-4o")
    parts = [
        {"type": "text", "text": "analyze"},
        {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAA", "detail": "auto"}},
    ]
    out = p._to_api_messages([LLMMessage(role="user", content="analyze", content_parts=parts)])
    assert out[0]["content"] == parts


@pytest.mark.asyncio
async def test_inference_skips_image_injection_for_text_only():
    from unittest.mock import AsyncMock, MagicMock, patch

    from nous.application.chat.pipeline.inference import InferenceStep
    from nous.infrastructure.llm.base import DoneEvent, TextDeltaEvent, ToolCallEvent

    captured: list = []

    async def _mock_stream(**kwargs):
        captured.append(kwargs.get("messages", []))
        if len(captured) == 1:
            yield ToolCallEvent(tool_name="image_generate", tool_input={"prompt": "x"}, tool_use_id="t1")
            yield DoneEvent(full_content="", tool_calls=[])
        else:
            yield TextDeltaEvent(content="done")
            yield DoneEvent(full_content="done", tool_calls=[])

    mock_provider = MagicMock()
    mock_provider.stream = _mock_stream
    mock_provider.supports_vision.return_value = False

    config = MagicMock()
    config.debug_mode = False
    config.show_message_timestamps = False
    config.temperature = 0.7
    config.max_tokens = 100
    config.provider = "openai"
    config.get_effective_api_key.return_value = "test-key"
    config.get_effective_model.return_value = "deepseek-v4-flash"
    config.get_effective_base_url.return_value = ""
    config.max_tool_calls = 5
    config.enable_parallel_tools = False
    config.tool_result_max_chars = 4000
    config.top_p = None
    config.reasoning_enabled = False
    config.reasoning_effort = None

    from nous.application.chat.pipeline.context import ChatTurnContext

    turn_ctx = ChatTurnContext(session_id="s", user_message="hi")
    turn_ctx.system_prompt = "sys"
    turn_ctx.segments = []

    registry = MagicMock()
    registry.get_visible_tools.return_value = []
    registry.execute = AsyncMock(
        return_value={"images": [{"base64": "A" * 200, "url": "http://x/y.png"}], "provider": "comfyui"}
    )
    registry.truncate_result = MagicMock(return_value={"status": "ok"})

    with patch("nous.application.chat.pipeline.inference.get_provider", return_value=mock_provider):
        async for _ in InferenceStep().run(MagicMock(), config, [], turn_ctx, registry):
            pass

    assert len(captured) >= 2
    for msgs in captured[1:]:
        for m in msgs:
            parts = getattr(m, "content_parts", None)
            if parts:
                assert all(p.get("type") != "image_url" for p in parts), "image_url leaked to text-only model"
