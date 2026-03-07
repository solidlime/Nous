"""
Nous 設定 CRUD REST API ルーター。
"""

import json
import logging
import os
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

from config import load_config, get_config_path

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/settings", tags=["settings"])

_SENSITIVE_KEYS = {
    "discord.bot_token", "discord.token",
    "llm.api_key", "llm.claude.api_key",
    "llm.openrouter.api_key", "openrouter_api_key",
    "anthropic_api_key", "openrouter_api_key",
}


def _mask_sensitive(data: dict, prefix: str = "") -> dict:
    """センシティブな値を '***' にマスクする。"""
    result = {}
    for k, v in data.items():
        full_key = f"{prefix}.{k}" if prefix else k
        if isinstance(v, dict):
            result[k] = _mask_sensitive(v, full_key)
        elif any(sk in full_key.lower() for sk in ["token", "api_key", "secret", "password"]):
            result[k] = "***" if v else ""
        else:
            result[k] = v
    return result


def _save_config(new_config: dict) -> None:
    """設定を config.json に保存する。"""
    config_path = get_config_path()
    os.makedirs(os.path.dirname(config_path), exist_ok=True)

    # 既存設定を読み込み
    existing = {}
    if os.path.exists(config_path):
        with open(config_path, "r", encoding="utf-8") as f:
            existing = json.load(f)

    # センシティブ値: 空文字列の場合は既存値を保持
    def _merge_preserve_secrets(current: dict, new: dict) -> dict:
        merged = dict(current)
        for k, v in new.items():
            if isinstance(v, dict) and isinstance(merged.get(k), dict):
                merged[k] = _merge_preserve_secrets(merged[k], v)
            elif v == "***" or v == "":
                pass  # 既存値を保持
            else:
                merged[k] = v
        return merged

    merged = _merge_preserve_secrets(existing, new_config)

    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(merged, f, ensure_ascii=False, indent=2)

    # キャッシュをリセット（hot reload）
    load_config(force=True)


@router.get("")
async def get_settings():
    """全設定を取得する（センシティブ値はマスク）。"""
    config = load_config()
    return _mask_sensitive(config)


