"""サンドボックスツール — manager 経由の隔離コンテナでシェルを実行する。

ホストのワークスペースには触れない。出力の切り詰め（末尾 120 行・全文 log_path）は
manager 側の契約で、ここでは末尾行数の上限だけ保険で掛け直す。
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

import httpx

from nous.application.chat.tools.shell import _tail

if TYPE_CHECKING:
    from nous.application.use_cases import AppContext
    from nous.domain.chat_config import ChatConfig

TAIL_LINES = 120
TOKEN_HEADER = "X-Sandbox-Token"
# manager 側の exec がタイムアウトを処理する間、こちらは少し長く待つ
TIMEOUT_GRACE_SECONDS = 10.0
_TRUE = {"1", "true", "yes", "on"}


def sandbox_settings(config: ChatConfig) -> tuple[bool, str, str]:
    """config.json → 環境変数の順で (enabled, url, token) を解決する。

    compose スタックだけで動かせるように、manager の URL とトークンは
    nous のサービス環境にも渡せる。config.json の値が優先。
    """
    raw_enabled = os.environ.get("NOUS_SANDBOX_ENABLED", "").strip().lower()
    enabled = raw_enabled in _TRUE if raw_enabled else bool(getattr(config, "sandbox_enabled", False))
    url = str(getattr(config, "sandbox_manager_url", "") or os.environ.get("NOUS_SANDBOX_MANAGER_URL", ""))
    token = str(getattr(config, "sandbox_manager_token", "") or os.environ.get("NOUS_SANDBOX_MANAGER_TOKEN", ""))
    return enabled, url.rstrip("/"), token


def _exec_body(config: ChatConfig, persona: str, command: str, cwd: str | None) -> dict:
    """manager に送る本体を組み立てる。未設定の項目は manager の env に任せる。"""
    body: dict = {"persona": persona, "command": command}
    if cwd:
        body["cwd"] = str(cwd)
    for field, key in (
        ("sandbox_image", "image"),
        ("sandbox_network", "network"),
        ("sandbox_memory", "memory"),
    ):
        value = str(getattr(config, field, "") or "")
        if value:
            body[key] = value
    idle = getattr(config, "sandbox_idle_minutes", 0) or 0
    if idle > 0:
        body["idle_minutes"] = float(idle)
    body["timeout_seconds"] = float(getattr(config, "shell_timeout_seconds", 120))
    return body


async def handle_sandbox(ctx: AppContext, config: ChatConfig, tool_input: dict) -> dict:
    _enabled, url, token = sandbox_settings(config)
    if not url:
        return {"status": "error", "error": "sandbox_manager_url is not configured"}
    persona = getattr(ctx, "persona", None)
    if not persona:
        return {"status": "error", "error": "persona is not set"}
    if not token:
        return {"status": "error", "error": "sandbox_manager_token is not configured"}
    command = str(tool_input.get("command") or "").strip()
    if not command:
        return {"status": "error", "error": "command is required"}

    body = _exec_body(config, persona, command, tool_input.get("cwd"))
    timeout = float(getattr(config, "shell_timeout_seconds", 120))

    try:
        async with httpx.AsyncClient(timeout=timeout + TIMEOUT_GRACE_SECONDS) as client:
            response = await client.post(f"{url}/exec", json=body, headers={TOKEN_HEADER: token})
            if response.status_code != 200:
                detail = response.text[:500]
                return {"status": "error", "error": f"sandbox-manager: HTTP {response.status_code} {detail}".strip()}
            payload = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        return {"status": "error", "error": f"sandbox-manager: {exc}"}

    if not isinstance(payload, dict):
        return {"status": "error", "error": "sandbox-manager: invalid response"}
    cut = bool(payload.get("truncated"))
    for key in ("stdout_tail", "stderr_tail"):
        if isinstance(payload.get(key), str):
            payload[key], more = _tail(payload[key], TAIL_LINES)
            cut = cut or more
    payload["truncated"] = cut
    return payload
