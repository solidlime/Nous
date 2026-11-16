"""ワークスペースツール — bash / read_file / write_file / edit_file。

コンテキスト衛生の要: bash の出力は末尾 :data:`TAIL_LINES` 行だけ返し、
全文は artifact に落として ``read_file`` で読み直させる。巨大ログを会話履歴に
焼き付けない。
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import signal
import time
from typing import TYPE_CHECKING

from nous.application.chat.tools.workspace import (
    WorkspaceError,
    artifact_path,
    relative_to_root,
    resolve_in_workspace,
    workspace_root,
)
from nous.infrastructure.logging.structured import get_logger

if TYPE_CHECKING:
    from nous.application.use_cases import AppContext
    from nous.domain.chat_config import ChatConfig

logger = get_logger(__name__)

TAIL_LINES = 120
READ_MAX_LINES = 2000
READ_MAX_BYTES = 50_000
READ_HARD_LIMIT_BYTES = 2_000_000
ARTIFACT_MAX_BYTES = 256_000
MAX_TIMEOUT_SECONDS = 600.0


def _as_int(raw: object, default: int) -> int:
    if isinstance(raw, (int, float, str)) and not isinstance(raw, bool):
        try:
            return int(raw)
        except (TypeError, ValueError):
            return default
    return default


def _coerce_timeout(raw: object, config: ChatConfig) -> float:
    fallback = getattr(config, "shell_timeout_seconds", 120)
    value = _as_int(raw, int(fallback)) if raw is not None else int(fallback)
    return max(1.0, min(float(value), MAX_TIMEOUT_SECONDS))


def _tail(text: str, limit: int) -> tuple[str, bool]:
    lines = text.splitlines()
    if len(lines) <= limit:
        return text, False
    return "\n".join(lines[-limit:]), True


def _kill_tree(proc: asyncio.subprocess.Process) -> None:
    if proc.returncode is not None:
        return
    try:
        if os.name == "posix":
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        else:
            proc.kill()
    except (ProcessLookupError, PermissionError, OSError):
        # プロセスグループを殺せんでも、子だけは落とす
        with contextlib.suppress(ProcessLookupError, PermissionError, OSError):
            proc.kill()


def _save_log(ctx: AppContext, command: str, stdout: str, stderr: str) -> str | None:
    """全文を artifact に落とす。失敗してもツール自体は成功させる。"""
    try:
        path = artifact_path(ctx.persona, getattr(ctx, "session_id", None), "bash")
    except OSError:
        logger.warning("artifact path creation failed", exc_info=True)
        return None
    body = f"$ {command}\n\n[stdout]\n{stdout}\n\n[stderr]\n{stderr}\n"
    try:
        path.write_text(body[:ARTIFACT_MAX_BYTES], encoding="utf-8")
    except OSError:
        logger.warning("artifact write failed: %s", path, exc_info=True)
        return None
    return str(path)


async def _handle_bash(ctx: AppContext, config: ChatConfig, tool_input: dict) -> dict:
    try:
        root = workspace_root(config)
    except WorkspaceError as e:
        return {"status": "error", "message": str(e)}

    command = str(tool_input.get("command") or "").strip()
    if not command:
        return {"status": "error", "message": "command が空"}

    timeout = _coerce_timeout(tool_input.get("timeout_seconds"), config)
    started = time.monotonic()
    proc = await asyncio.create_subprocess_shell(
        command,
        cwd=str(root),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        start_new_session=True,
    )
    timed_out = False
    try:
        out_b, err_b = await asyncio.wait_for(proc.communicate(), timeout)
    except TimeoutError:
        timed_out = True
        _kill_tree(proc)
        try:
            out_b, err_b = await asyncio.wait_for(proc.communicate(), 5)
        except TimeoutError:
            out_b, err_b = b"", b""
    duration_ms = int((time.monotonic() - started) * 1000)

    stdout = out_b.decode("utf-8", "replace")
    stderr = err_b.decode("utf-8", "replace")
    stdout_tail, stdout_cut = _tail(stdout, TAIL_LINES)
    stderr_tail, stderr_cut = _tail(stderr, TAIL_LINES)

    result: dict = {
        "status": "ok",
        "exit_code": proc.returncode,
        "stdout": stdout_tail,
        "stderr": stderr_tail,
        "truncated": stdout_cut or stderr_cut,
        "duration_ms": duration_ms,
        "cwd": relative_to_root(root, root),
        # registry が tool.called の payload にマージする監査情報
        "audit": {"command": command[:500], "exit_code": proc.returncode, "duration_ms": duration_ms},
    }
    if timed_out:
        result["timed_out"] = True
        result["note"] = f"{timeout:.0f} 秒で打ち切った（プロセスは殺した）"
    if stdout_cut or stderr_cut:
        result["note"] = f"末尾 {TAIL_LINES} 行のみ表示。全文は log_path。"
    log_path = _save_log(ctx, command, stdout, stderr)
    if log_path:
        result["log_path"] = log_path
    return result


async def _handle_read_file(ctx: AppContext, config: ChatConfig, tool_input: dict) -> dict:
    try:
        root = workspace_root(config)
        target = resolve_in_workspace(root, tool_input.get("path"))
    except WorkspaceError as e:
        return {"status": "error", "message": str(e)}

    rel = relative_to_root(root, target)
    if not target.is_file():
        return {"status": "error", "message": f"ファイルではない: {rel}"}
    size = target.stat().st_size
    if size > READ_HARD_LIMIT_BYTES:
        return {
            "status": "error",
            "message": f"大きすぎる ({size} bytes): {rel}。bash で head/tail/grep すること",
        }
    try:
        text = target.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return {"status": "error", "message": f"テキストファイルではない: {rel}"}

    lines = text.splitlines()
    offset = max(0, _as_int(tool_input.get("offset"), 0))
    limit = max(1, min(_as_int(tool_input.get("limit"), READ_MAX_LINES), READ_MAX_LINES))
    chunk = "\n".join(lines[offset : offset + limit])[:READ_MAX_BYTES]
    truncated = offset + limit < len(lines)

    result: dict = {
        "status": "ok",
        "path": rel,
        "content": chunk,
        "total_lines": len(lines),
        "offset": offset,
    }
    if truncated:
        result["next_offset"] = offset + limit
    return result


async def _handle_write_file(ctx: AppContext, config: ChatConfig, tool_input: dict) -> dict:
    try:
        root = workspace_root(config)
        target = resolve_in_workspace(root, tool_input.get("path"))
    except WorkspaceError as e:
        return {"status": "error", "message": str(e)}

    content = tool_input.get("content")
    if not isinstance(content, str):
        return {"status": "error", "message": "content は文字列で必須"}
    if target.exists() and target.is_dir():
        return {"status": "error", "message": f"ディレクトリには書けない: {relative_to_root(root, target)}"}
    target.parent.mkdir(parents=True, exist_ok=True)
    data = content.encode("utf-8")
    target.write_bytes(data)
    return {
        "status": "ok",
        "path": relative_to_root(root, target),
        "bytes": len(data),
        "created": True,
    }


async def _handle_edit_file(ctx: AppContext, config: ChatConfig, tool_input: dict) -> dict:
    try:
        root = workspace_root(config)
        target = resolve_in_workspace(root, tool_input.get("path"))
    except WorkspaceError as e:
        return {"status": "error", "message": str(e)}

    old = tool_input.get("old_text")
    new = tool_input.get("new_text")
    if not isinstance(old, str) or not old:
        return {"status": "error", "message": "old_text は非空文字列で必須"}
    if not isinstance(new, str):
        return {"status": "error", "message": "new_text は文字列で必須（削除なら空文字）"}
    rel = relative_to_root(root, target)
    if not target.is_file():
        return {"status": "error", "message": f"ファイルが無い: {rel}"}
    try:
        text = target.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return {"status": "error", "message": f"テキストファイルではない: {rel}"}

    occurrences = text.count(old)
    if occurrences == 0:
        return {"status": "error", "message": f"old_text が見つからない: {rel}。read_file で現物を確認すること"}
    if occurrences > 1:
        return {
            "status": "error",
            "message": f"old_text が {occurrences} 箇所に一致: {rel}。前後を広げて一意にすること",
        }
    target.write_text(text.replace(old, new, 1), encoding="utf-8")
    return {"status": "ok", "path": rel, "replaced": 1}
