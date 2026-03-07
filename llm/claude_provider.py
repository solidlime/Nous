import json
import os
import logging
from typing import Any, Dict, List, Optional
from llm.base import LLMProvider, Message, LLMResponse


class ClaudeProvider(LLMProvider):
    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = "claude-sonnet-4-6",
        max_tokens: int = 1000,
    ):
        self.api_key = api_key or os.getenv("ANTHROPIC_API_KEY", "")
        self.default_model = model
        self.default_max_tokens = max_tokens
        self.logger = logging.getLogger(__name__)
        self._client = None

    def _get_client(self):
        if self._client is None:
            from anthropic import AsyncAnthropic
            self._client = AsyncAnthropic(api_key=self.api_key)
        return self._client

    def _convert_tools_to_anthropic(self, tools: List[dict]) -> List[dict]:
        """OpenAI function calling 形式を Anthropic tools 形式に変換する。"""
        result = []
        for tool in tools:
            if tool.get("type") == "function":
                fn = tool["function"]
                result.append({
                    "name": fn["name"],
                    "description": fn.get("description", ""),
                    "input_schema": fn.get("parameters", {"type": "object", "properties": {}}),
                })
        return result

    async def generate(
        self,
        messages: List[Message],
        model: Optional[str] = None,
        max_tokens: int | None = None,
        temperature: float = 0.7,
        tools: Optional[List[dict]] = None,
    ) -> LLMResponse:
        use_model = model or self.default_model
        use_max_tokens = max_tokens or self.default_max_tokens

        # システムメッセージとツール結果メッセージを適切に変換
        system_content = ""
        chat_messages: list[dict] = []
        for m in messages:
            if m.role == "system":
                system_content += m.content + "\n"
            elif m.role == "tool":
                # ツール結果はユーザーメッセージ内の tool_result コンテンツブロックとして送る
                try:
                    result_data = json.loads(m.content)
                    tool_call_id = result_data.get("tool_call_id", "unknown")
                    tool_content = result_data.get("content", m.content)
                except Exception:
                    tool_call_id = "unknown"
                    tool_content = m.content
                chat_messages.append({
                    "role": "user",
                    "content": [{"type": "tool_result", "tool_use_id": tool_call_id, "content": tool_content}],
                })
            else:
                chat_messages.append({"role": m.role, "content": m.content})

        if not chat_messages:
            chat_messages = [{"role": "user", "content": "(empty)"}]

        try:
            client = self._get_client()
            kwargs: Dict[str, Any] = {
                "model": use_model,
                "max_tokens": use_max_tokens,
                "messages": chat_messages,
            }
            if system_content.strip():
                kwargs["system"] = system_content.strip()
            if tools:
                kwargs["tools"] = self._convert_tools_to_anthropic(tools)

            response = await client.messages.create(**kwargs)

            # コンテンツからテキストとツール呼び出しを抽出
            content_text = ""
            tool_calls = None
            for block in response.content:
                if block.type == "text":
                    content_text += block.text
                elif block.type == "tool_use":
                    if tool_calls is None:
                        tool_calls = []
                    tool_calls.append({
                        "id": block.id,
                        "name": block.name,
                        "arguments": block.input if isinstance(block.input, dict) else {},
                    })

            return LLMResponse(
                content=content_text,
                model=use_model,
                provider="claude",
                usage={
                    "input_tokens": response.usage.input_tokens,
                    "output_tokens": response.usage.output_tokens,
                },
                tool_calls=tool_calls,
            )
        except Exception as e:
            return LLMResponse(content="", model=use_model, provider="claude", error=str(e))

    async def is_available(self) -> bool:
        return bool(self.api_key)
