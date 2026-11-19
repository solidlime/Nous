"""サンドボックス設定の解決（manager の URL / トークン / 有効判定）。

実際の exec は :mod:`nous.application.chat.tools.sandbox_shell` が担る。
ここに置いているのは、sandbox_shell と definitions の両方が参照するため。
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from nous.domain.config.chat_config import ChatConfig

TOKEN_HEADER = "X-Sandbox-Token"
# manager 側の exec がタイムアウトを処理する間、こちらは少し長く待つ
TIMEOUT_GRACE_SECONDS = 10.0
_TRUE = {"1", "true", "yes", "on"}


def sandbox_settings(config: ChatConfig) -> tuple[bool, str, str]:
    """(enabled, url, token) を解決する。

    url / token は config.json 優先で、無ければ環境変数（compose スタックだけで
    動かせるように）。**enabled だけは環境変数が優先** — 障害時のキルスイッチとして
    `NOUS_SANDBOX_ENABLED=false` を 1 箇所で効かせるため（config 側の true を上書きする）。
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
