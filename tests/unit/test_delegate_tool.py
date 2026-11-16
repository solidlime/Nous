"""delegate ツール — workspace 未設定 / argv 組み立て / workdir 境界 / pi 不在。"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from nous.application.chat.tools import delegate as delegate_mod
from nous.application.chat.tools import workspace as workspace_mod
from nous.application.chat.tools.delegate import _handle_delegate
from nous.domain.chat_config import ChatConfig


class _FakeProc:
    def __init__(self, stdout: bytes = b"done\n", stderr: bytes = b"", returncode: int = 0):
        self._stdout = stdout
        self._stderr = stderr
        self.returncode = returncode

    async def communicate(self) -> tuple[bytes, bytes]:
        return self._stdout, self._stderr


@pytest.fixture
def root(tmp_path, monkeypatch):
    ws = tmp_path / "ws"
    ws.mkdir()
    fake_settings = SimpleNamespace(persona_path=lambda persona: str(tmp_path / "persona" / persona))
    monkeypatch.setattr(workspace_mod, "get_settings", lambda: fake_settings)
    return ws


@pytest.fixture
def ctx():
    c = MagicMock()
    c.persona = "test_persona"
    c.session_id = "session-1"
    return c


def _capture(monkeypatch, calls: list, proc: _FakeProc):
    async def fake_exec(*argv, **kwargs):
        calls.append((argv, kwargs))
        return proc

    monkeypatch.setattr(delegate_mod.asyncio, "create_subprocess_exec", fake_exec)


async def test_errors_when_workspace_root_unset(ctx):
    result = await _handle_delegate(ctx, ChatConfig(persona="p"), {"prompt": "do it"})
    assert result["status"] == "error"
    assert "workspace_root" in result["message"]


async def test_runs_pi_with_prompt_in_argv(root, ctx, monkeypatch):
    calls: list = []
    _capture(monkeypatch, calls, _FakeProc(stdout=b"ok 1\nok 2\n"))
    config = ChatConfig(persona="p", workspace_root=str(root), shell_timeout_seconds=10)

    result = await _handle_delegate(ctx, config, {"prompt": "fix $HOME && ls", "agent": "kaan"})

    assert result["status"] == "ok"
    argv, kwargs = calls[0]
    assert argv == ("pi", "--print", "fix $HOME && ls")
    assert kwargs["cwd"] == str(root)
    assert result["stdout"] == "ok 1\nok 2\n"
    assert "kaan" in result["message"]
    assert result["log_path"]


async def test_rejects_workdir_outside_workspace(root, ctx, monkeypatch):
    calls: list = []
    _capture(monkeypatch, calls, _FakeProc())
    config = ChatConfig(persona="p", workspace_root=str(root))

    result = await _handle_delegate(ctx, config, {"prompt": "x", "workdir": "../outside"})

    assert result["status"] == "error"
    assert calls == []


async def test_reports_missing_pi(root, ctx, monkeypatch):
    async def fake_exec(*argv, **kwargs):
        raise FileNotFoundError("pi")

    monkeypatch.setattr(delegate_mod.asyncio, "create_subprocess_exec", fake_exec)
    config = ChatConfig(persona="p", workspace_root=str(root))

    result = await _handle_delegate(ctx, config, {"prompt": "x"})

    assert result["status"] == "error"
    assert "pi" in result["message"]
