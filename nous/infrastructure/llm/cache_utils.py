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


def build_openai_system_messages(system: str) -> list[dict]:
    """Build OpenAI/OpenRouter ``messages`` entry with prompt caching.

    When the boundary marker is present::

        [{"role": "system", "content": [
            {"type": "text", "text": static, "cache_control": {"type": "ephemeral"}},
            {"type": "text", "text": dynamic},   # 空なら省略
        ]}]

    Without the marker::

        [{"role": "system", "content": system}]
    """
    static_part, dynamic_part = split_system_prompt(system)
    # commandcode.ai 等は空 content の system メッセージを 400 で拒否する
    # （2026-08-30 実機 curl 確認）。空 system はメッセージ自体を省略する。
    if not system.strip():
        return []
    # marker が無い = 静的分割の意思が無い → 文字列単一形式（従来動作）
    if _BOUNDARY not in system:
        return [{"role": "system", "content": system}]

    content: list[dict] = [{"type": "text", "text": static_part, "cache_control": {"type": "ephemeral"}}]
    # 動的部が空でも parts 形式を保つ（marker の有無が形式の合図）
    if dynamic_part:
        content.append({"type": "text", "text": dynamic_part})
    return [{"role": "system", "content": content}]
