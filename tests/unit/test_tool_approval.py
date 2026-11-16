"""承認ポリシー（auto / allowlist / ask）と TurnHub の承認待ち。"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

from nous.application.chat.pipeline.inference import InferenceStep
from nous.application.chat.tools.approval import approval_payload, approval_required
from nous.application.chat.turn_hub import TurnHub
from nous.domain.chat_config import ChatConfig
from nous.infrastructure.llm.base import ToolCallEvent

# ---------------------------------------------------------------------------
# ポリシー
# ---------------------------------------------------------------------------


class TestPolicy:
    def test_ask_requires_for_write_tools(self):
        config = ChatConfig(shell_approval_mode="ask")
        for tool in ("bash", "write_file", "edit_file"):
            assert approval_required(config, tool, {"command": "ls"}) is True

    def test_read_file_never_requires(self):
        config = ChatConfig(shell_approval_mode="ask")
        assert approval_required(config, "read_file", {"path": "a.txt"}) is False

    def test_non_workspace_tool_never_requires(self):
        config = ChatConfig(shell_approval_mode="ask")
        assert approval_required(config, "memory_search", {"query": "x"}) is False

    def test_auto_allows_everything(self):
        config = ChatConfig(shell_approval_mode="auto")
        assert approval_required(config, "bash", {"command": "rm -rf /"}) is False

    def test_allowlist_allows_listed_head_only(self):
        config = ChatConfig(shell_approval_mode="allowlist", shell_allowed_commands=["ls", "pwd"])
        assert approval_required(config, "bash", {"command": "ls -la"}) is False
        assert approval_required(config, "bash", {"command": "rm -rf /"}) is True

    def test_allowlist_always_requires_file_writes(self):
        config = ChatConfig(shell_approval_mode="allowlist", shell_allowed_commands=["ls"])
        assert approval_required(config, "write_file", {"path": "a.txt"}) is True

    def test_unknown_mode_falls_back_to_ask(self):
        config = ChatConfig(shell_approval_mode="bogus")
        assert approval_required(config, "bash", {"command": "ls"}) is True

    def test_payload_truncates_command(self):
        payload = approval_payload("bash", {"command": "x" * 1000})
        assert len(payload["detail"]) == 300

    def test_payload_for_file_tools_uses_path(self):
        assert approval_payload("edit_file", {"path": "a/b.txt"})["detail"] == "a/b.txt"
        assert approval_payload("edit_file", None)["detail"] == ""

    def test_payload_for_delegate_uses_prompt(self):
        payload = approval_payload("delegate", {"prompt": "修正して", "agent": "fixer"})
        assert payload["detail"] == "修正して"

    def test_payload_for_delegate_truncates(self):
        assert len(approval_payload("delegate", {"prompt": "x" * 500})["detail"]) == 300


# ---------------------------------------------------------------------------
# TurnHub
# ---------------------------------------------------------------------------


class TestTurnHubApproval:
    async def test_allow_resolves_waiter(self):
        hub = TurnHub()
        task = asyncio.create_task(hub.request_approval("p", "a1", {"tool_name": "bash"}))
        await asyncio.sleep(0)
        assert hub.resolve_approval("p", "a1", "allow") is True
        assert await task == "allow"

    async def test_deny_resolves_waiter(self):
        hub = TurnHub()
        task = asyncio.create_task(hub.request_approval("p", "a1", {"tool_name": "bash"}))
        await asyncio.sleep(0)
        hub.resolve_approval("p", "a1", "deny")
        assert await task == "deny"

    async def test_timeout_is_deny(self):
        hub = TurnHub()
        assert await hub.request_approval("p", "a1", {"tool_name": "bash"}, timeout=0.01) == "deny"

    async def test_unknown_approval_id_is_false(self):
        assert TurnHub().resolve_approval("p", "nope", "allow") is False

    async def test_request_publishes_sse_event(self):
        hub = TurnHub()
        task = asyncio.create_task(
            hub.request_approval("p", "a1", {"tool_name": "bash", "detail": "ls -la"}, timeout=0.01)
        )
        await task
        sse = "".join(s for _seq, s in hub.snapshot_after("p", 0))
        assert "event: approval_requested" in sse
        assert "ls -la" in sse

    async def test_waiter_is_cleaned_up(self):
        hub = TurnHub()
        await hub.request_approval("p", "a1", {"tool_name": "bash"}, timeout=0.01)
        assert hub.resolve_approval("p", "a1", "allow") is False


# ---------------------------------------------------------------------------
# inference のゲート
# ---------------------------------------------------------------------------


class TestInferenceGate:
    async def _gate(self, decision: str, config: ChatConfig, monkeypatch, calls: list):
        hub = MagicMock()
        hub.request_approval = AsyncMock(return_value=decision)
        monkeypatch.setattr("nous.application.chat.service.get_turn_hub", lambda: hub)
        ctx = MagicMock()
        ctx.persona = "p"
        tc = ToolCallEvent(tool_name="bash", tool_input={"command": "ls"}, tool_use_id="t1")
        step = InferenceStep.__new__(InferenceStep)
        return await step._approval_denied(ctx, config, tc)

    async def test_denied_returns_denied_result(self, monkeypatch):
        denied = await self._gate("deny", ChatConfig(shell_approval_mode="ask"), monkeypatch, [])
        assert denied is not None
        assert denied["status"] == "denied"

    async def test_allowed_returns_none(self, monkeypatch):
        assert await self._gate("allow", ChatConfig(shell_approval_mode="ask"), monkeypatch, []) is None

    async def test_auto_mode_never_asks(self, monkeypatch):
        hub = MagicMock()
        hub.request_approval = AsyncMock()
        monkeypatch.setattr("nous.application.chat.service.get_turn_hub", lambda: hub)
        step = InferenceStep.__new__(InferenceStep)
        tc = ToolCallEvent(tool_name="bash", tool_input={"command": "ls"}, tool_use_id="t1")
        assert await step._approval_denied(MagicMock(), ChatConfig(shell_approval_mode="auto"), tc) is None
        hub.request_approval.assert_not_awaited()
