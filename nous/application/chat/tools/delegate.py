"""delegate ツール — pi をサブプロセスで起動し、作業を別エージェントに投げる。

コンテキスト衛生は bash と同じ: 出力は末尾 :data:`TAIL_LINES` 行だけ返し、
全文は artifact に落として ``read_file`` で読み直させる。
"""

from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING

from nous.application.chat.tools.shell import (
    TAIL_LINES,
    _communicate_with_timeout,
    _save_log,
    _tail,
)
from nous.application.chat.tools.workspace import (
    WorkspaceError,
    relative_to_root,
    resolve_in_workspace,
    workspace_root,
)
from nous.infrastructure.logging.structured import get_logger

if TYPE_CHECKING:
    from nous.application.use_cases import AppContext
    from nous.domain.chat_config import ChatConfig

logger = get_logger(__name__)

PI_COMMAND = "pi"


async def _handle_delegate(ctx: AppContext, config: ChatConfig, tool_input: dict) -> dict:
    try:
        root = workspace_root(config)
    except WorkspaceError as e:
        return {"status": "error", "message": str(e)}

    prompt = str(tool_input.get("prompt") or "").strip()
    if not prompt:
        return {"status": "error", "message": "prompt が空"}
    # agent は今のところ表示だけ。実エージェント解決の差し込み口はここ。
    agent = str(tool_input.get("agent") or "general").strip() or "general"

    try:
        cwd = resolve_in_workspace(root, tool_input["workdir"]) if tool_input.get("workdir") else root
    except WorkspaceError as e:
        return {"status": "error", "message": str(e)}
    if not cwd.is_dir():
        return {"status": "error", "message": f"workdir がディレクトリではない: {relative_to_root(root, cwd)}"}

    command = f"{PI_COMMAND} --print {prompt}"
    timeout = float(getattr(config, "shell_timeout_seconds", 120) or 120)
    started = time.monotonic()
    try:
        proc = await asyncio.create_subprocess_exec(
            PI_COMMAND,
            "--print",
            prompt,
            cwd=str(cwd),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            start_new_session=True,
        )
    except FileNotFoundError:
        return {"status": "error", "message": f"{PI_COMMAND} が見つからない。PATH を確認すること。"}
    except OSError as e:
        return {"status": "error", "message": f"{PI_COMMAND} を起動できなかった: {e}"}

    out_b, err_b, timed_out = await _communicate_with_timeout(proc, timeout)
    duration_ms = int((time.monotonic() - started) * 1000)

    stdout = out_b.decode("utf-8", "replace")
    stderr = err_b.decode("utf-8", "replace")
    stdout_tail, stdout_cut = _tail(stdout, TAIL_LINES)
    stderr_tail, stderr_cut = _tail(stderr, TAIL_LINES)

    result: dict = {
        "status": "timeout" if timed_out else "ok",
        "exit_code": proc.returncode,
        "stdout": stdout_tail,
        "stderr": stderr_tail,
        "truncated": stdout_cut or stderr_cut,
        "duration_ms": duration_ms,
        "cwd": relative_to_root(root, cwd),
        "message": f"委譲先: {agent}",
        # registry が tool.called の payload にマージする監査情報
        "audit": {"command": command[:500], "exit_code": proc.returncode, "duration_ms": duration_ms},
    }
    if timed_out:
        result["message"] = f"委譲先 {agent} は {timeout:.0f} 秒で打ち切った（プロセスは殺した）。"
    elif stdout_cut or stderr_cut:
        result["message"] = f"委譲先 {agent}: 末尾 {TAIL_LINES} 行のみ表示。全文は log_path。"
    log_path = _save_log(ctx, command, stdout, stderr)
    if log_path:
        result["log_path"] = log_path
    return result
