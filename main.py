"""
Nous — AIキャラクター自律稼働システム エントリポイント。

FastMCP（MCP Server）と FastAPI（REST + WebSocket）を統合起動する。
"""

import asyncio
import logging
import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from config import load_config

# ── ロギング設定 ─────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)


# ── 起動 / シャットダウンライフサイクル ──────────────────────────────────────

_background_tasks: list = []
_agent_loops: dict = {}
_discord_bots: dict = {}
_forgetting_workers: dict = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    """FastAPI ライフサイクル — 起動時初期化とシャットダウン処理。"""
    cfg = load_config()
    active_personas = cfg.get("active_personas", ["herta"])
    logger.info(f"Nous 起動中... personas: {active_personas}")

    # ── データディレクトリ作成 ─────────────────────────────────────────────
    data_dir = cfg.get("data_dir", "data")
    for persona in active_personas:
        Path(data_dir, persona).mkdir(parents=True, exist_ok=True)

    # ── LLM Router 初期化 ─────────────────────────────────────────────────
    llm_router = _init_llm_router(cfg)

    # ── AgentLoop 初期化 ──────────────────────────────────────────────────
    from nous_mcp.tools.agent_tools import register_agent_loops, register_elevation_processors
    from elevation.batch_processor import ElevationBatchProcessor

    for persona in active_personas:
        try:
            from memory.db import MemoryDB
            from memory.conversation_db import ConversationDB
            from psychology.engine import PsychologyEngine
            from psychology.decision_engine import DecisionEngine
            from agent.loop import AgentLoop
            from nous_mcp.server import get_db_path, get_psychology_db_path, get_conversation_db_path

            memory_db = MemoryDB(get_db_path(persona))
            conv_db = ConversationDB(get_conversation_db_path(persona))
            # PsychologyEngine が AppraisalEngine/EmotionalModel/DriveSystem/GoalManager を束ねる
            psychology_engine = PsychologyEngine(persona, get_psychology_db_path(persona), config=cfg)
            decision_engine = DecisionEngine()

            loop = AgentLoop(
                persona=persona,
                llm_router=llm_router,
                memory_db=memory_db,
                conv_db=conv_db,
                # ContextBuilder 用に個別モデルも渡す（engine 内部のインスタンスを参照）
                emotional_model=psychology_engine.emotional,
                drive_system=psychology_engine.drives,
                goal_manager=psychology_engine.goals,
                decision_engine=decision_engine,
                config=cfg,
                psychology_engine=psychology_engine,
            )
            _agent_loops[persona] = loop
            logger.info(f"AgentLoop 初期化完了: {persona}")
        except Exception as e:
            logger.error(f"AgentLoop 初期化失敗 [{persona}]: {e}", exc_info=True)

    register_agent_loops(_agent_loops)

    # ElevationBatchProcessor
    elevation_processors = {}
    for persona in active_personas:
        try:
            from memory.db import MemoryDB
            from nous_mcp.server import get_db_path
            memory_db = MemoryDB(get_db_path(persona))
            ep = ElevationBatchProcessor(llm_router=llm_router, memory_db=memory_db, config=cfg)
            elevation_processors[persona] = ep
        except Exception as e:
            logger.warning(f"ElevationBatchProcessor 初期化失敗 [{persona}]: {e}")
    register_elevation_processors(elevation_processors)

    # ── アバターアダプター初期化 ──────────────────────────────────────────
    from nous_mcp.tools.avatar_tools import register_avatar_adapters
    for persona in active_personas:
        try:
            vtube_adapter = _init_vtube_studio(cfg, persona)
            voice_adapter = _init_voice_adapter(cfg, persona)
            live2d_controller = _init_live2d_controller(cfg, persona)
            register_avatar_adapters(
                vtube={persona: vtube_adapter} if vtube_adapter else None,
                voice={persona: voice_adapter} if voice_adapter else None,
                live2d={persona: live2d_controller} if live2d_controller else None,
            )
        except Exception as e:
            logger.warning(f"アバターアダプター初期化失敗 [{persona}]: {e}")

    # chat_routes / dashboard_routes に AgentLoop を登録
    from api.chat_routes import register_agent_loops as register_chat_loops
    register_chat_loops(_agent_loops)

    # ── Ebbinghaus 忘却ワーカー起動 ───────────────────────────────────────
    for persona in active_personas:
        try:
            from memory.forgetting import start_forgetting_worker
            from nous_mcp.server import get_db_path
            thread = start_forgetting_worker(get_db_path(persona))
            _forgetting_workers[persona] = thread
            logger.info(f"Ebbinghaus 忘却ワーカー起動: {persona}")
        except Exception as e:
            logger.warning(f"忘却ワーカー起動失敗 [{persona}]: {e}")

    # ── AgentLoop バックグラウンドタスク起動 ─────────────────────────────
    for persona, loop in _agent_loops.items():
        try:
            task = asyncio.create_task(loop.run(), name=f"agent_loop_{persona}")
            _background_tasks.append(task)
            logger.info(f"AgentLoop バックグラウンド起動: {persona}")
        except Exception as e:
            logger.error(f"AgentLoop 起動失敗 [{persona}]: {e}")

    # ── Discord Bot 起動 ──────────────────────────────────────────────────
    discord_cfg = cfg.get("discord", {})
    if discord_cfg.get("enabled", False):
        try:
            from output.discord_bot import DiscordBot
            for persona in active_personas:
                token = discord_cfg.get("bot_token") or os.getenv("DISCORD_BOT_TOKEN", "")
                if token:
                    bot = DiscordBot(
                        persona=persona,
                        token=token,
                        agent_loop=_agent_loops.get(persona),
                        config=cfg,
                    )
                    _discord_bots[persona] = bot
                    task = asyncio.create_task(bot.start_async(), name=f"discord_{persona}")
                    _background_tasks.append(task)
                    logger.info(f"Discord Bot 起動: {persona}")
        except Exception as e:
            logger.warning(f"Discord Bot 起動失敗: {e}")

    logger.info("Nous 起動完了!")

    yield  # ─── アプリケーション実行中 ───────────────────────────────────

    # ── シャットダウン処理 ─────────────────────────────────────────────────
    logger.info("Nous シャットダウン中...")

    # Discord Bot 停止
    for persona, bot in _discord_bots.items():
        try:
            await bot.close()
        except Exception:
            pass

    # バックグラウンドタスクをキャンセル
    for task in _background_tasks:
        task.cancel()

    if _background_tasks:
        await asyncio.gather(*_background_tasks, return_exceptions=True)

    logger.info("Nous シャットダウン完了")


