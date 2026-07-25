"""CompressStep: コンテキスト圧縮。トークン予算超過時にシステムプロンプト・会話履歴を縮める。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from nous.application.chat.pipeline.summarizer import (
    SUMMARIZE_PROMPT,  # noqa: F401
    SummarizerMixin,
)
from nous.application.chat.pipeline.trimmer import TrimmerMixin
from nous.infrastructure.llm.token_counter import TokenCounter
from nous.infrastructure.logging.structured import get_logger

if TYPE_CHECKING:
    from nous.application.chat.pipeline.context import ChatTurnContext
    from nous.application.use_cases import AppContext
    from nous.domain.chat_config import ChatConfig
    from nous.infrastructure.llm.base import LLMMessage

logger = get_logger(__name__)


class CompressStep(SummarizerMixin, TrimmerMixin):
    """トークン予算を超えたらシステムプロンプト・会話履歴を動的圧縮する。

    パイプライン位置: PromptBuildStep → CompressStep → InferenceStep

    圧縮段階（軽い順）:
    1. システムプロンプトの関連記憶セクションをトリム
    2. 古いツール結果をステータスサマリーに置換（成功/失敗/完了）
    3. LLMによる古い会話ターンの要約圧縮（予算超過時）— フルテキストで要約
    4. 古い会話メッセージを切り詰め（予算超過が続く場合のみ）
    """

    async def run(
        self,
        _ctx: AppContext,
        config: ChatConfig,
        turn_ctx: ChatTurnContext,
        session_messages: list[LLMMessage],
    ) -> list[LLMMessage]:
        """コンテキストを検査し、必要なら圧縮する。

        Returns:
            圧縮後のメッセージリスト（変更不要ならそのまま返す）
        """
        model = config.get_effective_model()
        counter = TokenCounter(model)
        total = counter.count(turn_ctx.system_prompt) + counter.count_messages(session_messages, "")

        # max_stored_messages 超過時は強制圧縮
        force_compress = len(session_messages) >= config.max_stored_messages

        if config.context_max_tokens is not None:
            model_max = config.context_max_tokens
        else:
            model_max = TokenCounter.get_model_max_tokens(model)
        budget = int(model_max * config.context_compression_threshold)
        # Ensure budget never goes below 200
        budget = max(budget, 200)

        if not force_compress and total <= budget:
            logger.debug(
                "CompressStep: %d/%d tokens (%.0f%%) — within budget, skip",
                total,
                budget,
                total * 100 / budget if budget else 0,
            )
            return session_messages

        logger.info(
            "CompressStep: %d/%d tokens (%.0f%%) — OVER budget, compressing...",
            total,
            budget,
            total * 100 / budget if budget else 0,
        )
        before_total = total

        # Stage 1: System prompt trimming
        if getattr(config, "context_compress_system_prompt", True):
            old_len = len(turn_ctx.system_prompt)
            turn_ctx.system_prompt = self._trim_system_prompt(
                turn_ctx.system_prompt,
                config.context_compression_mode,
                total,
                budget,
            )
            logger.debug(
                "CompressStep: system prompt trimmed %d → %d chars",
                old_len,
                len(turn_ctx.system_prompt),
            )

        # Re-check
        total = counter.count(turn_ctx.system_prompt) + counter.count_messages(session_messages, "")
        if not force_compress and total <= budget:
            return session_messages

        # Stage 2: Clear old tool results
        if getattr(config, "context_compress_history", True):
            messages = self._clear_old_tool_results(session_messages)
        else:
            messages = session_messages

        # Re-check
        total = counter.count(turn_ctx.system_prompt) + counter.count_messages(messages, "")
        if not force_compress and total <= budget:
            return list(messages)

        keep_recent = getattr(config, "context_keep_recent_turns", 2)

        # Stage 3: LLM-based summary of old conversation turns (runs BEFORE truncation)
        # Only runs when we're over budget and there's enough history worth summarizing
        if (
            (force_compress or total > budget)
            and getattr(config, "context_compress_history", True)
            and self._should_summarize(messages, config)
        ):
            try:
                summary = await self._summarize_old_turns(
                    config=config,
                    messages=messages,
                    keep_recent=keep_recent,
                )
                if summary:
                    keep_count = keep_recent * 2
                    old_count = len(messages) - keep_count
                    from nous.infrastructure.llm.base import LLMMessage

                    summary_msg = LLMMessage(
                        role="user",
                        content=f"[過去の会話要約]\n{summary}",
                    )
                    messages = [summary_msg] + messages[-keep_count:]
                    total = counter.count(turn_ctx.system_prompt) + counter.count_messages(messages, "")
                    logger.info(
                        "CompressStep: Stage 3 — LLM summarized %d old messages into %d chars",
                        old_count,
                        len(summary),
                    )
            except Exception:
                logger.warning(
                    "CompressStep: Stage 3 — LLM summarization failed, proceeding to truncation",
                )

        # Stage 4: Always truncate when keep_recent > 0 (independent of token budget)
        # When keep_recent == 0, skip truncation — fall back to token-budget-only behavior
        if keep_recent > 0 and getattr(config, "context_compress_history", True):
            messages = self._truncate_old_messages(list(messages), keep_recent)

        # Re-check budget for logging/SSE notification
        total = counter.count(turn_ctx.system_prompt) + counter.count_messages(messages, "")
        if total <= budget:
            logger.info("CompressStep: after compression: %d tokens", total)
            turn_ctx._compression_info = {
                "before_tokens": before_total,
                "after_tokens": total,
                "budget": budget,
            }
            return list(messages)

        logger.info("CompressStep: after compression: %d tokens", total)
        # Store compression info for SSE notification
        turn_ctx._compression_info = {
            "before_tokens": before_total,
            "after_tokens": total,
            "budget": budget,
        }
        return list(messages)
