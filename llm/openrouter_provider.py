import aiohttp
import json
import os
import logging
from typing import Any, Dict, List, Optional
from llm.base import LLMProvider, Message, LLMResponse


class OpenRouterProvider(LLMProvider):
    BASE_URL = "https://openrouter.ai/api/v1/chat/completions"

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = "anthropic/claude-3.5-sonnet",
        site_url: str = "https://nous.local",
        app_name: str = "Nous",
    ):
        self.api_key = api_key or os.getenv("OPENROUTER_API_KEY", "")
        self.default_model = model
        self.site_url = site_url
        self.app_name = app_name
        self.logger = logging.getLogger(__name__)

    async def generate(
        self,
        messages: List[Message],
        model: Optional[str] = None,
        max_tokens: int = 1000,
        temperature: float = 0.7,
        tools: Optional[List[dict]] = None,
    ) -> LLMResponse:
        use_model = model or self.default_model
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "HTTP-Referer": self.site_url,
            "X-Title": self.app_name,
            "Content-Type": "application/json",
        }
        # tool role を OpenAI 形式に変換
        openai_messages = []
        for m in messages:
            if m.role == "tool":
                try:
                    result_data = json.loads(m.content)
                    openai_messages.append({
                        "role": "tool",
                        "tool_call_id": result_data.get("tool_call_id", "unknown"),
                        "content": result_data.get("content", m.content),
                    })
                except Exception:
                    openai_messages.append({"role": "user", "content": m.content})
            else:
                openai_messages.append({"role": m.role, "content": m.content})

        payload: Dict[str, Any] = {
            "model": use_model,
            "messages": openai_messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    self.BASE_URL,
                    headers=headers,
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=60),
                ) as resp:
                    data = await resp.json()
                    if resp.status != 200:
                        return LLMResponse(
                            content="", model=use_model, provider="openrouter", error=str(data)
                        )
                    choice = data["choices"][0]
                    msg = choice.get("message", {})
                    content = msg.get("content") or ""
                    usage = data.get("usage", {})

                    # ツール呼び出しのパース
                    raw_tool_calls = msg.get("tool_calls")
                    tool_calls = None
                    if raw_tool_calls:
                        tool_calls = []
                        for tc in raw_tool_calls:
                            fn = tc.get("function", {})
                            args = fn.get("arguments", "{}")
                            if isinstance(args, str):
                                try:
                                    args = json.loads(args)
                                except Exception:
                                    args = {}
                            tool_calls.append({
                                "id": tc.get("id", ""),
                                "name": fn.get("name", ""),
                                "arguments": args,
                            })

                    return LLMResponse(
                        content=content,
                        model=use_model,
                        provider="openrouter",
                        usage=usage,
                        tool_calls=tool_calls,
                    )
        except Exception as e:
            return LLMResponse(content="", model=use_model, provider="openrouter", error=str(e))

    async def is_available(self) -> bool:
        return bool(self.api_key)
