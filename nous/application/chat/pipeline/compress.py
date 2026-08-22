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

    圧縮段階:
    0. 常時メッセージ切り詰め (context_keep_recent_turns) ← 予算・force_compressとは独立して常時実行
    1. 古いツール結果をステータスサマリーに置換（成功/失敗/完了）
    2. システムプロンプトの関連記憶セクションをトリム
    3. LLMによる古い会話ターンの要約圧縮（予算超過時）— フルテキストで要約
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
        # ──────────────────────────────────────────────────────────────
        # Stage 0: 常時メッセージ切り詰め (context_keep_recent_turns)
        # budget/force_compressとは独立して常時実行。
        # 途中で有効にしても即座に古いメッセージをぶったぎる。
        # keep_recent == 0 の場合はスキップ（全履歴保持）。
        # ──────────────────────────────────────────────────────────────
        keep_recent = getattr(config, "context_keep_recent_turns", 2)
        if keep_recent > 0 and getattr(config, "context_compress_history", True):
            messages = self._truncate_old_messages(session_messages, keep_recent)
        else:
            messages = session_messages

        # ──────────────────────────────────────────────────────────────
        # Token budget calculation
        # ──────────────────────────────────────────────────────────────
        model = config.get_effective_model()
        counter = TokenCounter(model)
        total = counter.count(turn_ctx.system_prompt) + counter.count_messages(messages, "")

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
            return messages

        logger.info(
            "CompressStep: %d/%d tokens (%.0f%%) — OVER budget, compressing...",
            total,
            budget,
            total * 100 / budget if budget else 0,
        )
        before_total = total

        # Stage 1: Clear old tool results（古いログ系を先に圧縮）
        if getattr(config, "context_compress_history", True):
            messages = self._clear_old_tool_results(messages)

        # Re-check
        total = counter.count(turn_ctx.system_prompt) + counter.count_messages(messages, "")
        if not force_compress and total <= budget:
            return list(messages)

        # Stage 2: System prompt trimming（関連記憶/digest はツール結果より優先で残す）
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
        total = counter.count(turn_ctx.system_prompt) + counter.count_messages(messages, "")
        if not force_compress and total <= budget:
            return messages

        # Stage 3: LLM-based summary of old conversation turns
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
                    from nous.infrastructure.llm.base import LLMMessage

                    summary_msg = LLMMessage(
                        role="user",
                        content=f"[過去の会話要約]\n{summary}",
                    )
                    # スライス先頭が tool なら assistant(tool_calls) を含むよう広げる（孤児 tool 防止）
                    start = TrimmerMixin._adjust_slice_start(messages, -keep_count)
                    kept = messages[start:]
                    old_count = len(messages) - len(kept)
                    messages = [summary_msg] + kept
                    total = counter.count(turn_ctx.system_prompt) + counter.count_messages(messages, "")
                    logger.info(
                        "CompressStep: Stage 3 — LLM summarized %d old messages into %d chars",
                        old_count,
                        len(summary),
                    )
            except Exception:
                logger.warning(
                    "CompressStep: Stage 3 — LLM summarization failed, proceeding",
                )

        # Final budget check for logging/SSE notification
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
        turn_ctx._compression_info = {
            "before_tokens": before_total,
            "after_tokens": total,
            "budget": budget,
        }
        return list(messages)
