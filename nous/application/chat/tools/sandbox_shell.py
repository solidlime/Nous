"""sandbox を既定のシェルにする — ワークスペースツールの sandbox 版。

manager の ``/exec`` だけを使う（コンテナに python/perl を要求しない）。
引数の形・出力の形（``_tail``・行数上限・エラー時の status）は ``shell.py`` の
ローカル版に揃え、モデルから見たインターフェースを変えない。
"""

from __future__ import annotations

import base64
import binascii
import posixpath
import shlex
from typing import TYPE_CHECKING, Any

import httpx

from nous.application.chat.tools.sandbox import (
    TIMEOUT_GRACE_SECONDS,
    TOKEN_HEADER,
    _exec_body,
    sandbox_settings,
)
from nous.application.chat.tools.shell import (
    READ_HARD_LIMIT_BYTES,
    READ_MAX_BYTES,
    READ_MAX_LINES,
    TAIL_LINES,
    _as_int,
    _coerce_timeout,
    _tail,
)
from nous.application.chat.tools.workspace import WorkspaceError

if TYPE_CHECKING:
    from nous.domain.config.chat_config import ChatConfig


def workspace_path(persona: str) -> str:
    """コンテナ内のワークスペース（manager のマウント先）。

    ペルソナごとに分かれるのはホスト側で、コンテナ内の HOME は共通
    （/home/agent）。sandbox はペルソナ専用の使い捨てコンテナ。
    """
    del persona  # 呼び出し側の互換のため引数は残す
    return "/home/agent/workspace"


class SandboxManager:
    """manager の ``/exec`` を叩くハンドル。テストは :meth:`exec` を差し替えるだけでよい。"""

    def __init__(self, config: ChatConfig) -> None:
        self.config = config

    async def exec(
        self,
        persona: str,
        command: str,
        cwd: str | None = None,
        timeout_seconds: object = None,
    ) -> dict:
        _enabled, url, token = sandbox_settings(self.config)
        if not url:
            return {"status": "error", "message": "sandbox_manager_url is not configured"}
        if not token:
            return {"status": "error", "message": "sandbox_manager_token is not configured"}
        body = _exec_body(self.config, persona, command, cwd)
        timeout = (
            _coerce_timeout(timeout_seconds, self.config)
            if timeout_seconds is not None
            else float(getattr(self.config, "shell_timeout_seconds", 120))
        )
        if timeout_seconds is not None:
            body["timeout_seconds"] = timeout
        try:
            async with httpx.AsyncClient(timeout=timeout + TIMEOUT_GRACE_SECONDS) as client:
                response = await client.post(f"{url}/exec", json=body, headers={TOKEN_HEADER: token})
                if response.status_code != 200:
                    detail = response.text[:500]
                    return {
                        "status": "error",
                        "message": f"sandbox-manager: HTTP {response.status_code} {detail}".strip(),
                    }
                payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            return {"status": "error", "message": f"sandbox-manager: {exc}"}
        if not isinstance(payload, dict):
            return {"status": "error", "message": "sandbox-manager: invalid response"}
        return payload


def sandbox_manager(config: ChatConfig) -> SandboxManager | None:
    """sandbox が使える設定ならハンドル、使えないなら None（ローカル版に任せる）。"""
    enabled, url, _token = sandbox_settings(config)
    return SandboxManager(config) if enabled and url else None


def resolve_path(persona: str, raw: object) -> str:
    """相対はワークスペース起点、絶対はそのまま。``..`` は正規化するだけで拒否しない。"""
    text = str(raw or "").strip()
    if not text:
        raise WorkspaceError("path が空")
    if text.startswith("/"):
        return posixpath.normpath(text)
    return posixpath.normpath(posixpath.join(workspace_path(persona), text))


def _display(persona: str, target: str) -> str:
    root = workspace_path(persona)
    return target[len(root) + 1 :] if target.startswith(root + "/") else target


def _transport_error(payload: dict) -> dict | None:
    """manager 不達なら error 結果、届いていれば None。"""
    if "exit_code" in payload:
        return None
    return {"status": "error", "message": payload.get("message") or payload.get("error") or "sandbox-manager: failure"}


async def run_bash(
    manager: Any,
    persona: str,
    command: object,
    cwd: str | None = None,
    timeout_seconds: object = None,
) -> dict:
    text = str(command or "").strip()
    if not text:
        return {"status": "error", "message": "command が空"}
    workdir = cwd or workspace_path(persona)
    payload = await manager.exec(persona, text, workdir, timeout_seconds)
    if (failed := _transport_error(payload)) is not None:
        return failed

    stdout, cut_out = _tail(payload.get("stdout_tail") or "", TAIL_LINES)
    stderr, cut_err = _tail(payload.get("stderr_tail") or "", TAIL_LINES)
    exit_code = payload.get("exit_code")
    truncated = bool(payload.get("truncated")) or cut_out or cut_err
    result: dict = {
        "status": "ok",
        "exit_code": exit_code,
        "stdout": stdout,
        "stderr": stderr,
        "truncated": truncated,
        "cwd": workdir,
        "audit": {"command": text[:500], "exit_code": exit_code},
    }
    if truncated:
        result["note"] = f"末尾 {TAIL_LINES} 行のみ表示。全文は log_path。"
    if payload.get("log_path"):
        result["log_path"] = payload["log_path"]
    return result


