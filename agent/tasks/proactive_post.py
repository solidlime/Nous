"""
ドライブ高まり時の自発投稿タスク。

ドライブが閾値を超えたときに AgentLoop の _drive_overflow_tick() を呼ぶ。
スケジューラーや外部 API から直接呼ぶことも可能。
"""

import logging
from typing import List

logger = logging.getLogger(__name__)


async def run_proactive_post(
    agent_loop: object,
    drive_state: object,
    triggered_drives: List[str],
) -> str:
    """ドライブ閾値越え時に自発投稿を行う。

    AgentLoop の _drive_overflow_tick() に処理を委譲する。

    Args:
        agent_loop: AgentLoop インスタンス（_drive_overflow_tick() を呼ぶ）。
        drive_state: DriveState インスタンス（現在は未使用・将来の拡張用）。
        triggered_drives: 閾値を超えたドライブ名のリスト。

    Returns:
        "proactive_post fired for drives: {triggered_drives}" 形式の文字列。
    """
    logger.info(f"自発投稿タスク発火: drives={triggered_drives}")
    await agent_loop._drive_overflow_tick(triggered_drives)
    return f"proactive_post fired for drives: {triggered_drives}"
