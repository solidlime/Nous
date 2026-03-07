"""
Nous アバター制御 REST API + WebSocket ルーター。
Live2D / VRM Web / VTube Studio の表情制御と音声発話を提供する。
"""

import asyncio
import glob
import json
import logging
import os
from typing import Any, Dict, Optional, Set

from fastapi import APIRouter, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from pydantic import BaseModel

from nous_mcp.server import get_persona
from config import get_data_dir

logger = logging.getLogger(__name__)
router = APIRouter(tags=["avatar"])

# Live2D / 汎用 WebSocket 接続マネージャー（全ペルソナ共通）
_connected_clients: Set[WebSocket] = set()
_lock = asyncio.Lock()

# VRM per-persona WebSocket マネージャー {persona: set[WebSocket]}
_vrm_clients: Dict[str, Set[WebSocket]] = {}
_vrm_lock = asyncio.Lock()


class ExpressionRequest(BaseModel):
    emotion: str
    intensity: float = 1.0


class SpeakRequest(BaseModel):
    text: str


# ── VRM ファイル検索ヘルパー ───────────────────────────────────────────────────


def _find_vrm_file(persona: str) -> Optional[str]:
    """data/{persona}/ ディレクトリから最初の .vrm ファイルを返す。"""
    data_dir = get_data_dir()
    persona_dir = os.path.join(data_dir, persona)
    if not os.path.isdir(persona_dir):
        return None
    vrm_files = glob.glob(os.path.join(persona_dir, "*.vrm"))
    return vrm_files[0] if vrm_files else None


def _find_live2d_file(persona: str) -> Optional[str]:
    """data/{persona}/ ディレクトリから Live2D モデルファイルを返す。"""
    data_dir = get_data_dir()
    persona_dir = os.path.join(data_dir, persona)
    if not os.path.isdir(persona_dir):
        return None
    for pattern in ["*.model3.json", "*.model.json", "model.json"]:
        files = glob.glob(os.path.join(persona_dir, pattern))
        if files:
            return files[0]
    return None


@router.get("/api/avatar/scan/{persona}")
async def scan_avatar_files(persona: str):
    """data/{persona}/ からアバターモデルファイルを検索して返す。"""
    vrm_path = _find_vrm_file(persona)
    live2d_path = _find_live2d_file(persona)
    return {
        "vrm": vrm_path,
        "live2d": live2d_path,
    }


# ── VRM REST エンドポイント ────────────────────────────────────────────────────


@router.get("/api/avatar/vrm/{persona}/info")
async def get_vrm_info(persona: str):
    """ペルソナの VRM モデル利用可否と情報を返す。"""
    path = _find_vrm_file(persona)
    if path is None:
        return {"available": False, "persona": persona}
    stat = os.stat(path)
    return {
        "available": True,
        "persona": persona,
        "filename": os.path.basename(path),
        "size_mb": round(stat.st_size / 1024 / 1024, 1),
    }


@router.get("/api/avatar/vrm/{persona}/model")
async def get_vrm_model(persona: str):
    """ペルソナの VRM モデルファイルを配信する。"""
    path = _find_vrm_file(persona)
    if path is None:
        raise HTTPException(
            status_code=404,
            detail=f"VRM model not found for persona: {persona}. "
                   f"Place a .vrm file in data/{persona}/",
        )
    return FileResponse(
        path,
        media_type="model/gltf-binary",
        filename=os.path.basename(path),
        headers={"Cache-Control": "public, max-age=3600"},
    )


# ── 汎用アバター REST エンドポイント ──────────────────────────────────────────