# ── LLM Router 初期化ヘルパー ────────────────────────────────────────────────

def _init_llm_router(cfg: dict):
    """設定から LLM Router を初期化する。"""
    from llm.router import LLMRouter
    from llm.ollama_provider import OllamaProvider
    from llm.claude_provider import ClaudeProvider
    from llm.openrouter_provider import OpenRouterProvider

    llm_cfg = cfg.get("llm", {})
    providers = {}

    # Ollama（常に登録: APIキー不要）
    ollama_cfg = llm_cfg.get("ollama", {})
    ollama_url = (
        ollama_cfg.get("base_url")
        or os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
    )
    providers["ollama"] = OllamaProvider(
        base_url=ollama_url,
        model=ollama_cfg.get("model", "gemma3"),
        timeout=ollama_cfg.get("timeout_sec", 120),
    )

    # Claude（APIキーがある場合のみ登録）
    claude_cfg = llm_cfg.get("claude", {})
    api_key = claude_cfg.get("api_key") or os.getenv("ANTHROPIC_API_KEY", "")
    if api_key:
        providers["claude"] = ClaudeProvider(
            api_key=api_key,
            model=claude_cfg.get("model", "claude-sonnet-4-6"),
            max_tokens=claude_cfg.get("max_tokens", 1000),
        )

    # OpenRouter（APIキーがある場合のみ登録）
    or_cfg = llm_cfg.get("openrouter", {})
    or_key = or_cfg.get("api_key") or os.getenv("OPENROUTER_API_KEY", "")
    if or_key:
        providers["openrouter"] = OpenRouterProvider(
            api_key=or_key,
            model=or_cfg.get("model", "google/gemma-3-9b-it"),
            site_url=or_cfg.get("site_url", ""),
        )

    routing_table = llm_cfg.get("routing", {})
    return LLMRouter(providers=providers, routing_table=routing_table)


