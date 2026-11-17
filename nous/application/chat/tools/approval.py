"""ワークスペースツールの承認ポリシー（auto / allowlist / ask）。

`ChatConfig.shell_approval_mode` の解釈はここ 1 箇所だけに置く。
inference は「承認が要るか」を聞くだけで、モードの意味を知らない。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from nous.domain.config.chat_config import ChatConfig

# 承認が要り得るツール。read_file は読み取りなので常に素通し。
APPROVAL_REQUIRED_TOOLS = frozenset({"bash", "write_file", "edit_file", "delegate", "sandbox"})

APPROVAL_TIMEOUT_SECONDS = 120.0


def _command_head(tool_input: dict | None) -> str:
    command = tool_input.get("command") if isinstance(tool_input, dict) else None
    parts = str(command or "").split()
    return parts[0] if parts else ""


def approval_required(config: ChatConfig, tool_name: str, tool_input: dict | None) -> bool:
    """このツール呼び出しに人間の承認が要るか。未知のモードは ask 扱い（安全側）。"""
    if tool_name not in APPROVAL_REQUIRED_TOOLS:
        return False
    mode = getattr(config, "shell_approval_mode", "ask")
    if mode == "auto":
        return False
    if mode == "allowlist":
        allowed = getattr(config, "shell_allowed_commands", None) or []
        return _command_head(tool_input) not in allowed
    return True


# 承認ダイアログに出す要約キー。bash はコマンド、delegate はプロンプト、それ以外はパス。
_PAYLOAD_KEYS = {"bash": "command", "delegate": "prompt", "sandbox": "command"}


def approval_payload(tool_name: str, tool_input: dict | None) -> dict:
    """SSE に流す要約。長い本文は 300 字で切る。"""
    if not isinstance(tool_input, dict):
        tool_input = {}
    raw = tool_input.get(_PAYLOAD_KEYS.get(tool_name, "path"))
    detail = str(raw or "")
    return {"tool_name": tool_name, "detail": detail[:300] if tool_name != "write_file" else detail}