@router.get("/api/avatar/state")
async def get_avatar_state(request: Request):
    """現在のアバター・感情状態を返す。"""
    persona = get_persona(request)
    from nous_mcp.server import get_psychology_db_path
    db_path = get_psychology_db_path(persona)
    try:
        from psychology.emotional_model import EmotionalModel
        em = EmotionalModel(persona, db_path)
        state = em.state
        return {
            "persona": persona,
            "emotion": state.surface_emotion,
            "intensity": state.surface_intensity,
            "mood": state.mood,
            "mood_valence": state.mood_valence,
            "mood_arousal": state.mood_arousal,
            "display_emotion": em.get_display_emotion(),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/avatar/express")
async def set_expression(request: Request, body: ExpressionRequest):
    """アバターの表情を設定する。VTube Studio + VRM Web + Live2D に送信。"""
    from nous_mcp.tools.avatar_tools import _vtube_adapters, _live2d_controllers
    persona = get_persona(request)
    results = {}

    vtube = _vtube_adapters.get(persona)
    if vtube:
        try:
            await vtube.set_expression(body.emotion, body.intensity)
            results["vtube_studio"] = "ok"
        except Exception as e:
            results["vtube_studio"] = str(e)

    # VRM + Live2D WebSocket にブロードキャスト
    payload = {"emotion": body.emotion, "intensity": body.intensity}
    await broadcast_avatar_state(payload)
    await broadcast_vrm_state(persona, payload)
    results["vrm_ws"] = f"{len(_vrm_clients.get(persona, set()))} clients"
    results["live2d_ws"] = f"{len(_connected_clients)} clients"

    return {"success": True, "emotion": body.emotion, "results": results}


@router.post("/api/avatar/speak")
async def speak(request: Request, body: SpeakRequest):
    """VOICEVOX で発話する。"""
    from nous_mcp.tools.avatar_tools import _voice_adapters
    persona = get_persona(request)
    voice = _voice_adapters.get(persona)
    if voice is None:
        raise HTTPException(status_code=503, detail="VoiceAdapter not configured")
    try:
        wav_bytes = await voice.speak(body.text)
        if not wav_bytes:
            raise HTTPException(status_code=500, detail="VOICEVOX returned empty audio")
        tmp_dir = os.path.join("data", "tmp")
        os.makedirs(tmp_dir, exist_ok=True)
        from datetime import datetime
        ts = datetime.now().strftime("%Y%m%d%H%M%S")
        tmp_path = os.path.join(tmp_dir, f"voice_{persona}_{ts}.wav")
        with open(tmp_path, "wb") as f:
            f.write(wav_bytes)
        return {
            "success": True,
            "text": body.text,
            "audio_url": f"/data/tmp/{os.path.basename(tmp_path)}",
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── WebSocket エンドポイント ──────────────────────────────────────────────────


@router.websocket("/ws/avatar")
async def avatar_websocket(websocket: WebSocket):
    """Live2D ブラウザ向け汎用 WebSocket エンドポイント（全ペルソナ共通）。"""
    await websocket.accept()
    async with _lock:
        _connected_clients.add(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        async with _lock:
            _connected_clients.discard(websocket)


@router.websocket("/ws/vrm/{persona}")
async def vrm_websocket(websocket: WebSocket, persona: str):
    """VRM ブラウザ向け per-persona WebSocket エンドポイント。

    クライアント接続時に現在の感情状態を送信する。
    サーバーから感情更新を受け取り VRM 表情に反映させる。
    """
    await websocket.accept()
    async with _vrm_lock:
        if persona not in _vrm_clients:
            _vrm_clients[persona] = set()
        _vrm_clients[persona].add(websocket)
    logger.info(f"VRM WS connected: {persona} (total: {len(_vrm_clients.get(persona, set()))})")

    # 接続時に現在の感情状態を送信
    try:
        from nous_mcp.server import get_psychology_db_path
        from psychology.emotional_model import EmotionalModel
        em = EmotionalModel(persona, get_psychology_db_path(persona))
        await websocket.send_text(json.dumps({
            "emotion": em.state.surface_emotion,
            "intensity": em.state.surface_intensity,
        }))
    except Exception:
        pass

    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        async with _vrm_lock:
            if persona in _vrm_clients:
                _vrm_clients[persona].discard(websocket)
        logger.info(f"VRM WS disconnected: {persona}")


async def broadcast_avatar_state(state: Dict[str, Any]) -> None:
    """全接続中クライアントに感情状態をブロードキャスト（汎用 /ws/avatar）。"""
    if not _connected_clients:
        return
    message = json.dumps(state, ensure_ascii=False)
    disconnected = set()
    for ws in list(_connected_clients):
        try:
            await ws.send_text(message)
        except Exception:
            disconnected.add(ws)
    if disconnected:
        async with _lock:
            _connected_clients -= disconnected


async def broadcast_vrm_state(persona: str, state: Dict[str, Any]) -> None:
    """特定ペルソナの VRM クライアントに感情状態をブロードキャスト。"""
    clients = _vrm_clients.get(persona)
    if not clients:
        return
    message = json.dumps(state, ensure_ascii=False)
    disconnected = set()
    for ws in list(clients):
        try:
            await ws.send_text(message)
        except Exception:
            disconnected.add(ws)
    if disconnected:
        async with _vrm_lock:
            if persona in _vrm_clients:
                _vrm_clients[persona] -= disconnected