def rebuild_llm_router() -> None:
    """設定変更後に LLM Router を再構築して全 AgentLoop に反映する。

    settings_routes.py から設定保存後に呼ばれる。
    """
    from config import load_config
    cfg = load_config(force=True)
    new_router = _init_llm_router(cfg)
    for persona, loop in _agent_loops.items():
        try:
            loop._llm_router = new_router
            logger.info(f"LLM Router rebuilt for {persona}")
        except Exception as e:
            logger.warning(f"LLM Router rebuild failed for {persona}: {e}")


async def stop_agent_loop(persona: str) -> dict:
    """指定ペルソナの AgentLoop を停止する。

    agent_routes.py から呼び出される。
    バックグラウンドタスクをキャンセルして終了を待つ。
    """
    loop = _agent_loops.get(persona)
    if loop is None:
        return {"success": False, "error": f"AgentLoop not found for: {persona}"}

    # _background_tasks から該当タスクを探してキャンセル
    task_name = f"agent_loop_{persona}"
    cancelled = False
    for task in list(_background_tasks):
        if task.get_name() == task_name and not task.done():
            task.cancel()
            try:
                await asyncio.wait_for(asyncio.shield(task), timeout=5.0)
            except (asyncio.CancelledError, asyncio.TimeoutError):
                pass
            _background_tasks.remove(task)
            cancelled = True
            break

    if not cancelled and loop._running:
        return {"success": False, "error": "Task not found in background tasks"}

    logger.info(f"AgentLoop 停止要求: {persona}")
    return {"success": True, "status": "stopped", "persona": persona}


async def start_agent_loop(persona: str) -> dict:
    """指定ペルソナの AgentLoop を起動する。

    agent_routes.py から呼び出される。
    既に起動中の場合は何もしない。
    """
    loop = _agent_loops.get(persona)
    if loop is None:
        return {"success": False, "error": f"AgentLoop not initialized for: {persona}"}

    # 既に起動中なら何もしない
    if loop._running:
        return {"success": True, "status": "running", "persona": persona, "note": "already running"}

    # バックグラウンドタスクとして起動
    task = asyncio.create_task(loop.run(), name=f"agent_loop_{persona}")
    _background_tasks.append(task)
    logger.info(f"AgentLoop 再起動: {persona}")
    return {"success": True, "status": "starting", "persona": persona}


# ── アバターアダプター初期化ヘルパー ─────────────────────────────────────────

def _init_vtube_studio(cfg: dict, persona: str):
    """VTube Studio アダプターを初期化する。"""
    avatar_cfg = cfg.get("avatar", {})
    vtube_cfg = avatar_cfg.get("vtube_studio", {})
    if not vtube_cfg.get("enabled", False):
        return None
    try:
        from output.avatar.vtube_studio import VTubeStudioAdapter
        ws_url = vtube_cfg.get("ws_url") or os.getenv("VTUBE_STUDIO_WS", "ws://localhost:8001")
        return VTubeStudioAdapter(
            ws_url=ws_url,
            plugin_name=vtube_cfg.get("plugin_name", "Nous"),
        )
    except Exception as e:
        logger.warning(f"VTubeStudio 初期化失敗: {e}")
        return None


def _init_voice_adapter(cfg: dict, persona: str):
    """VOICEVOX 音声アダプターを初期化する。"""
    voice_cfg = cfg.get("voice", {})
    if not voice_cfg.get("enabled", False):
        return None
    try:
        from output.voice_adapter import VoiceAdapter
        voicevox_url = (
            voice_cfg.get("voicevox_url")
            or os.getenv("VOICEVOX_URL", "http://localhost:50021")
        )
        persona_voice = voice_cfg.get("personas", {}).get(persona, {})
        speaker_id = persona_voice.get("speaker_id", voice_cfg.get("speaker_id", 0))
        return VoiceAdapter(
            voicevox_url=voicevox_url,
            speaker_id=speaker_id,
            speed_scale=persona_voice.get("speed_scale", 1.0),
            pitch_scale=persona_voice.get("pitch_scale", 0.0),
            volume_scale=persona_voice.get("volume_scale", 1.0),
        )
    except Exception as e:
        logger.warning(f"VoiceAdapter 初期化失敗: {e}")
        return None


def _init_live2d_controller(cfg: dict, persona: str):
    """Live2D Web コントローラーを初期化する。"""
    avatar_cfg = cfg.get("avatar", {})
    live2d_cfg = avatar_cfg.get("live2d_web", {})
    if not live2d_cfg.get("enabled", True):
        return None
    try:
        from output.avatar.live2d_web import Live2DWebController
        return Live2DWebController(persona=persona)
    except Exception as e:
        logger.warning(f"Live2DWebController 初期化失敗: {e}")
        return None