async def _read_text(manager: Any, persona: str, target: str) -> tuple[str | None, dict | None]:
    """base64 で読んで nous 側でデコードする。(text, error) を返す。"""
    rel = _display(persona, target)
    payload = await manager.exec(persona, f"base64 -w0 -- {shlex.quote(target)}", None)
    if (failed := _transport_error(payload)) is not None:
        return None, failed
    if payload.get("exit_code") != 0:
        err = (payload.get("stderr_tail") or "").strip() or "読み取りに失敗"
        low = err.lower()
        if "no such file" in low or "directory" in low or "not a regular file" in low:
            return None, {"status": "error", "message": f"ファイルではない: {rel}"}
        return None, {"status": "error", "message": f"read_file: {err}"}
    raw = payload.get("stdout_tail") or ""
    try:
        data = base64.b64decode(raw)
    except (binascii.Error, ValueError) as exc:
        return None, {"status": "error", "message": f"base64 のデコードに失敗: {exc}"}
    # shortcut: サイズ上限は転送後に見る（2MB 程度なら本体で吸える）。巨大化したら wc -c を先に撃つ
    if len(data) > READ_HARD_LIMIT_BYTES:
        return None, {
            "status": "error",
            "message": f"大きすぎる ({len(data)} bytes): {rel}。bash で head/tail/grep すること",
        }
    try:
        return data.decode("utf-8"), None
    except UnicodeDecodeError:
        return None, {"status": "error", "message": f"テキストファイルではない: {rel}"}


async def _write_text(manager: Any, persona: str, target: str, content: str) -> dict | None:
    """base64 にしてから書き込む（シェルクォート事故を避ける）。成功なら None。"""
    rel = _display(persona, target)
    encoded = base64.b64encode(content.encode("utf-8")).decode("ascii")
    command = (
        f"mkdir -p -- {shlex.quote(posixpath.dirname(target) or '/')} && "
        f"printf %s {encoded} | base64 -d > {shlex.quote(target)}"
    )
    payload = await manager.exec(persona, command, None)
    if (failed := _transport_error(payload)) is not None:
        return failed
    if payload.get("exit_code") != 0:
        err = (payload.get("stderr_tail") or "").strip() or "書き込みに失敗"
        if "directory" in err.lower():
            return {"status": "error", "message": f"ディレクトリには書けない: {rel}"}
        return {"status": "error", "message": f"write_file: {err}"}
    return None


async def read_file(
    manager: Any,
    persona: str,
    path: object,
    offset: object = None,
    limit: object = None,
) -> dict:
    try:
        target = resolve_path(persona, path)
    except WorkspaceError as exc:
        return {"status": "error", "message": str(exc)}
    rel = _display(persona, target)
    text, error = await _read_text(manager, persona, target)
    if error is not None:
        return error
    assert text is not None

    lines = text.splitlines()
    start = max(0, _as_int(offset, 0))
    count = max(1, min(_as_int(limit, READ_MAX_LINES), READ_MAX_LINES))
    chunk = "\n".join(lines[start : start + count])[:READ_MAX_BYTES]
    result: dict = {
        "status": "ok",
        "path": rel,
        "content": chunk,
        "total_lines": len(lines),
        "offset": start,
    }
    if start + count < len(lines):
        result["next_offset"] = start + count
    return result


async def write_file(manager: Any, persona: str, path: object, content: object) -> dict:
    try:
        target = resolve_path(persona, path)
    except WorkspaceError as exc:
        return {"status": "error", "message": str(exc)}
    if not isinstance(content, str):
        return {"status": "error", "message": "content は文字列で必須"}
    error = await _write_text(manager, persona, target, content)
    if error is not None:
        return error
    return {
        "status": "ok",
        "path": _display(persona, target),
        "bytes": len(content.encode("utf-8")),
        "created": True,
    }


async def edit_file(manager: Any, persona: str, path: object, old: object, new: object) -> dict:
    try:
        target = resolve_path(persona, path)
    except WorkspaceError as exc:
        return {"status": "error", "message": str(exc)}
    if not isinstance(old, str) or not old:
        return {"status": "error", "message": "old_text は非空文字列で必須"}
    if not isinstance(new, str):
        return {"status": "error", "message": "new_text は文字列で必須（削除なら空文字）"}

    rel = _display(persona, target)
    text, error = await _read_text(manager, persona, target)
    if error is not None:
        if str(error.get("message") or "").startswith("ファイルではない"):
            return {"status": "error", "message": f"ファイルが無い: {rel}"}
        return error
    assert text is not None

    occurrences = text.count(old)
    if occurrences == 0:
        return {"status": "error", "message": f"old_text が見つからない: {rel}。read_file で現物を確認すること"}
    if occurrences > 1:
        return {
            "status": "error",
            "message": f"old_text が {occurrences} 箇所に一致: {rel}。前後を広げて一意にすること",
        }
    error = await _write_text(manager, persona, target, text.replace(old, new, 1))
    if error is not None:
        return error
    return {"status": "ok", "path": rel, "replaced": 1}


async def run_tool(name: str, manager: Any, persona: str, tool_input: dict) -> dict:
    """ツール名 → sandbox 版ハンドラ。tool_input はモデルが送ってきた引数そのまま。"""
    if name == "bash":
        return await run_bash(manager, persona, tool_input.get("command"), None, tool_input.get("timeout_seconds"))
    if name == "read_file":
        return await read_file(
            manager, persona, tool_input.get("path"), tool_input.get("offset"), tool_input.get("limit")
        )
    if name == "write_file":
        return await write_file(manager, persona, tool_input.get("path"), tool_input.get("content"))
    if name == "edit_file":
        return await edit_file(
            manager, persona, tool_input.get("path"), tool_input.get("old_text"), tool_input.get("new_text")
        )
    return {"status": "error", "message": f"Unknown tool: {name}"}
