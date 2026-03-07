from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

@dataclass
class Message:
    role: str  # "user" | "assistant" | "system" | "tool"
    content: str

@dataclass
class LLMResponse:
    content: str
    model: str
    provider: str = ""
    usage: Optional[Dict[str, int]] = None
    error: Optional[str] = None
    # ツール呼び出しがあった場合に設定される。
    # 各要素: {"id": str, "name": str, "arguments": dict}
    tool_calls: Optional[List[Dict[str, Any]]] = None

class LLMProvider(ABC):
    @abstractmethod
    async def generate(
        self,
        messages: List[Message],
        model: Optional[str] = None,
        max_tokens: int = 1000,
        temperature: float = 0.7,
        tools: Optional[List[dict]] = None,
    ) -> LLMResponse:
        """LLM にメッセージを送り返答を生成する。

        Args:
            messages: 会話履歴。
            model: 使用するモデル名（None でプロバイダーデフォルト）。
            max_tokens: 最大生成トークン数。
            temperature: 生成温度（0.0〜2.0）。
            tools: ツール定義リスト（OpenAI function calling 形式）。
                   None の場合はツール機能を使用しない。

        Returns:
            LLMResponse。tool_calls がある場合は content が空の場合もある。
        """
        ...

    @abstractmethod
    async def is_available(self) -> bool:
        ...
