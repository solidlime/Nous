from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .base import LLMProvider


_PROVIDER_REGISTRY = {
    "anthropic": {
        "class": "anthropic",
        "default_base_url": "",
    },
    "openai": {
        "class": "openai_compat",
        "default_base_url": "https://api.openai.com/v1",
    },
    "openrouter": {
        "class": "openai_compat",
        "default_base_url": "https://openrouter.ai/api/v1",
    },
    "google": {
        "class": "gemini",
        "default_base_url": "https://generativelanguage.googleapis.com/v1beta/openai/",
    },
    "opencode_go": {
        "class": "openai_compat",
        "default_base_url": "https://opencode.ai/zen/go/v1",
    },
}


def get_provider(provider: str, api_key: str, model: str, base_url: str = "") -> LLMProvider:
    entry = _PROVIDER_REGISTRY.get(provider)
    if not entry:
        raise ValueError(f"Unknown provider: {provider}")

    resolved_base_url = base_url or entry["default_base_url"]
    provider_class = entry["class"]

    if provider_class == "anthropic":
        from .anthropic import AnthropicProvider

        return AnthropicProvider(api_key=api_key, model=model)
    elif provider_class == "gemini":
        from .google import GeminiProvider

        return GeminiProvider(api_key=api_key, model=model, base_url=resolved_base_url)
    else:
        from .openai_compat import OpenAICompatProvider

        return OpenAICompatProvider(api_key=api_key, model=model, base_url=resolved_base_url)
