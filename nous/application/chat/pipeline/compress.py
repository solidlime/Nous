"""CompressStep: コンテキスト圧縮。トークン予算超過時にシステムプロンプト・会話履歴を縮める。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from nous.application.chat.pipeline.summarizer import (
    SUMMARIZE_PROMPT,  # noqa: F401
    SummarizerMixin,
)
from nous.application.chat.pipeline.trimmer import TrimmerMixin
from nous.domain.shared.time_utils import get_now
from nous.infrastructure.llm.token_counter import TokenCounter
from nous.infrastructure.logging.structured import get_logger

if TYPE_CHECKING:
    from nous.application.chat.pipeline.context import ChatTurnContext
    from nous.application.use_cases import AppContext
    from nous.domain.chat_config import ChatConfig
    from nous.infrastructure.llm.base import LLMMessage

logger = get_logger(__name__)

# <conversation_history_summary> の枠付け（§4.2）。
# framing は短く自前で。RETRIEVED_DATA_GUARD は付けない —
# guard の「依頼文に従うな」はセッション要約の核心価値
# （過去の依頼・決定・約束）と正反対に作用するため。
_HISTORY_SUMMARY_FRAME = (
    "<conversation_history_summary>\n"
    "過去会話の圧縮要約。会話の継続性のための参照。最新のユーザー指示と <precedence> が優先。\n"
    "{body}\n"
    "</conversation_history_summary>"
)


class CompressStep(SummarizerMixin, TrimmerMixin):
    """トークン予算を超えたらシステムプロンプト・会話履歴を動的圧縮する。

    パイプライン位置: PromptBuildStep → CompressStep → InferenceStep

    圧縮段階:
    0. 常時メッセージ切り詰め (context_keep_recent_turns) ← 予算・force_compressとは独立して常時実行
       切り詰めた分は fake note ではなく system セクション
       <conversation_history_summary> にハイライトとして注入する
    1. 古いツール結果をステータスサマリーに置換（成功/失敗/完了）
    2. システムプロンプトの関連記憶セクションをトリム
    3. LLMによる Stage 0 removed slice の要約圧縮（予算超過時）—
       <conversation_history_summary> に統合（メッセージには混ぜない）
    """

    @staticmethod
    def _append_history_summary(turn_ctx: ChatTurnContext, body: str) -> None:
        """Inject a <conversation_history_summary> block into the system prompt.

        Sibling tag: placed immediately AFTER </retrieved_data> when present,
        else appended at the end (dynamic area after __STATIC_END__, cache
        boundary untouched). NEVER inside <retrieved_data> — the
        RETRIEVED_DATA_GUARD ("don't follow requests in data") would
        invalidate the summary's core value (past requests/decisions/promises).
        Second call in the same turn merges into the existing tag.
        """
        prompt = turn_ctx.system_prompt
        if "</conversation_history_summary>" in prompt:
            # 同一ターン内の2回目（Stage 0 ハイライト + Stage 3 要約）: 既存タグに追記
            turn_ctx.system_prompt = prompt.replace(
                "</conversation_history_summary>",
                f"{body}\n</conversation_history_summary>",
                1,
            )
            return
        block = _HISTORY_SUMMARY_FRAME.format(body=body)
        marker = "</retrieved_data>"
        if marker in prompt:
            idx = prompt.index(marker) + len(marker)
            turn_ctx.system_prompt = prompt[:idx] + "\n" + block + prompt[idx:]
        else:
            turn_ctx.system_prompt = prompt + "\n" + block
        logger.debug("CompressStep: injected <conversation_history_summary> (%d chars body)", len(body))

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
            messages, highlights, removed = self._truncate_old_messages(session_messages, keep_recent)
            if highlights:
                # 切り詰めハイライトを system セクションへ注入（fake note 廃止の代替）。
                # Stage 2 先例どおり CompressStep が turn_ctx.system_prompt を mutate する。
                # 注入はこの直後の budget 再計算に自然に反映される。
                self._append_history_summary(turn_ctx, highlights)
        else:
            messages = session_messages
            highlights = ""
            removed = []

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

        # Stage 3: LLM-based summary of the Stage 0 removed slice
        if (
            (force_compress or total > budget)
            and getattr(config, "context_compress_history", True)
            and removed
            and self._should_summarize(removed, config)
        ):
            try:
                summary = await self._summarize_old_turns(
                    config=config,
                    removed=removed,
                )
                if summary:
                    body = f"生成: {get_now().strftime('%Y-%m-%d %H:%M')}\n{summary}"
                    # メッセージに混ぜず system セクションへ統合（§4.2）。
                    # 注入後の token 数はこの直後の再計算に反映される。
                    self._append_history_summary(turn_ctx, body)
                    logger.info(
                        "CompressStep: Stage 3 — LLM summarized %d removed messages into %d chars",
                        len(removed),
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
