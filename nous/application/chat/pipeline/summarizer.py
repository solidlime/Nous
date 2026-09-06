"""LLM要約処理: トークン予算超過時に古い会話ターンをLLMで要約する。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from nous.domain.language import LanguageResolver
from nous.infrastructure.logging.structured import get_logger

if TYPE_CHECKING:
    from nous.domain.chat_config import ChatConfig
    from nous.infrastructure.llm.base import LLMMessage

logger = get_logger(__name__)

SUMMARIZE_PROMPT = """Summarize the conversation history below, in {language}.
Prioritize: user statements, decisions, preferences, promises, emotional events.
Keep the summary within approximately 300 characters.

Conversation history:
{conversation}

Summary:"""


class SummarizerMixin:
    """LLMによる会話要約機能を提供するミックスイン。"""

    @staticmethod
    def _should_summarize(removed: list[LLMMessage], config: ChatConfig) -> bool:
        """Check if LLM summarization should be attempted.

        Conditions:
        1. Feature flag is enabled
        2. Provider is configured (has API key)
        3. The removed slice (Stage 0) contains user content to summarize
        """
        if not getattr(config, "context_use_llm_summary", True):
            return False
        if not config.is_configured():
            return False
        return any(m.role == "user" and m.content for m in removed)

    async def _summarize_old_turns(
        self,
        config: ChatConfig,
        removed: list[LLMMessage],
    ) -> str | None:
        """Call LLM to summarize the Stage 0 removed message slice.

        The removed slice is everything Stage 0 cut off (before the recent
        window). Strips tool messages, truncates long content to 500 chars,
        and asks the LLM for a ~300 char summary.

        Returns:
            要約文字列。条件不成立時またはエラー時は None。
        """
        if not removed:
            return None

        # Build conversation text for summarization:
        # - Only user and assistant roles (skip tool messages)
        # - Truncate each message content to 500 chars
        lines: list[str] = []
        for msg in removed:
            if msg.role == "user":
                content = (msg.content or "")[:500]
                lines.append(f"User: {content}")
            elif msg.role == "assistant":
                content = (msg.content or "")[:500]
                lines.append(f"Assistant: {content}")

        if not lines:
            return None

        language_resolver = LanguageResolver(config)
        lang = language_resolver.resolve()
        prompt = SUMMARIZE_PROMPT.format(
            language=LanguageResolver.display_name(lang),
            conversation="\n".join(lines),
        )

        from nous.infrastructure.llm.base import DoneEvent, ErrorEvent, LLMMessage, TextDeltaEvent
        from nous.infrastructure.llm.factory import get_provider

        try:
            provider = get_provider(
                config.provider,
                config.get_effective_api_key(),
                config.get_effective_model(),
                config.get_effective_base_url(),
            )
        except Exception:
            logger.warning("CompressStep: Stage 4 — provider init failed")
            return None

        text = ""
        try:
            async for event in provider.stream(
                messages=[LLMMessage(role="user", content=prompt)],
                system="",
                tools=[],
                temperature=0.0,
                max_tokens=512,
            ):
                if isinstance(event, TextDeltaEvent):
                    text += event.content
                elif isinstance(event, (DoneEvent, ErrorEvent)):
                    break
        except Exception as e:
            logger.warning("CompressStep: Stage 4 — LLM call failed: %s", e)
            return None

        summary = text.strip()
        return summary if summary else None
