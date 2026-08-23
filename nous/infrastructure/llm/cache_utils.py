"""Prompt caching utilities for LLM providers.

Provides shared functions to split system prompts at a boundary marker
and build provider-specific structures with cache_control annotations.
"""

_BOUNDARY = "<!-- __STATIC_END__ -->"


def split_system_prompt(system: str) -> tuple[str, str]:
    """Split system prompt into static/dynamic parts.

    Uses ``<!-- __STATIC_END__ -->`` as the boundary marker.
    Returns (static_part, dynamic_part).
    If the marker is absent, returns (system, "").
    """
    if _BOUNDARY in system:
        static_part, _, dynamic_part = system.partition(_BOUNDARY)
        return static_part, dynamic_part.strip()
    return system, ""


def build_anthropic_system(system: str) -> str | list[dict]:
    """Build Anthropic API ``system`` parameter with prompt caching.

    When the boundary marker is present::

        [{"type": "text", "text": static, "cache_control": {"type": "ephemeral"}},
         {"type": "text", "text": dynamic}]

    Without the marker, returns the original string unchanged.
    """
    static_part, dynamic_part = split_system_prompt(system)
    if not dynamic_part:
        return system

    blocks: list[dict] = [
        {"type": "text", "text": static_part, "cache_control": {"type": "ephemeral"}},
    ]
    if dynamic_part:
        blocks.append({"type": "text", "text": dynamic_part})
    return blocks


def build_openai_system_messages(system: str) -> list[dict]:
    """Build OpenAI/OpenRouter ``messages`` entry with prompt caching.

    When the boundary marker is present::

        [{"role": "system", "content": [
            {"type": "text", "text": static, "cache_control": {"type": "ephemeral"}},
            {"type": "text", "text": dynamic},
        ]}]

    Without the marker::

        [{"role": "system", "content": system}]
    """
    static_part, dynamic_part = split_system_prompt(system)
    if not dynamic_part:
        return [{"role": "system", "content": system}]

    content: list[dict] = [
        {"type": "text", "text": static_part, "cache_control": {"type": "ephemeral"}},
        {"type": "text", "text": dynamic_part},
    ]
    return [{"role": "system", "content": content}]


# プロバイダごとのキャッシュ戦略
# explicit: cache_control: ephemeral を明示的に付与（Anthropic/OpenRouter/OpenCode Go）
# auto: プロバイダ側の自動キャッシュに任せる（OpenAI/Gemini）
# none: キャッシュ非対応
PROVIDER_CACHE_STRATEGY = {
    "anthropic": "explicit",
    "openai": "auto",
    "openrouter": "explicit",
    "google": "auto",
    "opencode_go": "explicit",
}


def should_add_cache_control(provider: str) -> bool:
    """explicit 戦略のプロバイダかどうか"""
    return PROVIDER_CACHE_STRATEGY.get(provider) == "explicit"


def get_cache_extra_body(provider: str, session_id: str = "") -> dict:
    """プロバイダごとのキャッシュ用 extra_body を返す。
    opencode_go は prompt_cache_retention + prompt_cache_key が必要。
    """
    if provider == "opencode_go":
        body = {"prompt_cache_retention": "24h"}
        if session_id:
            body["prompt_cache_key"] = session_id
        return body
    return {}
