"""
記念日チェックタスク（毎朝8時などに実行）。

memory_db で tags=["anniversary"] の記憶を検索し、
今日の日付と一致する記念日があれば意識ティックを強制発火する。
"""

import logging
from datetime import datetime
from typing import Any

logger = logging.getLogger(__name__)


async def run_anniversary_check(
    agent_loop: object,
    memory_db: Any,
    llm_router: Any,
    persona: str,
) -> str:
    """今日の記念日・特別な日をチェックして意識ティックを発火する。

    記念日記憶の content に "MM-DD" 形式の日付が含まれるものを照合する。
    一致した記念日が存在すれば _consciousness_tick() を強制発火する。

    Args:
        agent_loop: AgentLoop インスタンス（意識ティック発火に使用）。
        memory_db: MemoryDB インスタンス（記念日記憶の検索に使用）。
        llm_router: LLMRouter インスタンス（現在は未使用・将来の拡張用）。
        persona: ペルソナ名（ログ出力に使用）。

    Returns:
        実行結果を表す文字列。記念日が見つかった場合はその件数を含む。
    """
    try:
        today_str = datetime.now().strftime("%m-%d")  # 例: "03-02"

        # tags=["anniversary"] の記憶を取得
        anniversary_memories = memory_db.get_by_tags(["anniversary"])

        if not anniversary_memories:
            logger.info(f"[{persona}] 記念日チェック: 記念日記憶なし")
            return "anniversary_check: no anniversary memories"

        # 今日の月日と一致する記念日を探す
        matched = [
            m for m in anniversary_memories
            if today_str in m.content
        ]

        if not matched:
            logger.info(f"[{persona}] 記念日チェック: 今日({today_str})の記念日なし")
            return f"anniversary_check: no match for {today_str}"

        logger.info(
            f"[{persona}] 記念日発見: {len(matched)}件 — {[m.key for m in matched]}"
        )

        # 記念日があれば意識ティックを発火（記念日記憶をログに残す）
        for mem in matched:
            logger.info(f"[{persona}] 記念日: {mem.content[:80]}")

        await agent_loop._consciousness_tick()
        return f"anniversary_check fired: {len(matched)} anniversaries on {today_str}"

    except Exception as e:
        logger.error(f"[{persona}] 記念日チェックエラー: {e}", exc_info=True)
        return f"anniversary_check error: {e}"
