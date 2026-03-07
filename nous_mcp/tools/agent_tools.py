"""
Nous MCP エージェント制御ツール。
エージェント状態確認・タスク手動投入・昇華バッチ実行を提供する。
"""

import json
import logging
from typing import Dict, Optional

from nous_mcp.server import get_persona

logger = logging.getLogger(__name__)

# グローバルエージェントループ参照（main.py で設定する）
_agent_loops: Dict[str, any] = {}
_elevation_processors: Dict[str, any] = {}


def register_agent_loops(loops: Dict[str, any]) -> None:
    """main.py から AgentLoop 参照を登録する。"""
    _agent_loops.update(loops)


def register_elevation_processors(processors: Dict[str, any]) -> None:
    """main.py から ElevationBatchProcessor 参照を登録する。"""
    _elevation_processors.update(processors)


def register_agent_tools(mcp) -> None:
    """FastMCP にエージェント制御ツールを登録する。"""

    @mcp.tool()
    async def agent_status() -> str:
        """
        エージェント稼働状態・最終自律行動・次スケジュール情報を返す。
        """
        persona = get_persona()
        loop = _agent_loops.get(persona)
        if loop is None:
            return json.dumps({
                "persona": persona,
                "status": "not_running",
                "message": "AgentLoop is not initialized for this persona",
            }, ensure_ascii=False)
        try:
            status = await loop.get_status()
            return json.dumps(status, ensure_ascii=False, default=str)
        except Exception as e:
            return json.dumps({"error": str(e)}, ensure_ascii=False)

    @mcp.tool()
    async def agent_trigger(
        task_type: str,
        params: Optional[Dict] = None,
    ) -> str:
        """
        エージェントにタスクを手動投入する。

        task_type 例:
          consciousness_tick — 意識ティックを強制発火
          morning_greeting   — 朝の挨拶
          daily_diary        — 日記生成
          anniversary_check  — 記念日チェック
          discord_send       — Discord にメッセージ送信 (params: channel_id, message)
          speak              — VOICEVOX で音声発話 (params: text)
        """
        persona = get_persona()
        loop = _agent_loops.get(persona)
        if loop is None:
            return json.dumps({
                "error": f"AgentLoop not running for persona: {persona}",
            }, ensure_ascii=False)
        try:
            result = await loop.trigger_task(task_type, params or {})
            return json.dumps({"success": True, "result": result}, ensure_ascii=False, default=str)
        except Exception as e:
            logger.error(f"agent_trigger error: {e}", exc_info=True)
            return json.dumps({"error": str(e)}, ensure_ascii=False)

    @mcp.tool()
    async def elevation_trigger(
        batch_size: int = 5,
        dry_run: bool = False,
    ) -> str:
        """
        記憶昇華バッチを手動実行する。

        Args:
            batch_size: 一度に処理する記憶数 (デフォルト: 5)
            dry_run: True の場合は実際には保存せず確認のみ
        """
        persona = get_persona()
        processor = _elevation_processors.get(persona)
        if processor is None:
            return json.dumps({
                "error": f"ElevationBatchProcessor not initialized for persona: {persona}",
            }, ensure_ascii=False)
        try:
            result = await processor.run_batch(
                persona=persona,
                batch_size=batch_size,
                dry_run=dry_run,
            )
            return json.dumps(result, ensure_ascii=False, default=str)
        except Exception as e:
            logger.error(f"elevation_trigger error: {e}", exc_info=True)
            return json.dumps({"error": str(e)}, ensure_ascii=False)
