"""
Nous MCP サーバー初期化モジュール。

FastMCP + ペルソナ解決関数を提供する。
"""

import os
from typing import Optional

from fastmcp import FastMCP
from starlette.requests import Request

from config import load_config

# グローバル MCP インスタンス（main.py で初期化後に参照される）
_mcp_instance: Optional[FastMCP] = None


def get_mcp() -> FastMCP:
    """現在の FastMCP インスタンスを返す。"""
    global _mcp_instance
    if _mcp_instance is None:
        raise RuntimeError("MCP server not initialized. Call create_mcp() first.")
    return _mcp_instance


def create_mcp() -> FastMCP:
    """FastMCP インスタンスを作成・初期化して返す。"""
    global _mcp_instance
    cfg = load_config()
    _mcp_instance = FastMCP(
        name="nous",
        instructions=(
            "Nous — AIキャラクター自律稼働システム。"
            "マルチペルソナ対応記憶管理・心理状態・エージェント制御を提供する。"
            "Authorization: Bearer {persona_name} ヘッダーでペルソナを切り替える。"
        ),
    )
    return _mcp_instance


def get_persona(request: Optional[Request] = None) -> str:
    """
    リクエストからペルソナ名を解決する。

    優先順位:
    1. Authorization: Bearer {persona} ヘッダー
    2. PERSONA 環境変数
    3. config.json の default_persona
    """
    if request is not None:
        auth = request.headers.get("Authorization", "")
        if auth.startswith("Bearer "):
            persona = auth[7:].strip()
            if persona:
                return persona
    env_persona = os.getenv("PERSONA", "")
    if env_persona:
        return env_persona
    return load_config().get("default_persona", "nous")


def get_db_path(persona: str) -> str:
    """記憶 DB のパスを返す。"""
    from config import load_config as _cfg
    cfg = _cfg()
    data_dir = cfg.get("data_dir", "data")
    return os.path.join(data_dir, persona, "memory.db")


def get_psychology_db_path(persona: str) -> str:
    """心理 DB のパスを返す。"""
    from config import load_config as _cfg
    cfg = _cfg()
    data_dir = cfg.get("data_dir", "data")
    return os.path.join(data_dir, persona, "psychology.db")


def get_conversation_db_path(persona: str) -> str:
    """会話スレッド DB のパスを返す。"""
    from config import load_config as _cfg
    cfg = _cfg()
    data_dir = cfg.get("data_dir", "data")
    return os.path.join(data_dir, persona, "conversations.db")
