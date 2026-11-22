"""LLM要約処理: トークン予算超過時に古い会話ターンをLLMで要約する。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from nous.domain.language import LanguageResolver
from nous.infrastructure.logging.structured import get_logger

if TYPE_CHECKING:
    from nous.domain.config.chat_config import ChatConfig
    from nous.infrastructure.llm.base import LLMMessage

logger = get_logger(__name__)

SUMMARIZE_PROMPT = """Summarize the conversation history below, in {language}.
Prioritize: user statements, decisions, preferences, emotional events.
Keep the summary within approximately {summarize_target_chars} characters.

Conversation history:
{conversation}

Summary:"""


class SummarizerMixin:
    """LLMによる会話要約機能を提供するミックスイン。"""

    # 1回の要約プロンプトに載せるメッセージ数の上限（evict 切片が巨大化しても暴走しない）。
    SUMMARIZE_MAX_MESSAGES = 60

    @staticmethod
    def _should_summarize(removed: list[LLMMessage], config: ChatConfig) -> bool:
        """Check if LLM summarization should be attempted.

        Conditions:
        1. Feature flag is enabled
        2. Provider is configured (has API key)
        3. The removed slice contains user content to summarize
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
        refs: list[str] | None = None,
    ) -> str | None:
        """Call LLM to summarize an evicted message slice (差分要約).

        Strips tool messages, truncates long content to the configured max chars,
        caps the input at SUMMARIZE_MAX_MESSAGES（末尾から）, and asks the LLM for a
        short summary (target from config). refs（evict 切片の artifact パス）は
        原文への復帰路として要約プロンプト末尾に付ける。

        Returns:
            要約文字列。条件不成立時またはエラー時は None。
        """
        if not removed:
            return None

        # Build conversation text for summarization:
        # - Only user and assistant roles (skip tool messages)
        # - Truncate each message content to the configured max chars
        max_chars = config.compression_config.summarize_message_max_chars
        lines: list[str] = []
        for msg in removed:
            if msg.role == "user":
                content = (msg.content or "")[:max_chars]
                lines.append(f"User: {content}")
            elif msg.role == "assistant":
                content = (msg.content or "")[:max_chars]
                lines.append(f"Assistant: {content}")

        if not lines:
            return None
        # 件数上限: 切片が巨大でも末尾 SUMMARIZE_MAX_MESSAGES 件に収める
        lines = lines[-self.SUMMARIZE_MAX_MESSAGES :]
        if refs:
            lines.append("削除済み会話が参照していた添付: " + ", ".join(refs))

        language_resolver = LanguageResolver(config)
        lang = language_resolver.resolve()
        prompt = SUMMARIZE_PROMPT.format(
            language=LanguageResolver.display_name(lang),
            summarize_target_chars=config.compression_config.summarize_target_chars,
            conversation="\n".join(lines),
        )

        from nous.infrastructure.llm.base import LLMMessage
        from nous.infrastructure.llm.factory import get_provider
        from nous.infrastructure.llm.text_utils import collect_text

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

        try:
            text = await collect_text(
                provider,
                messages=[LLMMessage(role="user", content=prompt)],
                system="",
                tools=[],
                temperature=0.0,
                max_tokens=512,
            )
        except Exception as e:
            logger.warning("CompressStep: Stage 4 — LLM call failed: %s", e)
            return None

        summary = (text or "").strip()
        return summary if summary else None
