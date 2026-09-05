"""SessionSummarizer: 会話ターンを記憶に圧縮して保存する。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from nous.domain.language import LanguageResolver
from nous.infrastructure.llm.base import LLMMessage
from nous.infrastructure.llm.factory import get_provider
from nous.infrastructure.logging.structured import get_logger

if TYPE_CHECKING:
    from nous.application.use_cases import AppContext
    from nous.domain.chat_config import ChatConfig

logger = get_logger(__name__)

_SUMMARIZE_PROMPT = """\
Summarize the following conversation in 2-3 sentences in {language}.
Prioritize important information, decisions, and emotional events.
Write the summary in first person as {persona} (そのキャラクター自身の一人称で書くこと)。

[Conversation]
{conversation}

[Output]
Summary only. No JSON.
"""


async def summarize_and_store(
    ctx: AppContext,
    config: ChatConfig,
    turns: list[dict],
) -> str | None:
    """古い会話ターンをLLMで要約して記憶に保存する。

    Args:
        ctx: AppContext
        config: ChatConfig
        turns: {"role": str, "content": str} の辞書リスト

    Returns:
        生成された要約文字列。スキップ時またはエラー時はNone。
    """
    if not getattr(config, "session_summarize", True):
        return None

    if not turns:
        return None

    api_key = config.get_effective_api_key()
    model = config.extract_model.strip() or config.get_effective_model()
    if not api_key or not model:
        return None

    conversation_lines = []
    persona = ctx.persona
    for turn in turns:
        role = turn.get("role", "unknown")
        content = turn.get("content", "")
        if role == "user":
            conversation_lines.append(f"User: {content[:300]}")
        elif role == "assistant":
            conversation_lines.append(f"{persona}: {content[:300]}")

    if not conversation_lines:
        return None

    language_resolver = LanguageResolver(config)
    lang = language_resolver.resolve()
    prompt = _SUMMARIZE_PROMPT.format(
        language=LanguageResolver.display_name(lang),
        persona=persona,
        conversation="\n".join(conversation_lines),
    )

    try:
        provider = get_provider(config.provider, api_key, model, config.get_effective_base_url())
    except Exception as e:
        logger.warning("SessionSummarizer: provider init failed: %s", e)
        return None

    from nous.infrastructure.llm.base import DoneEvent, ErrorEvent, TextDeltaEvent

    text = ""
    try:
        async for event in provider.stream(
            messages=[LLMMessage(role="user", content=prompt)],
            system="",
            tools=[],
            temperature=0.0,
            max_tokens=256,
        ):
            if isinstance(event, TextDeltaEvent):
                text += event.content
            elif isinstance(event, (DoneEvent, ErrorEvent)):
                break
    except Exception as e:
        logger.warning("SessionSummarizer: LLM call failed: %s", e)
        return None

    summary = text.strip()
    if not summary:
        return None

    # Byte-level BPE トークナイザ由来の文字化けチェック
    # N'Ko, Mongolian, PUA, Surrogates の異常Unicodeブロック検出
    suspicious_ranges = [
        (0x07C0, 0x07FF),  # N'Ko
        (0x1800, 0x18AF),  # Mongolian
        (0xE000, 0xF8FF),  # Private Use Area
        (0xD800, 0xDFFF),  # Surrogates
    ]
    suspicious = [ch for ch in summary if any(lo <= ord(ch) <= hi for lo, hi in suspicious_ranges)]
    if suspicious and len(suspicious) / len(summary) > 0.1:
        logger.warning(
            "SessionSummarizer: discarding summary with %.0f%% suspicious chars", len(suspicious) / len(summary) * 100
        )
        return None

    await ctx.memory_service.create_memory(
        content=summary,
        importance=0.65,
        tags=["session_summary"],
        emotion="neutral",
    )
    logger.debug("SessionSummarizer: stored summary for persona=%s (%d chars)", ctx.persona, len(summary))
    return summary
