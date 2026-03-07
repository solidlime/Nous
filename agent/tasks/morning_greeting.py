"""
朝挨拶タスク（スケジューラーから呼ばれる）。

AgentLoop の意識ティックを朝挨拶コンテキストで強制発火する。
スケジューラーの設定（consciousness.force_ticks）で毎朝7時などに呼ぶことを想定。
"""

import logging

logger = logging.getLogger(__name__)


async def run_morning_greeting(agent_loop: object, config: dict) -> str:
    """AgentLoop の意識ティックを朝挨拶コンテキストで強制発火する。

    通常の意識ティックとまったく同じ処理を行う。
    今後、朝挨拶専用のプロンプトに切り替えたい場合はここにコンテキスト変更を追加する。

    Args:
        agent_loop: AgentLoop インスタンス。_consciousness_tick() を呼ぶ。
        config: Nous 設定 dict（現在は未使用だが将来の拡張用に保持）。

    Returns:
        "morning_greeting fired" 固定文字列。
    """
    logger.info("朝挨拶タスク発火")
    await agent_loop._consciousness_tick()
    return "morning_greeting fired"
