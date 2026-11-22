"""メッセージ切り詰め: コンテキスト長制限のためのメッセージ切り詰め処理。"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from nous.infrastructure.logging.structured import get_logger

if TYPE_CHECKING:
    from nous.infrastructure.llm.base import LLMMessage

logger = get_logger(__name__)


class TrimmerMixin:
    """メッセージ切り詰め機能を提供するミックスイン。"""

    # ツール結果に埋まった保存先（workspace artifact / shell log）を拾う正規表現。
    _ARTIFACT_REF_RE = re.compile(r'"(?:artifact_path|log_path)"\s*:\s*"([^"]+)"')

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
    def _collect_artifact_refs(removed: list[LLMMessage], limit: int = 20) -> list[str]:
        """切り捨てるメッセージに含まれる保存先パスを重複なしで集める。

        メッセージを消した後で原文に戻る唯一の手がかりなので、要約に残す。
        """
        seen: list[str] = []
        for message in removed:
            for path in TrimmerMixin._ARTIFACT_REF_RE.findall(message.content or ""):
                if path not in seen:
                    seen.append(path)
                    if len(seen) >= limit:
                        return seen
        return seen
