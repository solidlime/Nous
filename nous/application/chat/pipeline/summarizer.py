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
    def _should_summarize(messages: list[LLMMessage], config: ChatConfig) -> bool:
        """Check if LLM summarization should be attempted.

        Conditions:
        1. Feature flag is enabled
        2. Provider is configured (has API key)
        3. More user messages than context_keep_recent_turns (i.e. there are messages
           beyond what's being kept intact to summarize)
        """
        if not getattr(config, "context_use_llm_summary", True):
            return False
        if not config.is_configured():
            return False
        # Count turns by counting user messages
        user_count = sum(1 for m in messages if m.role == "user")
        keep = getattr(config, "context_keep_recent_turns", 2)
        return user_count > keep

    async def _summarize_old_turns(
        self,
        config: ChatConfig,
        messages: list[LLMMessage],
        keep_recent: int,
    ) -> str | None:
        """Call LLM to summarize old conversation turns.

        Takes all messages except the most recent ``keep_recent * 2``,
        strips tool messages, truncates long content to 500 chars,
        and sends to the LLM for a ~300 char Japanese summary.

        Returns:
            要約文字列。条件不成立時またはエラー時は None。
        """
        keep_count = keep_recent * 2
        if len(messages) <= keep_count:
            return None

        old_messages = messages[:-keep_count]

        # Build conversation text for summarization:
        # - Only user and assistant roles (skip tool messages)
        # - Truncate each message content to 500 chars
        lines: list[str] = []
        for msg in old_messages:
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