# ── FastAPI + FastMCP アプリ構築 ────────────────────────────────────────────

def create_app() -> FastAPI:
    """FastAPI アプリケーションを構築して返す。"""
    cfg = load_config()
    server_cfg = cfg.get("server", {})

    app = FastAPI(
        title="Nous",
        description="AIキャラクター自律稼働システム",
        version="1.0.0",
        lifespan=lifespan,
    )

    # CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # テンプレート
    templates_dir = Path("templates")
    templates_dir.mkdir(exist_ok=True)
    templates = Jinja2Templates(directory=str(templates_dir))

    # 静的ファイル
    static_dir = Path("static")
    static_dir.mkdir(exist_ok=True)
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    # data/tmp ディレクトリ（音声ファイル一時保存）
    data_tmp_dir = Path("data/tmp")
    data_tmp_dir.mkdir(parents=True, exist_ok=True)
    app.mount("/data/tmp", StaticFiles(directory=str(data_tmp_dir)), name="data_tmp")

    # ── REST API ルーター登録 ───────────────────────────────────────────────
    from api.memory_routes import router as memory_router
    from api.agent_routes import router as agent_router
    from api.avatar_routes import router as avatar_router
    from api.settings_routes import router as settings_router
    from api.conversation_routes import router as conversation_router
    from api.chat_routes import router as chat_router, set_templates as set_chat_templates
    from api.dashboard_routes import (
        router as dashboard_router,
        set_templates as set_dashboard_templates,
    )

    # テンプレートを各ルーターに注入
    set_chat_templates(templates)
    set_dashboard_templates(templates)

    app.include_router(dashboard_router)
    app.include_router(memory_router)
    app.include_router(agent_router)
    app.include_router(avatar_router)
    app.include_router(settings_router)
    app.include_router(conversation_router)
    app.include_router(chat_router)

    # ── MCP Server マウント ────────────────────────────────────────────────
    try:
        from nous_mcp.server import create_mcp
        from nous_mcp.tools.memory_tools import register_memory_tools
        from nous_mcp.tools.psychology_tools import register_psychology_tools
        from nous_mcp.tools.agent_tools import register_agent_tools
        from nous_mcp.tools.avatar_tools import register_avatar_tools

        mcp_server = create_mcp()
        register_memory_tools(mcp_server)
        register_psychology_tools(mcp_server)
        register_agent_tools(mcp_server)
        register_avatar_tools(mcp_server)

        # FastAPI に MCP を ASGI でマウント
        try:
            mcp_app = mcp_server.http_app(stateless_http=True)
        except (TypeError, AttributeError):
            mcp_app = mcp_server.streamable_http_app()
        app.mount("/mcp", mcp_app)
        logger.info("MCP Server マウント完了 → /mcp")
    except Exception as e:
        logger.error(f"MCP Server マウント失敗: {e}", exc_info=True)

    return app


# ── Webhook ルーター追加 ─────────────────────────────────────────────────────

def _register_webhook_routes(app: FastAPI, cfg: dict) -> None:
    """Webhook 受信ルーターを追加する。"""
    try:
        from output.webhook import router as webhook_router
        app.include_router(webhook_router)
        logger.info("Webhook ルーター登録完了")
    except ImportError:
        logger.debug("Webhook ルーターなし（スキップ）")
    except Exception as e:
        logger.warning(f"Webhook ルーター登録失敗: {e}")


# ── エントリポイント ──────────────────────────────────────────────────────────

def main():
    """Nous サーバーを起動する。"""
    cfg = load_config()
    server_cfg = cfg.get("server", {})

    host = os.getenv("HOST", server_cfg.get("host", "0.0.0.0"))
    port = int(os.getenv("PORT", server_cfg.get("port", 26263)))

    logger.info(f"Nous サーバー起動: http://{host}:{port}")
    logger.info(f"MCP エンドポイント: http://{host}:{port}/mcp")
    logger.info(f"ダッシュボード: http://{host}:{port}/dashboard")

    app = create_app()
    _register_webhook_routes(app, cfg)

    uvicorn.run(
        app,
        host=host,
        port=port,
        log_level="info",
        access_log=True,
    )


if __name__ == "__main__":
    main()
