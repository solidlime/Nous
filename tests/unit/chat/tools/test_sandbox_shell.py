"""sandbox 既定シェル（workplace tools の sandbox 版）のテスト。"""

from __future__ import annotations

import base64
from typing import Any

import httpx
import pytest

from nous.application.chat.tools.definitions import get_filtered_tools
from nous.domain.config.chat_config import ChatConfig

_URL = "http://sandbox-manager:8080"
TOKEN = "test-token"


class FakeManager:
    """manager の /exec を差し替える。呼ばれた argv を記録する。"""

    def __init__(self, *payloads: dict, missing: bool = False) -> None:
        self.payloads = list(payloads)
        self.missing = missing
        self.calls: list[dict] = []

    async def exec(self, persona: str, command: str, cwd: str | None = None, timeout_seconds: object = None) -> dict:
        self.calls.append({"persona": persona, "command": command, "cwd": cwd, "timeout_seconds": timeout_seconds})
        if self.missing:
            return {"status": "error", "message": "sandbox-manager: ConnectError"}
        return self.payloads.pop(0) if self.payloads else _ok()


def _ok(stdout: str = "", exit_code: int = 0) -> dict:
    return {"status": "ok", "exit_code": exit_code, "stdout_tail": stdout, "stderr_tail": "", "truncated": False}


@pytest.fixture
def config() -> ChatConfig:
    return ChatConfig(
        sandbox_enabled=True,
        sandbox_manager_url=_URL,
        sandbox_manager_token=TOKEN,
        shell_timeout_seconds=30,
    )


class TestBash:
    async def test_posts_command_with_workspace_cwd(self) -> None:
        from nous.application.chat.tools.sandbox_shell import run_bash

        manager = FakeManager(_ok("hi\n"))
        result = await run_bash(manager, "p1", "echo hi")
        assert manager.calls == [
            {"persona": "p1", "command": "echo hi", "cwd": "/root/workspace", "timeout_seconds": None}
        ]
        assert result["status"] == "ok"
        assert result["exit_code"] == 0
        assert result["stdout"] == "hi\n"
        assert result["cwd"] == "/root/workspace"

    async def test_empty_command_is_error(self) -> None:
        from nous.application.chat.tools.sandbox_shell import run_bash

        assert (await run_bash(FakeManager(), "p1", "  "))["status"] == "error"


class TestRead:
    async def test_decodes_base64(self) -> None:
        from nous.application.chat.tools.sandbox_shell import read_file

        body = base64.b64encode(b"a\nb\nc\n").decode()
        manager = FakeManager(_ok(body))
        result = await read_file(manager, "p1", "notes.txt")
        assert manager.calls[0]["command"] == "base64 -w0 -- /root/workspace/notes.txt"
        assert result == {"status": "ok", "path": "notes.txt", "content": "a\nb\nc", "total_lines": 3, "offset": 0}

    async def test_missing_file_message(self) -> None:
        from nous.application.chat.tools.sandbox_shell import read_file

        payload = {"status": "error", "exit_code": 1, "stdout_tail": "", "stderr_tail": "No such file or directory"}
        result = await read_file(FakeManager(payload), "p1", "nope.txt")
        assert result == {"status": "error", "message": "ファイルではない: nope.txt"}


class TestWrite:
    async def test_writes_base64_payload(self) -> None:
        from nous.application.chat.tools.sandbox_shell import write_file

        manager = FakeManager(_ok())
        result = await write_file(manager, "p1", "d/x.txt", "hello 'world'")
        b64 = base64.b64encode(b"hello 'world'").decode()
        assert manager.calls[0]["command"] == (
            f"mkdir -p -- /root/workspace/d && printf %s {b64} | base64 -d > /root/workspace/d/x.txt"
        )
        assert result == {"status": "ok", "path": "d/x.txt", "bytes": 13, "created": True}


class TestEdit:
    async def _round(self, old: str, new: str, text: str) -> tuple[dict, FakeManager]:
        from nous.application.chat.tools.sandbox_shell import edit_file

        manager = FakeManager(
            _ok(base64.b64encode(text.encode()).decode()),
            _ok(),
        )
        return await edit_file(manager, "p1", "f.txt", old, new), manager

    async def test_replaces_once_by_reading_and_writing(self) -> None:
        result, manager = await self._round("b", "B", "a\nb\nc\n")
        assert result == {"status": "ok", "path": "f.txt", "replaced": 1}
        assert len(manager.calls) == 2
        assert "B" in base64.b64decode(manager.calls[1]["command"].split("printf %s ")[1].split(" |")[0]).decode()

    async def test_zero_occurrences_is_error(self) -> None:
        result, manager = await self._round("zzz", "x", "a\nb\n")
        assert result["status"] == "error"
        assert "old_text が見つからない: f.txt" in result["message"]
        assert len(manager.calls) == 1  # 書かない

    async def test_multiple_occurrences_is_error(self) -> None:
        result, _manager = await self._round("b", "x", "b\nb\n")
        assert result["status"] == "error"
        assert "2 箇所に一致: f.txt" in result["message"]


