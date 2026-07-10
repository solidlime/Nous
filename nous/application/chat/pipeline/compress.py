"""CompressStep: コンテキスト圧縮。トークン予算超過時にシステムプロンプト・会話履歴を縮める。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from nous.infrastructure.llm.token_counter import TokenCounter
from nous.infrastructure.logging.structured import get_logger

if TYPE_CHECKING:
    from nous.application.chat.pipeline.context import ChatTurnContext
    from nous.application.use_cases import AppContext
    from nous.domain.chat_config import ChatConfig
    from nous.infrastructure.llm.base import LLMMessage

logger = get_logger(__name__)

SUMMARIZE_PROMPT = """以下の会話履歴を要約してください。重要な情報（ユーザーの発言、決定事項、好み、約束）のみを抽出し、300文字以内の日本語でまとめてください。

会話履歴:
{conversation}

要約:"""


class CompressStep:
    """トークン予算を超えたらシステムプロンプト・会話履歴を動的圧縮する。

    パイプライン位置: PromptBuildStep → CompressStep → InferenceStep

    圧縮段階（軽い順）:
    1. システムプロンプトの関連記憶セクションをトリム
    2. 古いツール結果を [cleared] に置換
    3. 古い会話メッセージを切り詰め
    4. LLMによる古い会話ターンの要約圧縮（6ターン以上・予算超過時）
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

        if config.context_max_tokens is not None:
            model_max = config.context_max_tokens
        else:
            model_max = TokenCounter.get_model_max_tokens(model)
        budget = int(model_max * config.context_compression_threshold - (config.max_tokens or 4096))
        # Ensure budget never goes below 10% of model_max
        budget = max(budget, int(model_max * 0.1))

        if total <= budget:
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
            turn_ctx.system_prompt = self._trim_system_prompt(turn_ctx.system_prompt, config.context_compression_mode)
            logger.debug(
                "CompressStep: system prompt trimmed %d → %d chars",
                old_len,
                len(turn_ctx.system_prompt),
            )

        # Re-check
        total = counter.count(turn_ctx.system_prompt) + counter.count_messages(session_messages, "")
        if total <= budget:
            return session_messages

        # Stage 2: Clear old tool results
        if getattr(config, "context_compress_history", True):
            messages = self._clear_old_tool_results(session_messages)
        else:
            messages = session_messages

        # Re-check
        total = counter.count(turn_ctx.system_prompt) + counter.count_messages(messages, "")
        if total <= budget:
            return list(messages)

        keep_recent = getattr(config, "context_keep_recent_turns", 2)

        # Stage 3: Truncate old messages
        if getattr(config, "context_compress_history", True):
            messages = self._truncate_old_messages(list(messages), keep_recent)

        total = counter.count(turn_ctx.system_prompt) + counter.count_messages(messages, "")

        # Stage 4: LLM-based summary of old conversation turns
        # Only runs when mechanical compression still leaves us over budget
        # and there's enough history worth summarizing (≥6 turns)
        if total > budget and self._should_summarize(messages, config):
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
                        "CompressStep: Stage 4 — LLM summarized %d old messages into %d chars",
                        old_count,
                        len(summary),
                    )
            except Exception:
                logger.warning(
                    "CompressStep: Stage 4 — LLM summarization failed, keeping truncated messages",
                )

        logger.info("CompressStep: after compression: %d tokens", total)
        # Store compression info for SSE notification
        turn_ctx._compression_info = {
            "before_tokens": before_total,
            "after_tokens": total,
            "budget": budget,
        }
        return list(messages)

    @staticmethod
    def _should_summarize(messages: list[LLMMessage], config: ChatConfig) -> bool:
        """Check if LLM summarization should be attempted.

        Conditions:
        1. Feature flag is enabled
        2. Provider is configured (has API key)
        3. At least 6 user messages (6 conversation turns) exist
        """
        if not getattr(config, "context_use_llm_summary", True):
            return False
        if not config.is_configured():
            return False
        # Count turns by counting user messages
        user_count = sum(1 for m in messages if m.role == "user")
        return user_count >= 6

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
        api_key = config.get_effective_api_key()
        model = config.get_effective_model()
        if not api_key or not model:
            return None

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

        prompt = SUMMARIZE_PROMPT.format(conversation="\n".join(lines))

        from nous.infrastructure.llm.base import DoneEvent, ErrorEvent, LLMMessage, TextDeltaEvent
        from nous.infrastructure.llm.factory import get_provider

        try:
            provider = get_provider(config.provider, api_key, model, config.get_effective_base_url())
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

    @staticmethod
    def _trim_system_prompt(prompt: str, mode: str) -> str:
        """Trim system prompt sections by reducing memory list size.

        Sections are separated by '\\n--- ' markers.
        The 「関連記憶」 section is the primary target for trimming.
        """
        sections = prompt.split("\n--- ")
        if len(sections) <= 1:
            return prompt

        # Limits per mode (how many memory lines to keep)
        mode_limits = {
            "light": 8,  # Keep most
            "normal": 4,  # Moderate
            "aggressive": 2,  # Minimal
            "auto": 4,  # Default: normal
        }
        limit = mode_limits.get(mode, mode_limits["auto"])

        result: list[str] = [sections[0]]  # Base prompt + time (section 0)
        trimmed = False

        for sec in sections[1:]:
            if "関連記憶" in sec[:10]:
                lines = sec.split("\n")
                header = lines[0]
                memory_lines = [line for line in lines[1:] if line.strip().startswith("- ")]
                if len(memory_lines) > limit:
                    # Keep only the top-N memory lines
                    kept = memory_lines[:limit]
                    removed = len(memory_lines) - limit
                    kept.append(f"  （他 {removed} 件の関連記憶 — 必要なら memory_search で検索）")
                    result.append(f"--- {header}\n" + "\n".join(kept))
                    trimmed = True
                    continue
            elif "利用可能なSkill" in sec[:20]:
                # Truncate long skill descriptions to ~500 chars
                if len(sec) > 600:
                    result.append(f"--- {sec[:500]}...")
                    trimmed = True
                    continue
            result.append(f"--- {sec}")

        if trimmed:
            logger.debug("CompressStep: trimmed system prompt sections (mode=%s, limit=%d)", mode, limit)

        return "\n".join(result)

    @staticmethod
    def _clear_old_tool_results(messages: list[LLMMessage]) -> list[LLMMessage]:
        """Replace tool result contents older than 3 assistant turns with a compact marker.

        We keep the most recent 3 assistant turns' tool results intact.
        Tool results before that are replaced with '[cleared]'.
        """
        from nous.infrastructure.llm.base import LLMMessage

        # Find indices of assistant messages
        assistant_indices = [i for i, m in enumerate(messages) if m.role == "assistant"]

        if len(assistant_indices) <= 3:
            return messages  # Not enough history

        # Tool results before the 4th-to-last assistant message are fair game
        cutoff = assistant_indices[-4]  # Messages before this are old

        cleared_count = 0
        result: list[LLMMessage] = []
        for i, msg in enumerate(messages):
            if msg.role == "tool" and i < cutoff:
                result.append(
                    LLMMessage(
                        role="tool",
                        content="[previous tool output cleared]",
                        tool_call_id=msg.tool_call_id,
                    )
                )
                cleared_count += 1
            else:
                result.append(msg)

        if cleared_count:
            logger.debug("CompressStep: cleared %d old tool results", cleared_count)

        return result

    @staticmethod
    def _truncate_old_messages(messages: list[LLMMessage], keep_recent_turns: int) -> list[LLMMessage]:
        """Truncate older user/assistant messages to 300 chars.

        Keeps the most recent N turns intact; truncates everything before that.
        Tool messages are left as-is (handled by _clear_old_tool_results).
        """
        from nous.infrastructure.llm.base import LLMMessage

        keep_count = keep_recent_turns * 2  # user + assistant = one turn
        if len(messages) <= keep_count:
            return messages

        result: list[LLMMessage] = []
        truncated_count = 0

        for i, msg in enumerate(messages):
            if i < len(messages) - keep_count and msg.role in ("user", "assistant"):
                content = msg.content or ""
                if len(content) > 300:
                    result.append(
                        LLMMessage(
                            role=msg.role,
                            content=f"[旧]{content[:300]}...",
                            timestamp=msg.timestamp,
                            time_label=msg.time_label or "(旧)",
                            tool_call_id=msg.tool_call_id,
                            tool_calls=msg.tool_calls,
                            content_parts=msg.content_parts,
                        )
                    )
                    truncated_count += 1
                else:
                    result.append(msg)
            else:
                result.append(msg)

        if truncated_count:
            logger.debug(
                "CompressStep: truncated %d old messages (kept %d recent turns)",
                truncated_count,
                keep_recent_turns,
            )

        return result
