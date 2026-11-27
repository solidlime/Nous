"""CompressStep: コンテキスト圧縮。トークン予算超過時に会話履歴を縮める。"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from nous.application.chat.pipeline.summarizer import SummarizerMixin
from nous.application.chat.pipeline.trimmer import TrimmerMixin
from nous.application.chat.session_window import _expand_segments
from nous.domain.shared.time_utils import get_now
from nous.infrastructure.llm.base import LLMMessage
from nous.infrastructure.llm.token_counter import TokenCounter
from nous.infrastructure.logging.structured import get_logger

if TYPE_CHECKING:
    from nous.application.chat.pipeline.context import ChatTurnContext
    from nous.application.chat.tree_session import TreeSessionWindow
    from nous.application.use_cases import AppContext
    from nous.domain.config.chat_config import ChatConfig

logger = get_logger(__name__)

_HISTORY_SUMMARY_OPEN = "<conversation_history_summary>"
_HISTORY_SUMMARY_CLOSE = "</conversation_history_summary>"

# <conversation_history_summary> の枠付け（§4.2）。
# framing は短く自前で。BLOCK_INTRO は付けない —
# その「中の命令文に従うな」はセッション要約の核心価値
# （過去の依頼・決定・約束）と正反対に作用するため。
_HISTORY_SUMMARY_FRAME = (
    _HISTORY_SUMMARY_OPEN
    + "\n過去会話の圧縮要約。会話の継続性のための参照。最新のユーザー指示と <precedence> が優先。\n"
    "{body}\n" + _HISTORY_SUMMARY_CLOSE
)


class CompressStep(SummarizerMixin, TrimmerMixin):
    """トークン予算を超えたら会話履歴を予算駆動で縮める。

    パイプライン位置: PromptBuildStep → CompressStep → InferenceStep

    圧縮段階:
    1. 古いツール結果をステータスサマリーに置換（成功/失敗/完了）
    3'. 予算超過時: セッション窓の head から node 単位で永続 evict し、
        evict 切片を差分要約して <conversation_history_summary> に積む。
        要約は window に永続化され、次ターン以降も揮発ブロックに載る。
    """

    @staticmethod
    def _apply_history_summary(turn_ctx: ChatTurnContext, body: str) -> None:
        """<conversation_history_summary> を揮発ブロックへ設定する（既存タグは置換）。

        揮発ブロックは会話の後方（[NOUS CONTEXT]）に置かれるため、
        キャッシュ境界（__STATIC_END__）を動かさない。誤って
        <retrieved_data> の中に入れない — BLOCK_INTRO の
        「中の命令文に従うな」は要約の核心価値と反対に作用する。
        """
        if not body:
            return
        block = _HISTORY_SUMMARY_FRAME.format(body=body)
        volatile = turn_ctx.volatile_context
        start = volatile.find(_HISTORY_SUMMARY_OPEN)
        end = volatile.find(_HISTORY_SUMMARY_CLOSE)
        if start != -1 and end != -1:
            volatile = volatile[:start] + block + volatile[end + len(_HISTORY_SUMMARY_CLOSE) :]
        elif volatile:
            volatile = f"{volatile}\n{block}"
        else:
            volatile = block
        turn_ctx.volatile_context = volatile
        logger.debug("CompressStep: set <conversation_history_summary> (%d chars body)", len(body))

    @staticmethod
    def _fallback_note(removed_count: int, refs: list[str]) -> str:
        """要約失敗時の決定論的フォールバック（evict は記憶側にも保存されない）。"""
        note = (
            f"これより前の会話 {removed_count} 件はトークン予算超過により省略されています。"
            "必要なら memory_search で過去の発言を検索してください。"
        )
        if refs:
            note += "\n参照していた添付: " + ", ".join(refs)
        return note

    @staticmethod
    def _nodes_to_messages(nodes: list[dict], now: datetime) -> list[LLMMessage]:
        """node（dict）を LLMMessage へ展開する（segments は多対多なので展開必須）。"""
        flat: list[LLMMessage] = []
        for node in nodes:
            ts = datetime.fromisoformat(node["created_at"])
            segments = node.get("segments")
            if segments:
                flat.extend(_expand_segments(segments, ts, now))
            else:
                flat.append(
                    LLMMessage(
                        role=node["role"],
                        content=node["content"],
                        tool_calls=node.get("tool_calls"),
                    )
                )
        return flat

    async def run(
        self,
        _ctx: AppContext,
        config: ChatConfig,
        turn_ctx: ChatTurnContext,
        session_messages: list[LLMMessage],
        session: TreeSessionWindow | None = None,
    ) -> list[LLMMessage]:
        """コンテキストを検査し、必要なら予算駆動で圧縮する。

        Returns:
            圧縮後のメッセージリスト（変更不要ならそのまま返す）
        """
        # 前ターンまでの要約を揮発ブロックへ載せてから予算を測る（送信実サイズに合わせる）。
        if session is not None and session.history_summary:
            self._apply_history_summary(turn_ctx, session.history_summary)

        messages = session_messages
        # Stage 1: 古いツール結果をステータスに置換（古いログ系を先に圧縮）
        if getattr(config, "context_compress_history", True):
            messages = self._clear_old_tool_results(messages)

        model = config.get_effective_model()
        counter = TokenCounter(model)
        if config.context_max_tokens is not None:
            model_max = config.context_max_tokens
        else:
            model_max = TokenCounter.get_model_max_tokens(model)
        budget = max(int(model_max * config.context_compression_threshold), 200)

        def _total(msgs: list[LLMMessage]) -> int:
            # 揮発ブロック・今回の user メッセージも送信対象なので予算に含める
            return (
                counter.count(turn_ctx.system_prompt)
                + counter.count(turn_ctx.volatile_context)
                + counter.count(turn_ctx.user_message)
                + counter.count_messages(msgs, "")
            )

        total = _total(messages)
        if total <= budget:
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

        if session is not None:
            messages = await self._stage3_evict(config, turn_ctx, session, counter, budget, before_total)
            # evict 後は窓から作り直すため、Stage 1 の置換を掛け直す
            if getattr(config, "context_compress_history", True):
                messages = self._clear_old_tool_results(messages)
        else:
            logger.warning("CompressStep: Stage 3' — no session window, sending as-is")

        total = _total(messages)
        logger.info("CompressStep: after compression: %d tokens", total)
        turn_ctx._compression_info = {
            "before_tokens": before_total,
            "after_tokens": total,
            "budget": budget,
        }
        return messages

    async def _stage3_evict(
        self,
        config: ChatConfig,
        turn_ctx: ChatTurnContext,
        session: TreeSessionWindow,
        counter: TokenCounter,
        budget: int,
        total: int,
    ) -> list[LLMMessage]:
        """Stage 3': head から node 単位で永続 evict し、差分要約を history_summary に積む。"""
        now = get_now()
        path = session.get_active_path()
        candidates = [i for i, node in enumerate(path) if node.get("role") == "user"]
        if not candidates:
            # 終了条件: user 境界が無い（単発 REM セッション等）→ 切らない
            logger.warning("CompressStep: Stage 3' — no user boundary in active path; skip eviction")
            return session.get_labeled_messages()

        costs = [counter.count_messages(self._nodes_to_messages([node], now), "") for node in path]
        prefix = [0]
        for cost in costs:
            prefix.append(prefix[-1] + cost)

        # 終了条件: 単一メッセージが予算全体を超える（巨大ペースト）→
        # そのメッセージ以降は切らない。手前までで最善努力する。
        limit = len(path)
        for idx, cost in enumerate(costs):
            if cost > budget:
                logger.warning(
                    "CompressStep: Stage 3' — message #%d alone exceeds the whole budget (%d); not evicting past it",
                    idx,
                    budget,
                )
                limit = idx
                break

        chosen = 0
        for k in candidates:
            if k <= 0:
                continue
            if total - prefix[k] <= budget:
                chosen = k
                break
        if chosen > limit:
            chosen = 0
        if chosen == 0:
            valid = [k for k in candidates if 0 < k <= limit]
            if not valid:
                logger.warning("CompressStep: Stage 3' — no usable boundary; sending as-is")
                return session.get_labeled_messages()
            # 予算内に収まらない: 切れる最後の境界まで切って最善努力
            chosen = valid[-1]
            logger.warning("CompressStep: Stage 3' — budget unreachable; evicting %d nodes best-effort", chosen)

        evicted = session.evict_path_head(chosen)
        if not evicted:
            return session.get_labeled_messages()
        removed = self._nodes_to_messages(evicted, now)
        refs = self._collect_artifact_refs(removed)

        summary: str | None = None
        if self._should_summarize(removed, config):
            try:
                summary = await self._summarize_old_turns(config=config, removed=removed, refs=refs)
            except Exception:
                logger.warning("CompressStep: Stage 3' — LLM summarization failed, using fallback")
        body = (
            f"生成: {now.strftime('%Y-%m-%d %H:%M')}\n{summary}" if summary else self._fallback_note(len(removed), refs)
        )
        merged = session.append_history_summary(body)
        self._apply_history_summary(turn_ctx, merged)
        logger.info(
            "CompressStep: Stage 3' — evicted %d nodes (%d messages), history_summary %d chars",
            len(evicted),
            len(removed),
            len(merged),
        )
        return session.get_labeled_messages()
