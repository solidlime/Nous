"""attach_file — エージェントが作ったファイルをユーザーに渡す。"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nous.application.chat.tools.attachments import (
    _handle_attach_file,
)
from nous.domain.config.chat_config import ChatConfig


def _settings(tmp_path):
    settings = MagicMock()
    settings.persona_uploads_dir.side_effect = lambda persona: str(tmp_path / "persona" / persona / "uploads")
    return settings


@pytest.fixture
def workspace(tmp_path):
    root = tmp_path / "ws"
    root.mkdir()
    return root


@pytest.fixture
def ctx() -> Any:
    ctx = MagicMock()
    ctx.persona = "herta"
    ctx.session_id = "s1"
    return ctx


@pytest.fixture
def config(workspace) -> Any:
    config = MagicMock()
    config.workspace_root = str(workspace)
    config.sandbox_enabled = False
    config.sandbox_manager_url = ""
    config.sandbox_manager_token = ""
    config.max_attachment_bytes = ChatConfig().max_attachment_bytes
    return config


def _patch_settings(tmp_path):
    return patch(
        "nous.application.chat.tools.attachments.get_settings",
        return_value=_settings(tmp_path),
    )


class TestHostCopy:
    @pytest.mark.asyncio
    async def test_dotted_name_still_serves(self, tmp_path, workspace, ctx, config):
        """``a..b.txt`` は配信ルートのサニタイズで 404 になるので、置く前に揃える。"""
        (workspace / "a..b.txt").write_text("x", encoding="utf-8")
        with _patch_settings(tmp_path):
            result = await _handle_attach_file(ctx, config, {"path": "a..b.txt"})

        assert result["status"] == "ok"
        assert result["attachments"][0]["filename"] == "ab.txt"
        assert result["attachments"][0]["url"].endswith("/ab.txt")

    @pytest.mark.asyncio
    async def test_copies_into_uploads(self, tmp_path, workspace, ctx, config):
        (workspace / "report.md").write_text("# hi", encoding="utf-8")
        with _patch_settings(tmp_path):
            result = await _handle_attach_file(ctx, config, {"path": "report.md", "caption": "まとめ"})

        assert result["status"] == "ok"
        att = result["attachments"][0]
        assert att["filename"] == "report.md"
        assert att["url"] == "/api/chat/herta/attachment/report.md"
        assert att["mime_type"] == "text/markdown"
        assert att["size"] == 4
        assert att["caption"] == "まとめ"
        assert (tmp_path / "persona" / "herta" / "uploads" / "report.md").read_text(encoding="utf-8") == "# hi"

    @pytest.mark.asyncio
    async def test_name_override(self, tmp_path, workspace, ctx, config):
        (workspace / "tmp123.txt").write_text("x", encoding="utf-8")
        with _patch_settings(tmp_path):
            result = await _handle_attach_file(ctx, config, {"path": "tmp123.txt", "name": "結果.txt"})

        assert result["status"] == "ok"
        assert result["attachments"][0]["filename"] == "結果.txt"

    @pytest.mark.asyncio
    async def test_same_name_gets_suffix(self, tmp_path, workspace, ctx, config):
        (workspace / "a.txt").write_text("one", encoding="utf-8")
        with _patch_settings(tmp_path):
            await _handle_attach_file(ctx, config, {"path": "a.txt"})
            second = await _handle_attach_file(ctx, config, {"path": "a.txt"})

        assert second["attachments"][0]["filename"] == "a_1.txt"

    @pytest.mark.asyncio
    async def test_name_cannot_escape_uploads(self, tmp_path, workspace, ctx, config):
        (workspace / "a.txt").write_text("x", encoding="utf-8")
        with _patch_settings(tmp_path):
            result = await _handle_attach_file(ctx, config, {"path": "a.txt", "name": "../../evil.txt"})

        assert result["status"] == "ok"
        assert result["attachments"][0]["filename"] == "evil.txt"
        assert (tmp_path / "persona" / "herta" / "uploads" / "evil.txt").exists()


class TestRejects:
    @pytest.mark.asyncio
    async def test_missing_path_arg(self, tmp_path, ctx, config):
        with _patch_settings(tmp_path):
            result = await _handle_attach_file(ctx, config, {})
        assert result["status"] == "error"

    @pytest.mark.asyncio
    async def test_outside_workspace(self, tmp_path, ctx, config):
        with _patch_settings(tmp_path):
            result = await _handle_attach_file(ctx, config, {"path": "../../etc/passwd"})
        assert result["status"] == "error"
        assert "ワークスペース外" in result["message"]

    @pytest.mark.asyncio
    async def test_missing_file(self, tmp_path, ctx, config):
        with _patch_settings(tmp_path):
            result = await _handle_attach_file(ctx, config, {"path": "nope.txt"})
        assert result["status"] == "error"
        assert "ファイルが無い" in result["message"]

    @pytest.mark.asyncio
    async def test_directory_is_rejected(self, tmp_path, workspace, ctx, config):
        (workspace / "sub").mkdir()
        with _patch_settings(tmp_path):
            result = await _handle_attach_file(ctx, config, {"path": "sub"})
        assert result["status"] == "error"

    @pytest.mark.asyncio
    async def test_oversize_deletes_copy(self, tmp_path, workspace, ctx, config):
        (workspace / "big.bin").write_bytes(b"\0" * (ChatConfig().max_attachment_bytes + 1))
        with _patch_settings(tmp_path):
            result = await _handle_attach_file(ctx, config, {"path": "big.bin"})
        assert result["status"] == "error"
        assert "大きすぎる" in result["message"]
        assert not (tmp_path / "persona" / "herta" / "uploads" / "big.bin").exists()


class TestSandbox:
    def _sandbox_config(self, config):
        config.sandbox_enabled = True
        config.sandbox_manager_url = "http://sandbox:8090"
        config.sandbox_manager_token = "t"
        return config

    @pytest.mark.asyncio
    async def test_copies_inside_container(self, tmp_path, ctx, config, workspace):
        """sandbox 稼働中はコンテナ内でサイズ検査 + cp し、ホストの uploads を配信元にする。"""
        uploads = tmp_path / "persona" / "herta" / "uploads"

        async def fake_exec(persona, command, cwd=None, timeout_seconds=None):
            # cp の代わりに uploads 側へ書き出す（ホストからも見えるマウントの再現）
            assert "readlink -f" in command
            assert 'case "$src" in /home/agent/workspace/?*)' in command
            assert "stat -c %s" in command
            assert "/home/agent/uploads/.part-" in command
            uploads.mkdir(parents=True, exist_ok=True)
            (uploads / "out.png").write_bytes(b"png")
            return {"status": "success", "exit_code": 0, "stdout_tail": "", "stderr_tail": ""}

        manager = MagicMock()
        manager.exec = AsyncMock(side_effect=fake_exec)
        with (
            _patch_settings(tmp_path),
            patch("nous.application.chat.tools.attachments.sandbox_manager", return_value=manager),
        ):
            result = await _handle_attach_file(ctx, self._sandbox_config(config), {"path": "out.png"})

        assert result["status"] == "ok"
        assert result["attachments"][0]["filename"] == "out.png"
        assert result["attachments"][0]["size"] == 3

    @pytest.mark.asyncio
    @pytest.mark.parametrize("path", ["/etc/passwd", "../../etc/passwd", "/home/agent/uploads/x.txt"])
    async def test_outside_workspace_is_rejected(self, tmp_path, ctx, config, path):
        """コンテナ内でもワークスペース配下しか触らない（cp すら呼ばない）。"""
        manager = MagicMock()
        manager.exec = AsyncMock()
        with (
            _patch_settings(tmp_path),
            patch("nous.application.chat.tools.attachments.sandbox_manager", return_value=manager),
        ):
            result = await _handle_attach_file(ctx, self._sandbox_config(config), {"path": path})

        assert result["status"] == "error"
        assert "ワークスペース外" in result["message"]
        manager.exec.assert_not_called()

    @pytest.mark.asyncio
    async def test_too_big_in_container(self, tmp_path, ctx, config):
        manager = MagicMock()
        manager.exec = AsyncMock(return_value={"status": "success", "exit_code": 2, "stderr_tail": ""})
        with (
            _patch_settings(tmp_path),
            patch("nous.application.chat.tools.attachments.sandbox_manager", return_value=manager),
        ):
            result = await _handle_attach_file(ctx, self._sandbox_config(config), {"path": "big.bin"})

        assert result["status"] == "error"
        assert "大きすぎる" in result["message"]

    @pytest.mark.asyncio
    async def test_symlink_escape_in_container_is_rejected(self, tmp_path, ctx, config):
        """パス文字列が内側でも、実体が外ならコンテナ側の case 文で落ちる（exit 3）。"""
        manager = MagicMock()
        manager.exec = AsyncMock(return_value={"status": "success", "exit_code": 3, "stderr_tail": ""})
        with (
            _patch_settings(tmp_path),
            patch("nous.application.chat.tools.attachments.sandbox_manager", return_value=manager),
        ):
            result = await _handle_attach_file(ctx, self._sandbox_config(config), {"path": "ln"})

        assert result["status"] == "error"
        assert "ワークスペース外" in result["message"]

    @pytest.mark.asyncio
    async def test_transport_error_uses_stderr_tail(self, tmp_path, ctx, config):
        """manager の失敗 payload は exit_code が None で理由が stderr_tail に入る。"""
        manager = MagicMock()
        manager.exec = AsyncMock(
            return_value={
                "status": "error",
                "exit_code": None,
                "stdout_tail": "",
                "stderr_tail": "sandbox-manager: unreachable",
            }
        )
        with (
            _patch_settings(tmp_path),
            patch("nous.application.chat.tools.attachments.sandbox_manager", return_value=manager),
        ):
            result = await _handle_attach_file(ctx, self._sandbox_config(config), {"path": "out.png"})

        assert result["status"] == "error"
        assert "unreachable" in result["message"]

    @pytest.mark.asyncio
    async def test_sandbox_cp_failure_is_reported(self, tmp_path, ctx, config):
        manager = MagicMock()
        manager.exec = AsyncMock(
            return_value={"status": "success", "exit_code": 1, "stderr_tail": "cp: No such file or directory\n"}
        )
        with (
            _patch_settings(tmp_path),
            patch("nous.application.chat.tools.attachments.sandbox_manager", return_value=manager),
        ):
            result = await _handle_attach_file(ctx, self._sandbox_config(config), {"path": "gone.txt"})

        assert result["status"] == "error"
        assert "cp: No such file" in result["message"]
