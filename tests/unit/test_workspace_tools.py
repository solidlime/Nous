"""ワークスペースツール（bash / read_file / write_file / edit_file）の境界と切り詰め。"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from nous.application.chat.tools import workspace as workspace_mod
from nous.application.chat.tools.definitions import get_filtered_tools
from nous.application.chat.tools.shell import (
    TAIL_LINES,
    _handle_bash,
    _handle_edit_file,
    _handle_read_file,
    _handle_write_file,
)
from nous.application.chat.tools.workspace import WorkspaceError, resolve_in_workspace
from nous.domain.chat_config import ChatConfig

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def root(tmp_path, monkeypatch):
    ws = tmp_path / "ws"
    ws.mkdir()
    # artifact は実データディレクトリではなく tmp に落とす
    fake_settings = SimpleNamespace(persona_path=lambda persona: str(tmp_path / "persona" / persona))
    monkeypatch.setattr(workspace_mod, "get_settings", lambda: fake_settings)
    return ws


@pytest.fixture
def config(root):
    return ChatConfig(persona="test_persona", workspace_root=str(root), shell_timeout_seconds=10)


@pytest.fixture
def ctx():
    c = MagicMock()
    c.persona = "test_persona"
    c.session_id = "session-1"
    c.event_bus = AsyncMock()
    return c


# ---------------------------------------------------------------------------
# 境界
# ---------------------------------------------------------------------------


class TestBoundary:
    def test_rejects_parent_escape(self, root):
        with pytest.raises(WorkspaceError):
            resolve_in_workspace(root, "../outside.txt")

    def test_rejects_absolute_outside(self, root):
        with pytest.raises(WorkspaceError):
            resolve_in_workspace(root, "/etc/passwd")

    def test_rejects_symlink_escape(self, root, tmp_path):
        secret = tmp_path / "secret.txt"
        secret.write_text("x", encoding="utf-8")
        (root / "link").symlink_to(secret)
        with pytest.raises(WorkspaceError):
            resolve_in_workspace(root, "link")

    def test_allows_nested(self, root):
        (root / "a" / "b").mkdir(parents=True)
        assert resolve_in_workspace(root, "a/b/c.txt") == root / "a" / "b" / "c.txt"

    async def test_read_file_outside_is_error(self, root, config, ctx):
        result = await _handle_read_file(ctx, config, {"path": "../../etc/passwd"})
        assert result["status"] == "error"


# ---------------------------------------------------------------------------
# read_file
# ---------------------------------------------------------------------------


class TestReadFile:
    async def test_reads_with_offset_and_reports_next(self, root, config, ctx):
        (root / "f.txt").write_text("\n".join(f"line{i}" for i in range(10)), encoding="utf-8")
        result = await _handle_read_file(ctx, config, {"path": "f.txt", "offset": 5, "limit": 3})
        assert result["status"] == "ok"
        assert result["content"] == "line5\nline6\nline7"
        assert result["total_lines"] == 10
        assert result["next_offset"] == 8

    async def test_missing_file(self, root, config, ctx):
        result = await _handle_read_file(ctx, config, {"path": "nope.txt"})
        assert result["status"] == "error"


# ---------------------------------------------------------------------------
# bash
# ---------------------------------------------------------------------------


class TestBash:
    async def test_truncates_to_tail_and_writes_artifact(self, root, config, ctx):
        script = "print('\\n'.join(f'line{i}' for i in range(1, 501)))"
        result = await _handle_bash(ctx, config, {"command": f'python3 -c "{script}"'})
        assert result["status"] == "ok"
        assert result["exit_code"] == 0
        assert result["truncated"] is True
        lines = result["stdout"].splitlines()
        assert len(lines) == TAIL_LINES
        assert lines[-1] == "line500"
        log_path = result["log_path"]
        assert log_path.endswith("-bash.log")
        artifact_log = next((root.parent / "persona" / "test_persona" / "artifacts" / "session-1").glob("*-bash.log"))
        assert "line1\n" in artifact_log.read_text(encoding="utf-8")
        assert "line500" in artifact_log.read_text(encoding="utf-8")

    async def test_exit_code_is_reported(self, root, config, ctx):
        result = await _handle_bash(ctx, config, {"command": 'python3 -c "import sys; sys.exit(3)"'})
        assert result["exit_code"] == 3
        assert result["audit"]["exit_code"] == 3

    async def test_runs_in_workspace(self, root, config, ctx):
        result = await _handle_bash(ctx, config, {"command": "pwd"})
        assert result["stdout"].strip() == str(root)

    async def test_empty_command_rejected(self, root, config, ctx):
        result = await _handle_bash(ctx, config, {"command": "  "})
        assert result["status"] == "error"


# ---------------------------------------------------------------------------
# write_file / edit_file
# ---------------------------------------------------------------------------


class TestWriteEdit:
    async def test_write_creates_parents(self, root, config, ctx):
        result = await _handle_write_file(ctx, config, {"path": "a/b/c.txt", "content": "hello"})
        assert result["status"] == "ok"
        assert (root / "a" / "b" / "c.txt").read_text(encoding="utf-8") == "hello"

    async def test_edit_requires_unique_match(self, root, config, ctx):
        (root / "dup.txt").write_text("x\nx\n", encoding="utf-8")
        result = await _handle_edit_file(ctx, config, {"path": "dup.txt", "old_text": "x", "new_text": "y"})
        assert result["status"] == "error"
        assert "2 箇所" in result["message"]

    async def test_edit_missing_text(self, root, config, ctx):
        (root / "f.txt").write_text("abc", encoding="utf-8")
        result = await _handle_edit_file(ctx, config, {"path": "f.txt", "old_text": "zzz", "new_text": "y"})
        assert result["status"] == "error"

    async def test_edit_replaces_once(self, root, config, ctx):
        (root / "f.txt").write_text("a\nb\na\n", encoding="utf-8")
        result = await _handle_edit_file(ctx, config, {"path": "f.txt", "old_text": "a\nb", "new_text": "A"})
        assert result["status"] == "ok"
        assert (root / "f.txt").read_text(encoding="utf-8") == "A\na\n"

    async def test_write_outside_is_error(self, root, config, ctx):
        result = await _handle_write_file(ctx, config, {"path": "../escape.txt", "content": "x"})
        assert result["status"] == "error"


# ---------------------------------------------------------------------------
# ツール公開条件
# ---------------------------------------------------------------------------


class TestToolExposure:
    def test_hidden_without_workspace_root(self):
        names = {t.name for t in get_filtered_tools(ChatConfig())}
        assert "bash" not in names

    def test_exposed_with_workspace_root(self, root):
        names = {t.name for t in get_filtered_tools(ChatConfig(workspace_root=str(root)))}
        assert {"bash", "read_file", "write_file", "edit_file"} <= names

    def test_disabled_tools_still_wins(self, root):
        config = ChatConfig(workspace_root=str(root), disabled_tools=["bash"])
        assert "bash" not in {t.name for t in get_filtered_tools(config)}


# ---------------------------------------------------------------------------
# 監査ログ（tool.called）
# ---------------------------------------------------------------------------


class TestAudit:
    async def test_registry_merges_audit_fields_into_event(self, root, config, ctx):
        from nous.application.chat.tools.registry import ToolRegistry

        registry = ToolRegistry([], mcp_pool=None)
        result = await registry.execute(ctx, config, "bash", {"command": "echo hi"})

        assert result["exit_code"] == 0
        event_type, payload = ctx.event_bus.publish.await_args.args
        assert event_type == "tool.called"
        assert payload["command"] == "echo hi"
        assert payload["exit_code"] == 0
        assert "duration_ms" in payload
        assert payload["success"] is True


class TestShellNotes:
    async def test_timeout_and_truncation_notes_coexist(self, root, config, ctx):
        """打ち切りとタイムアウトが同時に起きても note が片方消えない。"""
        config.shell_timeout_seconds = 1
        script = "for i in range(600): print('line%d' % i)\nimport time; time.sleep(5)"
        result = await _handle_bash(ctx, config, {"command": f'python3 -u -c "{script}"'})
        assert result.get("timed_out") is True
        assert result["truncated"] is True
        assert "秒で打ち切った" in result["note"]
        assert "末尾" in result["note"]
