"""
Nous エージェント制御 REST API ルーター。
"""

import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from nous_mcp.server import get_persona
from nous_mcp.tools.agent_tools import _agent_loops, _elevation_processors

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/agent", tags=["agent"])

# 自律行動ログ（メモリ内、再起動でリセット）
_action_log: list = []


class TriggerRequest(BaseModel):
    task_type: str
    params: Dict[str, Any] = {}


class DiscordSendRequest(BaseModel):
    channel_id: int
    content: str


class ElevationRequest(BaseModel):
    batch_size: int = 5
    dry_run: bool = False
    min_importance: float = 0.3


@router.get("/status")
async def agent_status(request: Request):
    """エージェント稼働状態を返す。"""
    persona = get_persona(request)
    loop = _agent_loops.get(persona)
    if loop is None:
        return {"persona": persona, "status": "not_running"}
    try:
        return await loop.get_status()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/start")
async def agent_start(request: Request):
    """エージェントループを起動する。"""
    persona = get_persona(request)
    try:
        import main as main_module
        result = await main_module.start_agent_loop(persona)
        if not result.get("success"):
            raise HTTPException(status_code=400, detail=result.get("error", "起動失敗"))
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/stop")
async def agent_stop(request: Request):
    """エージェントループを停止する。"""
    persona = get_persona(request)
    try:
        import main as main_module
        result = await main_module.stop_agent_loop(persona)
        if not result.get("success"):
            raise HTTPException(status_code=400, detail=result.get("error", "停止失敗"))
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/trigger")
async def trigger_task(request: Request, body: TriggerRequest):
    """エージェントにタスクを手動投入する。"""
    persona = get_persona(request)
    loop = _agent_loops.get(persona)
    if loop is None:
        raise HTTPException(status_code=503, detail=f"AgentLoop not running for: {persona}")
    try:
        result = await loop.trigger_task(body.task_type, body.params)
        return {"success": True, "result": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/history")
async def get_action_history(request: Request, limit: int = 20):
    """自律行動ログを返す。"""
    return {"history": _action_log[-limit:], "total": len(_action_log)}


@router.post("/discord/send")
async def discord_send(request: Request, body: DiscordSendRequest):
    """Discord チャンネルにメッセージを手動送信する。"""
    persona = get_persona(request)
    loop = _agent_loops.get(persona)
    if loop is None:
        raise HTTPException(status_code=503, detail=f"AgentLoop not running for: {persona}")
    try:
        result = await loop.trigger_task("discord_send", {
            "channel_id": body.channel_id,
            "message": body.content,
        })
        return {"success": True, "result": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/elevation/run")
async def run_elevation(request: Request, body: ElevationRequest):
    """記憶昇華バッチを手動実行する。"""
    persona = get_persona(request)
    processor = _elevation_processors.get(persona)
    if processor is None:
        raise HTTPException(status_code=503, detail=f"ElevationBatchProcessor not initialized for: {persona}")
    try:
        result = await processor.run_batch(
            persona=persona,
            batch_size=body.batch_size,
            min_importance=body.min_importance,
            dry_run=body.dry_run,
        )
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/elevation/status")
async def elevation_status(request: Request):
    """昇華バッチの統計情報を返す。"""
    persona = get_persona(request)
    from nous_mcp.server import get_db_path
    from memory.db import MemoryDB
    db = MemoryDB(get_db_path(persona))
    stats = db.get_stats()
    return {
        "persona": persona,
        "total_memories": stats.get("total_count", 0),
        "elevated_count": stats.get("elevated_count", 0),
        "pending_elevation": stats.get("total_count", 0) - stats.get("elevated_count", 0),
    }