@router.put("")
async def update_settings(request: Request):
    """設定を一括更新する。保存後に LLM Router をホットリロードする。"""
    try:
        body = await request.json()
        _save_config(body)
        # LLM Router を新しい設定で再構築（APIキー変更を即座に反映）
        try:
            from main import rebuild_llm_router
            rebuild_llm_router()
        except Exception as e:
            logger.warning(f"LLM Router rebuild after save failed: {e}")
        return {"success": True, "message": "Settings saved and reloaded"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{section}")
async def get_settings_section(section: str):
    """セクション単位で設定を取得する。"""
    config = load_config()
    if section not in config:
        raise HTTPException(status_code=404, detail=f"Section not found: {section}")
    section_data = config[section]
    if isinstance(section_data, dict):
        return _mask_sensitive(section_data, section)
    return {section: section_data}


@router.put("/{section}")
async def update_settings_section(section: str, request: Request):
    """セクション単位で設定を更新する。"""
    try:
        body = await request.json()
        _save_config({section: body})
        return {"success": True, "section": section}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/test/openrouter")
async def test_openrouter_connection(request: Request):
    """OpenRouter API キー確認テスト。
    ボディに {"api_key": "sk-or-..."} を渡すと保存前でもテスト可能。
    """
    try:
        body = await request.json()
    except Exception:
        body = {}
    # ボディの値 → 保存済み config → 環境変数 の優先順
    api_key = (body.get("api_key") or "").strip()
    if not api_key or api_key == "***":
        cfg = load_config()
        api_key = cfg.get("llm", {}).get("openrouter", {}).get("api_key") or os.getenv("OPENROUTER_API_KEY", "")
    if not api_key or api_key == "***":
        return {"success": False, "error": "API key not configured"}
    return {"success": True, "message": "API key is configured"}


@router.post("/test/claude")
async def test_claude_connection(request: Request):
    """Claude (Anthropic) API キー確認テスト。
    ボディに {"api_key": "sk-ant-..."} を渡すと保存前でもテスト可能。
    """
    try:
        body = await request.json()
    except Exception:
        body = {}
    api_key = (body.get("api_key") or "").strip()
    if not api_key or api_key == "***":
        cfg = load_config()
        api_key = cfg.get("llm", {}).get("claude", {}).get("api_key") or os.getenv("ANTHROPIC_API_KEY", "")
    if not api_key or api_key == "***":
        return {"success": False, "error": "API key not configured"}
    return {"success": True, "message": "API key is configured"}


@router.post("/test/ollama")
async def test_ollama_connection(request: Request):
    """Ollama 接続テスト。ボディに {"base_url": "..."} を渡すと保存前でもテスト可能。"""
    import aiohttp
    try:
        body = await request.json()
    except Exception:
        body = {}
    base_url = (body.get("base_url") or "").strip()
    if not base_url:
        cfg = load_config()
        base_url = cfg.get("llm", {}).get("ollama", {}).get("base_url",
                   os.getenv("OLLAMA_BASE_URL", "http://localhost:11434"))
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get(f"{base_url}/api/version", timeout=aiohttp.ClientTimeout(total=5)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return {"success": True, "message": f"Ollama {data.get('version', 'OK')}"}
                return {"success": False, "error": f"HTTP {resp.status}"}
    except Exception as e:
        return {"success": False, "error": str(e)}


@router.post("/test/llm")
async def test_llm_connection(request: Request):
    """LLM 接続テスト。"""
    try:
        body = await request.json()
    except Exception:
        body = {}
    provider = body.get("provider", "ollama")
    config = load_config()

    if provider == "ollama":
        import aiohttp
        url = config.get("llm", {}).get("ollama", {}).get("base_url",
              config.get("ollama_base_url", "http://localhost:11434"))
        try:
            async with aiohttp.ClientSession() as s:
                async with s.get(f"{url}/api/version", timeout=aiohttp.ClientTimeout(total=5)) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        return {"success": True, "message": f"Ollama {data.get('version', 'OK')}"}
                    return {"success": False, "error": f"HTTP {resp.status}"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    elif provider == "claude":
        api_key = config.get("llm", {}).get("claude", {}).get("api_key") or os.getenv("ANTHROPIC_API_KEY", "")
        if not api_key:
            return {"success": False, "error": "API key not configured"}
        return {"success": True, "message": "API key is configured"}

    elif provider == "openrouter":
        api_key = config.get("llm", {}).get("openrouter", {}).get("api_key") or os.getenv("OPENROUTER_API_KEY", "")
        if not api_key:
            return {"success": False, "error": "API key not configured"}
        return {"success": True, "message": "API key is configured"}

    return {"success": False, "error": f"Unknown provider: {provider}"}


@router.post("/test/discord")
async def test_discord_connection(request: Request):
    """Discord 接続テスト。ボディに {"bot_token": "..."} を渡すと保存前でもテスト可能。"""
    try:
        body = await request.json()
    except Exception:
        body = {}
    token = (body.get("bot_token") or "").strip()
    if not token or token == "***":
        cfg = load_config()
        token = cfg.get("discord", {}).get("bot_token") or os.getenv("DISCORD_BOT_TOKEN", "")
    if not token or token == "***":
        return {"success": False, "error": "Bot token not configured"}
    return {"success": True, "message": "Token is configured (connection not tested at startup)"}


@router.post("/test/voicevox")
async def test_voicevox_connection():
    """VOICEVOX 接続テスト。"""
    import aiohttp
    config = load_config()
    url = config.get("voice", {}).get("voicevox_url", "http://localhost:50021")
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get(f"{url}/version", timeout=aiohttp.ClientTimeout(total=5)) as resp:
                if resp.status == 200:
                    version = await resp.text()
                    return {"success": True, "message": f"VOICEVOX {version.strip()}"}
                return {"success": False, "error": f"HTTP {resp.status}"}
    except Exception as e:
        return {"success": False, "error": str(e)}


@router.post("/test/qdrant")
async def test_qdrant_connection():
    """Qdrant 接続テスト。"""
    import aiohttp
    config = load_config()
    url = config.get("qdrant_url", "http://localhost:6333")
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get(f"{url}/health", timeout=aiohttp.ClientTimeout(total=5)) as resp:
                if resp.status == 200:
                    return {"success": True, "message": "Qdrant OK"}
                return {"success": False, "error": f"HTTP {resp.status}"}
    except Exception as e:
        return {"success": False, "error": str(e)}


@router.get("/voicevox/speakers")
async def get_voicevox_speakers():
    """VOICEVOX の利用可能話者一覧を取得する。"""
    import aiohttp
    config = load_config()
    url = config.get("voice", {}).get("voicevox_url", "http://localhost:50021")
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get(f"{url}/speakers", timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status == 200:
                    speakers_raw = await resp.json()
                    speakers = []
                    for sp in speakers_raw:
                        for style in sp.get("styles", [{}]):
                            speakers.append({
                                "id": style.get("id", 0),
                                "name": f"{sp.get('name', '')} ({style.get('name', '')})",
                            })
                    return {"speakers": speakers}
                return {"error": f"HTTP {resp.status}"}
    except Exception as e:
        return {"error": str(e)}


@router.post("/test/mcp")
async def test_mcp_server(request: Request):
    """外部 MCP サーバーへの接続テストとツール一覧取得。

    ボディ: {"url": "http://...", "auth_token": "Bearer xxx" | null}
    """
    import aiohttp
    try:
        body = await request.json()
    except Exception:
        body = {}
    url = (body.get("url") or "").strip().rstrip("/")
    auth_token = (body.get("auth_token") or "").strip()
    if not url:
        return {"success": False, "error": "URL is required"}

    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if auth_token:
        headers["Authorization"] = auth_token if auth_token.startswith("Bearer ") else f"Bearer {auth_token}"

    # MCP JSON-RPC 2.0 over HTTP (stateless): tools/list を呼ぶ
    tools_payload = {
        "jsonrpc": "2.0",
        "method": "tools/list",
        "params": {},
        "id": 1,
    }
    # FastMCP stateless_http のエンドポイント候補
    mcp_paths = ["/mcp", "/", ""]
    timeout = aiohttp.ClientTimeout(total=8)

    async with aiohttp.ClientSession() as session:
        for path in mcp_paths:
            endpoint = f"{url}{path}"
            try:
                async with session.post(
                    endpoint, json=tools_payload, headers=headers, timeout=timeout
                ) as resp:
                    if resp.status not in (200, 201):
                        continue
                    data = await resp.json(content_type=None)
                    # JSON-RPC result
                    if "result" in data:
                        tools = data["result"].get("tools", [])
                        tool_list = [
                            {"name": t.get("name", ""), "description": t.get("description", "")}
                            for t in tools
                        ]
                        return {"success": True, "tools": tool_list, "endpoint": endpoint}
                    # ルートが見つかったが tools/list ではない → 接続は OK
                    return {"success": True, "tools": [], "message": "Connected but tools/list returned no result", "endpoint": endpoint}
            except Exception:
                continue

        # 全パス失敗: 単純な GET で生死確認
        try:
            async with session.get(url, timeout=timeout) as resp:
                if resp.status < 500:
                    return {"success": True, "tools": [], "message": f"Server responded with HTTP {resp.status} (MCP tools/list not available at standard paths)"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    return {"success": False, "error": "Could not connect to MCP server"}


@router.get("/ollama/models")
async def get_ollama_models():
    """Ollama の利用可能モデル一覧を取得する。"""
    import aiohttp
    config = load_config()
    url = config.get("llm", {}).get("ollama", {}).get("base_url",
          config.get("ollama_base_url", "http://localhost:11434"))
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get(f"{url}/api/tags", timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    models = [m["name"] for m in data.get("models", [])]
                    return {"models": models}
                return {"error": f"HTTP {resp.status}"}
    except Exception as e:
        return {"error": str(e)}


@router.post("/reload")
async def reload_settings():
    """設定を hot reload する（再起動不要）。"""
    load_config(force=True)
    return {"success": True, "message": "Settings reloaded"}