class TestTransport:
    async def test_unreachable_manager_returns_error(self) -> None:
        from nous.application.chat.tools.sandbox_shell import run_bash

        result = await run_bash(FakeManager(missing=True), "p1", "ls")
        assert result["status"] == "error"
        assert "sandbox-manager" in result["message"]

    async def test_connect_error_from_http_client(self, config: ChatConfig) -> None:
        from unittest.mock import patch

        from nous.application.chat.tools.sandbox_shell import SandboxManager

        class Boom:
            def __init__(self, **kwargs: Any) -> None:
                pass

            async def __aenter__(self) -> Boom:
                return self

            async def __aexit__(self, *exc: object) -> bool:
                return False

            async def post(self, *args: Any, **kwargs: Any) -> Any:
                raise httpx.ConnectError("boom")

        with patch("nous.application.chat.tools.sandbox_shell.httpx.AsyncClient", Boom):
            result = await SandboxManager(config).exec("p1", "ls")
        assert result["status"] == "error"
        assert "sandbox-manager" in result["message"]


class TestToolListing:
    def test_sandbox_wins_without_workspace_root(self, config: ChatConfig) -> None:
        names = {t.name for t in get_filtered_tools(config)}
        assert {"bash", "read_file", "write_file", "edit_file"} <= names
        assert "sandbox" not in names

    def test_local_wiring_unchanged_when_disabled(self) -> None:
        config = ChatConfig(sandbox_enabled=False, workspace_root="/tmp")
        names = {t.name for t in get_filtered_tools(config)}
        assert {"bash", "read_file", "write_file", "edit_file"} <= names
        assert "sandbox" not in names

    def test_nothing_listed_when_neither_is_configured(self) -> None:
        names = {t.name for t in get_filtered_tools(ChatConfig())}
        assert "bash" not in names
        assert "sandbox" not in names


class TestDispatch:
    async def test_builtin_routes_workspace_tools_to_sandbox(
        self, config: ChatConfig, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from unittest.mock import MagicMock

        from nous.application.chat.tools import builtin

        calls: list[tuple[str, str, dict]] = []

        async def fake_run_tool(name: str, manager: Any, persona: str, tool_input: dict) -> dict:
            calls.append((name, persona, tool_input))
            return {"status": "ok", "path": "x"}

        monkeypatch.setattr(builtin, "_run_sandbox_tool", fake_run_tool)
        monkeypatch.setattr(builtin, "sandbox_manager", lambda _config: object())
        ctx = MagicMock()
        ctx.persona = "p1"
        result = await builtin.execute_tool(ctx, config, "read_file", {"path": "x"})
        assert calls == [("read_file", "p1", {"path": "x"})]
        assert result == {"status": "ok", "path": "x"}


class TestEnvFallback:
    """compose スタックだけで sandbox を有効にできること（config.json を触らせない）。"""

    def test_env_supplies_enabled_url_and_token(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from nous.application.chat.tools.sandbox import sandbox_settings

        monkeypatch.setenv("NOUS_SANDBOX_ENABLED", "true")
        monkeypatch.setenv("NOUS_SANDBOX_MANAGER_URL", "http://manager:8080/")
        monkeypatch.setenv("NOUS_SANDBOX_MANAGER_TOKEN", "tok")
        assert sandbox_settings(ChatConfig()) == (True, "http://manager:8080", "tok")

    def test_url_and_token_config_wins_over_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from nous.application.chat.tools.sandbox import sandbox_settings

        monkeypatch.setenv("NOUS_SANDBOX_MANAGER_URL", "http://env:8080")
        monkeypatch.setenv("NOUS_SANDBOX_MANAGER_TOKEN", "envtok")
        config = ChatConfig(sandbox_manager_url="http://cfg:1", sandbox_manager_token="cfgtok")
        assert sandbox_settings(config)[1:] == ("http://cfg:1", "cfgtok")

    def test_env_enabled_wins_over_config(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """:27-37 の実装は enabled だけ env 優先（キルスイッチ）。docstring をこれに合わせた。"""
        from nous.application.chat.tools.sandbox import sandbox_settings

        monkeypatch.setenv("NOUS_SANDBOX_ENABLED", "false")
        assert sandbox_settings(ChatConfig(sandbox_enabled=True))[0] is False
