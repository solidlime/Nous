from __future__ import annotations

from typing import TYPE_CHECKING

from .anthropic import AnthropicProvider

if TYPE_CHECKING:
    from .base import LLMProvider


def get_provider(provider: str, api_key: str, model: str, base_url: str = "") -> LLMProvider:
    from .google import GeminiProvider
    from .openai_compat import OpenAICompatProvider, _OPENAI_BASE_URL, _OPENROUTER_BASE_URL  # noqa: I001

    if provider == "anthropic":
        return AnthropicProvider(api_key=api_key, model=model)
    elif provider == "openai":
        return OpenAICompatProvider(api_key=api_key, model=model, base_url=base_url or _OPENAI_BASE_URL)
    elif provider == "openrouter":
        return OpenAICompatProvider(api_key=api_key, model=model, base_url=base_url or _OPENROUTER_BASE_URL)
    elif provider == "google":
        return GeminiProvider(api_key=api_key, model=model, base_url=base_url)
    else:
        raise ValueError(f"Unknown LLM provider: {provider}. Supported: anthropic, openai, openrouter, google")
