"""sandbox ツール（manager 経由の隔離コンテナ exec）のテスト。"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import httpx
import pytest

from nous.application.chat.tools.approval import approval_required
from nous.application.chat.tools.definitions import SANDBOX_TOOL, get_filtered_tools
from nous.application.chat.tools.sandbox import TOKEN_HEADER, handle_sandbox, sandbox_settings
from nous.domain.chat_config import ChatConfig

_URL = "http://sandbox-manager:8080"
TOKEN = "test-token"


class TestEnvFallback:
    """compose スタックだけで sandbox を有効にできること（config.json を触らせない）。"""

    def test_env_supplies_enabled_url_and_token(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("NOUS_SANDBOX_ENABLED", "true")
        monkeypatch.setenv("NOUS_SANDBOX_MANAGER_URL", "http://manager:8080/")
        monkeypatch.setenv("NOUS_SANDBOX_MANAGER_TOKEN", "tok")
        assert sandbox_settings(ChatConfig()) == (True, "http://manager:8080", "tok")

    def test_config_wins_over_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("NOUS_SANDBOX_MANAGER_URL", "http://env:8080")
        monkeypatch.setenv("NOUS_SANDBOX_MANAGER_TOKEN", "envtok")
        config = ChatConfig(sandbox_manager_url="http://cfg:1", sandbox_manager_token="cfgtok")
        assert sandbox_settings(config)[1:] == ("http://cfg:1", "cfgtok")


def _response(status_code: int = 200, payload: dict | None = None) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = payload if payload is not None else {}
    return resp


def _client_factory(*, response: MagicMock | None = None, exc: Exception | None = None, captured: dict | None = None):
    class FakeClient:
        def __init__(self, **kwargs: object) -> None:
            if captured is not None:
                captured["timeout"] = kwargs.get("timeout")

        async def __aenter__(self) -> FakeClient:
            return self

        async def __aexit__(self, *exc_info: object) -> bool:
            return False

        async def post(self, url: str, json: dict | None = None, **kwargs: Any) -> MagicMock:  # noqa: A002
            if captured is not None:
                captured["url"] = url
                captured["body"] = json
                captured["headers"] = kwargs.get("headers")
            if exc is not None:
                raise exc
            assert response is not None
            return response

    return FakeClient


@pytest.fixture
def ctx() -> MagicMock:
    mock = MagicMock()
    mock.persona = "test_persona"
    return mock


@pytest.fixture
def config() -> ChatConfig:
    return ChatConfig(sandbox_manager_url=_URL, sandbox_manager_token=TOKEN, shell_timeout_seconds=30)


async def _run(ctx: MagicMock, config: ChatConfig, tool_input: dict, **client_kwargs: Any) -> dict:
    factory = _client_factory(**client_kwargs)
    with patch("nous.application.chat.tools.sandbox.httpx.AsyncClient", factory):
        return await handle_sandbox(ctx, config, tool_input)


class TestSandboxHandler:
    async def test_missing_manager_url(self, ctx: MagicMock) -> None:
        result = await handle_sandbox(ctx, ChatConfig(), {"command": "ls"})
        assert result["status"] == "error"
        assert "sandbox_manager_url" in result["error"]

    async def test_missing_persona(self, config: ChatConfig) -> None:
        ctx = MagicMock()
        ctx.persona = ""
        result = await handle_sandbox(ctx, config, {"command": "ls"})
        assert result["status"] == "error"
        assert "persona" in result["error"]

    async def test_missing_command(self, ctx: MagicMock, config: ChatConfig) -> None:
        result = await handle_sandbox(ctx, config, {})
        assert result["status"] == "error"

    async def test_exec_posts_persona_and_command(self, ctx: MagicMock, config: ChatConfig) -> None:
        payload = {
            "status": "ok",
            "exit_code": 0,
            "stdout_tail": "hi\n",
            "stderr_tail": "",
            "truncated": False,
            "log_path": "/var/log/sandbox/x.log",
        }
        captured: dict = {}
        result = await _run(
            ctx, config, {"command": "echo hi", "cwd": "/work"}, response=_response(200, payload), captured=captured
        )
        assert captured["url"] == f"{_URL}/exec"
        assert captured["body"] == {
            "persona": "test_persona",
            "command": "echo hi",
            "cwd": "/work",
            "timeout_seconds": 30.0,
        }
        assert captured["timeout"] == 40.0
        assert captured["headers"] == {TOKEN_HEADER: TOKEN}
        assert result == payload

    async def test_configured_options_are_forwarded(self, ctx: MagicMock) -> None:
        config = ChatConfig(
            sandbox_manager_url=_URL,
            sandbox_manager_token=TOKEN,
            shell_timeout_seconds=30,
            sandbox_image="ubuntu:22.04",
            sandbox_network="sbx-net",
            sandbox_memory="2g",
            sandbox_idle_minutes=10,
        )
        captured: dict = {}
        await _run(ctx, config, {"command": "id"}, response=_response(200, {"status": "ok"}), captured=captured)
        assert captured["body"]["image"] == "ubuntu:22.04"
        assert captured["body"]["network"] == "sbx-net"
        assert captured["body"]["memory"] == "2g"
        assert captured["body"]["idle_minutes"] == 10.0

    async def test_tail_is_capped_at_120_lines(self, ctx: MagicMock, config: ChatConfig) -> None:
        payload = {"status": "ok", "stdout_tail": "\n".join(str(i) for i in range(200))}
        result = await _run(ctx, config, {"command": "seq 200"}, response=_response(200, payload))
        assert len(result["stdout_tail"].splitlines()) == 120
        assert "stderr_tail" not in result

    async def test_missing_token_fails_closed(self, ctx: MagicMock) -> None:
        config = ChatConfig(sandbox_manager_url=_URL, shell_timeout_seconds=30)
        result = await _run(ctx, config, {"command": "ls"}, response=_response(200, {"status": "ok"}))
        assert result["status"] == "error"
        assert "sandbox_manager_token" in result["error"]

    async def test_connect_error_returns_error(self, ctx: MagicMock, config: ChatConfig) -> None:
        result = await _run(ctx, config, {"command": "ls"}, exc=httpx.ConnectError("boom"))
        assert result["status"] == "error"
        assert "sandbox-manager" in result["error"]

    async def test_non_200_returns_error(self, ctx: MagicMock, config: ChatConfig) -> None:
        result = await _run(ctx, config, {"command": "ls"}, response=_response(500, {"detail": "x"}))
        assert result["status"] == "error"
        assert "500" in result["error"]


class TestSandboxWiring:
    def test_tool_defined(self) -> None:
        assert SANDBOX_TOOL.name == "sandbox"
        assert SANDBOX_TOOL.input_schema["required"] == ["command"]

    def test_listed_without_workspace_root(self) -> None:
        config = ChatConfig(sandbox_enabled=True, sandbox_manager_url=_URL, workspace_root="")
        names = [t.name for t in get_filtered_tools(config)]
        assert "sandbox" in names

    def test_not_listed_without_manager_url(self) -> None:
        config = ChatConfig(sandbox_enabled=True, workspace_root="/tmp")
        names = [t.name for t in get_filtered_tools(config)]
        assert "sandbox" not in names

    def test_not_listed_when_disabled(self) -> None:
        config = ChatConfig(sandbox_enabled=False, sandbox_manager_url=_URL)
        names = [t.name for t in get_filtered_tools(config)]
        assert "sandbox" not in names

    def test_disabled_tools_still_filters(self) -> None:
        config = ChatConfig(sandbox_enabled=True, sandbox_manager_url=_URL, disabled_tools=["sandbox"])
        names = [t.name for t in get_filtered_tools(config)]
        assert "sandbox" not in names

    def test_approval_required_in_ask_mode(self) -> None:
        config = ChatConfig(sandbox_manager_url=_URL, shell_approval_mode="ask")
        assert approval_required(config, "sandbox", {"command": "ls"}) is True
