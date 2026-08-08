"""メッセージ切り詰め: コンテキスト長制限のためのメッセージ切り詰め処理。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from nous.infrastructure.logging.structured import get_logger

if TYPE_CHECKING:
    from nous.infrastructure.llm.base import LLMMessage

logger = get_logger(__name__)


class TrimmerMixin:
    """メッセージ切り詰め機能を提供するミックスイン。"""

    @staticmethod
    def _adjust_slice_start(messages: list[LLMMessage], start: int) -> int:
        """スライス開始位置が tool メッセージを指す場合、1件前に広げて
        対応する assistant(tool_calls) を含める（孤児 tool 防止）。

        start は負のインデックス。リスト先頭（-len）を越えて広げない。
        """
        while start < 0 and start > -len(messages) and messages[start].role == "tool":
            start -= 1
        return start

    @staticmethod
    def _trim_system_prompt(prompt: str, mode: str, total_tokens: int = 0, budget_tokens: int = 0) -> str:
        """Trim system prompt sections by reducing memory list size.

        Sections are separated by '\\n--- ' markers.
        The 「関連記憶」 section is the primary target for trimming.
        """
        sections = prompt.split("\n--- ")
        if len(sections) <= 1:
            return prompt

        # Limits per mode (how many memory lines to keep)
        mode_limits = {
            "light": 8,
            "normal": 4,
            "aggressive": 2,
        }
        limit = mode_limits.get(mode, 4)  # default = normal

        # Auto mode: dynamic based on budget excess ratio
        if mode == "auto" and total_tokens > 0 and budget_tokens > 0:
            ratio = total_tokens / budget_tokens
            if ratio < 1.2:
                limit = 8
            elif ratio < 1.5:
                limit = 4
            else:
                limit = 2

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
            # NOTE: 利用可能なSkill セクションはスキル発見層であり絶対保護対象。
            # スキル情報の切り捨てはツール発見を阻害し、自律的 invoke_skill を不可能にする。
            # 業界標準（Anthropic/OpenAI/LangChain）に従い、コア指示と同様に保護する。
            result.append(f"--- {sec}")

        if trimmed:
            logger.debug("CompressStep: trimmed system prompt sections (mode=%s, limit=%d)", mode, limit)

        return "\n".join(result)

    @staticmethod
    def _clear_old_tool_results(messages: list[LLMMessage]) -> list[LLMMessage]:
        """Replace tool result contents older than 3 assistant turns with status summary.

        We keep the most recent 3 assistant turns' tool results intact.
        Tool results before that are replaced with a Japanese status summary
        extracted from the JSON result (success/failure/complete).
        """
        import json

        from nous.infrastructure.llm.base import LLMMessage

        # Find indices of assistant messages
        assistant_indices = [i for i, m in enumerate(messages) if m.role == "assistant"]

        if len(assistant_indices) <= 3:
            return messages  # Not enough history

        # Tool results before the 4th-to-last assistant message are fair game
        cutoff = assistant_indices[-4]  # Messages before this are old

        def _extract_status(content: str) -> str:
            """Extract success/failure status from tool result JSON."""
            try:
                data = json.loads(content)
                if isinstance(data, dict):
                    success = data.get("success") or data.get("status") in ("success", "ok", True)
                    return "[ツール実行: 成功]" if success else "[ツール実行: 失敗]"
            except (json.JSONDecodeError, TypeError, ValueError):
                pass
            return "[ツール実行: 完了]"

        replaced_count = 0
        result: list[LLMMessage] = []
        for i, msg in enumerate(messages):
            if msg.role == "tool" and i < cutoff:
                status = _extract_status(msg.content or "")
                result.append(
                    LLMMessage(
                        role="tool",
                        content=status,
                        tool_call_id=msg.tool_call_id,
                    )
                )
                replaced_count += 1
            else:
                result.append(msg)

        if replaced_count:
            logger.debug("CompressStep: replaced %d old tool results with status summaries", replaced_count)

        return result

    @staticmethod
    def _truncate_old_messages(messages: list[LLMMessage], keep_recent_turns: int) -> list[LLMMessage]:
        """Cut off old messages beyond keep_recent_turns, keeping only recent ones intact.

        Old messages (user/assistant/tool) before the last N turns are removed entirely
        and replaced with a single system notice. This is a hard cutoff — messages
        beyond the window are NOT visible to the LLM.

        When keep_recent_turns == 0, no truncation is performed.
        """
        from nous.infrastructure.llm.base import LLMMessage

        keep_count = keep_recent_turns * 2  # user + assistant = one turn
        if keep_recent_turns == 0 or len(messages) <= keep_count:
            return messages

        # スライス開始位置が tool メッセージを指す場合、1件前に広げて
        # 対応する assistant(tool_calls) を含める（孤児 tool 防止）
        start = TrimmerMixin._adjust_slice_start(messages, -keep_count)

        # Keep only the last keep_count messages intact
        recent = messages[start:]
        removed_count = len(messages) - len(recent)

        # Build a brief summary of cut user messages for context
        old_messages = messages[:start]
        user_msgs = [m for m in old_messages if m.role == "user" and m.content]
        summary_parts: list[str] = []
        if user_msgs:
            # Pick first few and last few user messages as highlights
            sample = []
            n_sample = min(6, len(user_msgs))
            if n_sample <= 6:
                sample = user_msgs
            else:
                half = n_sample // 2
                sample = user_msgs[:half] + user_msgs[-half:]
            for m in sample:
                snippet = (m.content or "")[:80].replace("\n", " ")
                summary_parts.append(f"  - {snippet}")

        summary_text = ""
        if summary_parts:
            summary_text = "\n切り詰めた会話のハイライト:\n" + "\n".join(summary_parts)

        # Insert a system notice in place of removed messages
        note = LLMMessage(
            role="assistant",
            content=(
                f"[システム: 過去{removed_count}件のメッセージを切り詰めました。"
                f"{summary_text}\n"
                f"直近{keep_recent_turns}ターンのみ保持しています。]"
            ),
        )

        logger.debug(
            "CompressStep: removed %d old messages (kept %d recent turns)",
            removed_count,
            keep_recent_turns,
        )

        return [note] + recent
