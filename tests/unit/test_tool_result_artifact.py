"""切り詰め時の原文 artifact 保存（ToolRegistry.execute）。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nous.application.chat.tools.registry import ToolRegistry

BIG = {"status": "ok", "stdout": "x" * 5000}
SMALL = {"status": "ok", "stdout": "x" * 10}


def _ctx(persona: str = "test_persona") -> MagicMock:
    ctx = MagicMock()
    ctx.persona = persona
    ctx.session_id = "sess-1"
    ctx.event_bus = AsyncMock()
    return ctx


def _config(max_chars: int = 1000) -> MagicMock:
    config = MagicMock()
    config.tool_result_max_chars = max_chars
    return config


def _artifact_payload(ctx: MagicMock) -> dict[str, Any]:
    calls = [c for c in ctx.event_bus.publish.await_args_list if c.args[0] == "tool.called"]
    assert calls, "tool.called が publish されていない"
    return calls[-1].args[1]


@pytest.mark.asyncio
async def test_no_artifact_below_threshold(tmp_path: Path):
    """閾値以下ならファイルを作らない。"""
    artifact_dir = tmp_path / "artifacts"
    artifact_dir.mkdir()

    def fake_artifact_path(*_args: object) -> Path:
        return artifact_dir / "never.log"

    with (
        patch("nous.application.chat.tools.registry.execute_tool", AsyncMock(return_value=dict(SMALL))),
        patch("nous.application.chat.tools.registry.artifact_path", fake_artifact_path),
    ):
        ctx = _ctx()
        result = await ToolRegistry([]).execute(ctx, _config(), "some_tool", {})

    assert "artifact_path" not in result
    assert list(artifact_dir.iterdir()) == []
    assert "artifact_path" not in _artifact_payload(ctx)


@pytest.mark.asyncio
async def test_artifact_written_above_threshold(tmp_path: Path):
    """閾値超えなら原文を保存し、切り詰め結果に artifact_path を残す。"""
    stored: list[Path] = []

    def fake_artifact_path(persona: str, session_id: str | None, tool: str) -> Path:
        path = tmp_path / f"{persona}-{session_id}-{tool}.log"
        stored.append(path)
        return path

    with (
        patch("nous.application.chat.tools.registry.execute_tool", AsyncMock(return_value=dict(BIG))),
        patch("nous.application.chat.tools.registry.artifact_path", fake_artifact_path),
    ):
        ctx = _ctx()
        registry = ToolRegistry([])
        raw = await registry.execute(ctx, _config(max_chars=1000), "some_tool", {})
        truncated = registry.truncate_result(raw, max_chars=1000)

    assert len(stored) == 1
    assert stored[0].read_text(encoding="utf-8") == json.dumps(BIG, ensure_ascii=False)
    assert raw["artifact_path"] == str(stored[0])
    assert truncated["truncated"] is True
    assert truncated["artifact_path"] == str(stored[0])
    assert len(truncated["content"]) < len(json.dumps(BIG, ensure_ascii=False))
    assert _artifact_payload(ctx)["artifact_path"] == str(stored[0])


@pytest.mark.asyncio
async def test_artifact_failure_does_not_raise():
    """保存失敗はツールを壊さない（best-effort）。"""

    def broken_artifact_path(*_args: object) -> Path:
        return Path("/proc/1/definitely-not-writable/artifact.log")

    with (
        patch("nous.application.chat.tools.registry.execute_tool", AsyncMock(return_value=dict(BIG))),
        patch("nous.application.chat.tools.registry.artifact_path", broken_artifact_path),
    ):
        ctx = _ctx()
        result = await ToolRegistry([]).execute(ctx, _config(), "some_tool", {})

    assert result["status"] == "ok"
    assert "artifact_path" not in result
    assert "artifact_path" not in _artifact_payload(ctx)


@pytest.mark.asyncio
async def test_mcp_str_result_saved(tmp_path: Path):
    """MCP の str 結果でも保存し、audit payload に載せる。"""
    path = tmp_path / "mcp.log"
    pool = MagicMock()
    pool.list_all_tools.return_value = []
    pool.call_tool = AsyncMock(return_value="y" * 5000)

    with patch("nous.application.chat.tools.registry.artifact_path", lambda *_a: path):
        ctx = _ctx()
        result = await ToolRegistry([], mcp_pool=pool).execute(ctx, _config(), "srv__tool", {})

    assert result == "y" * 5000
    assert path.read_text(encoding="utf-8") == "y" * 5000
