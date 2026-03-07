import aiohttp
import json
import logging
from typing import Any, Dict, List, Optional
from llm.base import LLMProvider, Message, LLMResponse


class OllamaProvider(LLMProvider):
    def __init__(self, base_url: str = "http://localhost:11434", model: str = "mistral", timeout: int = 120):
        self.base_url = base_url.rstrip("/")
        self.default_model = model
        self.timeout = timeout
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
        payload: Dict[str, Any] = {
            "model": use_model,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            "stream": False,
            "options": {
                "num_predict": max_tokens,
                "temperature": temperature,
            },
        }
        if tools:
            payload["tools"] = tools

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{self.base_url}/api/chat",
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=self.timeout),
                ) as resp:
                    if resp.status != 200:
                        text = await resp.text()
                        return LLMResponse(
                            content="",
                            model=use_model,
                            provider="ollama",
                            error=f"HTTP {resp.status}: {text}",
                        )
                    data = await resp.json()
                    msg = data.get("message", {})
                    content = msg.get("content", "")

                    # ツール呼び出しのパース
                    raw_tool_calls = msg.get("tool_calls")
                    tool_calls = None
                    if raw_tool_calls:
                        tool_calls = []
                        for i, tc in enumerate(raw_tool_calls):
                            fn = tc.get("function", {})
                            args = fn.get("arguments", {})
                            if isinstance(args, str):
                                try:
                                    args = json.loads(args)
                                except Exception:
                                    args = {}
                            tool_calls.append({
                                "id": tc.get("id", f"call_{i}"),
                                "name": fn.get("name", ""),
                                "arguments": args,
                            })

                    return LLMResponse(
                        content=content,
                        model=use_model,
                        provider="ollama",
                        usage={"total_tokens": data.get("eval_count", 0)},
                        tool_calls=tool_calls,
                    )
        except Exception as e:
            return LLMResponse(content="", model=use_model, provider="ollama", error=str(e))

    async def is_available(self) -> bool:
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"{self.base_url}/api/version",
                    timeout=aiohttp.ClientTimeout(total=5),
                ) as resp:
                    return resp.status == 200
        except Exception:
            return False
