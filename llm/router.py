import logging
from typing import Any, Dict, List, Optional, Union
from llm.base import LLMProvider, Message, LLMResponse

# タスク種別 → プロバイダーのデフォルトルーティングテーブル。
# 値は str（プロバイダー名）または dict（{"provider": str, "model": str}）。
DEFAULT_ROUTING_TABLE: Dict[str, Union[str, Dict[str, str]]] = {
    "greeting":          "ollama",
    "diary":             "ollama",
    "discord_reply":     "ollama",
    "consciousness":     "ollama",
    "web_reply":         "ollama",
    "memory_elevation":  "claude",
    "anniversary":       "claude",
    "summarization":     "openrouter",
    "goal_generation":   "openrouter",
    "default":           "ollama",
}


class LLMRouter:
    def __init__(
        self,
        providers: Dict[str, LLMProvider],
        routing_table: Optional[Dict[str, Union[str, Dict[str, str]]]] = None,
    ):
        self.providers = providers  # {"ollama": OllamaProvider(...), ...}
        self.routing_table = {**DEFAULT_ROUTING_TABLE, **(routing_table or {})}
        self.logger = logging.getLogger(__name__)

    def _resolve_entry(self, task_type: str) -> tuple[str, Optional[str]]:
        """タスク種別からプロバイダー名とモデルオーバーライドを返す。

        Returns:
            (provider_name, model_override) のタプル。
            model_override は None の場合プロバイダーのデフォルトモデルを使用する。
        """
        entry = self.routing_table.get(task_type, self.routing_table.get("default", "ollama"))
        if isinstance(entry, str):
            return entry, None
        elif isinstance(entry, dict):
            return entry.get("provider", "ollama"), entry.get("model") or None
        return "ollama", None

    async def generate(
        self,
        messages: List[Message],
        task_type: str = "default",
        model: Optional[str] = None,
        max_tokens: int = 1000,
        temperature: float = 0.7,
        tools: Optional[List[dict]] = None,
    ) -> LLMResponse:
        """タスク種別に基づいてプロバイダーを選択し LLM に問い合わせる。

        Args:
            messages: 会話履歴。
            task_type: ルーティングテーブルのキー（例: "consciousness", "web_reply"）。
            model: 明示的なモデル指定（routing_table のモデル設定より優先）。
            max_tokens: 最大生成トークン数。
            temperature: 生成温度。
            tools: ツール定義リスト。None の場合はツールなし。

        Returns:
            LLMResponse。全プロバイダー失敗時は error フィールド付きで返す。
        """
        provider_name, routing_model = self._resolve_entry(task_type)
        # 明示的な model 引数 > routing table のモデル指定 の優先順
        use_model = model or routing_model

        # フォールバック順序: 指定プロバイダー → ollama → claude → openrouter
        fallback_order = [provider_name, "ollama", "claude", "openrouter"]
        seen: set[str] = set()
        for name in fallback_order:
            if name in seen or name not in self.providers:
                continue
            seen.add(name)
            provider = self.providers[name]
            try:
                if not await provider.is_available():
                    continue
                response = await provider.generate(
                    messages,
                    model=use_model,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    tools=tools,
                )
                if response.error:
                    continue
                return response
            except Exception as e:
                self.logger.warning(f"Provider {name} failed: {e}")
                continue

        # 全プロバイダー失敗
        return LLMResponse(
            content="[LLM unavailable]",
            model="none",
            provider="none",
            error="All providers failed",
        )

    async def get_provider_status(self) -> Dict[str, bool]:
        status: Dict[str, bool] = {}
        for name, provider in self.providers.items():
            try:
                status[name] = await provider.is_available()
            except Exception:
                status[name] = False
        return status
