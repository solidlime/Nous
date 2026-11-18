"""#58: done をキャラ判定より先に出し、差し替えは done 後に通知して履歴も揃える。

- ChatService レベル: done が judge より先に届くこと / response_replaced が done の後に
  届き、修復後の本文と assistant_msg_id を持つこと。
- TreeSessionWindow.replace_response: content と segments（text は1本に畳む）が
  更新され、リロード後も修復後の本文になること。
- PostProcessStep: emit_done=False で done を流さないこと。
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nous.application.chat.pipeline.context import ChatTurnContext
from nous.domain.config.chat_config import ChatConfig
from nous.infrastructure.llm.base import DoneEvent, LLMMessage, TextDeltaEvent


def _ctx() -> MagicMock:
    ctx = MagicMock()
    ctx.persona = "test_persona"
    ctx.event_bus = MagicMock()
    ctx.event_bus.publish = AsyncMock()
    state = MagicMock()
    state.emotion = "neutral"
    state.emotion_intensity = 0.5
    for attr in ("mental_state", "physical_state", "environment", "fatigue", "warmth", "arousal"):
        setattr(state, attr, None)
    state.last_conversation_time = None
    state_result = MagicMock()
    state_result.is_ok = True
    state_result.value = state
    ctx.persona_service.get_context.return_value = state_result
    search_result = MagicMock()
    search_result.is_ok = True
    search_result.value = []
    ctx.search_engine.search.return_value = search_result
    return ctx


def _config() -> ChatConfig:
    return ChatConfig(persona="test_persona", provider="anthropic", api_key="sk-test", model="m")


def _mock_provider(text: str = "元の応答") -> MagicMock:
    async def mock_stream(*args: Any, **kwargs: Any) -> Any:
        yield TextDeltaEvent(content=text)
        yield DoneEvent(full_content=text, tool_calls=[])

    provider = MagicMock()
    provider.stream = mock_stream
    return provider


def _payloads(chunks: list[str]) -> list[dict]:
    return [json.loads(c[6:].strip()) for c in chunks if c.startswith("data: ")]


@pytest.mark.asyncio
async def test_done_is_streamed_before_character_judge(monkeypatch: pytest.MonkeyPatch) -> None:
    """判定が遅くても done が先に届く（判定の完了を待たない）。"""
    from nous.application.chat import ChatService
    from nous.application.chat.pipeline import repair

    order: list[str] = []

    async def fake_judge(config: Any, persona_identity: str, response: str) -> dict | None:
        order.append("judge")
        return {"violation": "none", "detail": ""}

    monkeypatch.setattr(repair, "judge_character", fake_judge)

    chunks: list[str] = []
    with patch("nous.application.chat.pipeline.inference.get_provider", return_value=_mock_provider()):
        async for chunk in ChatService().chat(_ctx(), _config(), "sess", "こんにちは"):
            chunks.append(chunk)
            if '"type": "done"' in chunk or '"type":"done"' in chunk:
                order.append("done")

    assert order.count("done") == 1
    assert "judge" in order
    assert order.index("done") < order.index("judge"), order


@pytest.mark.asyncio
async def test_replacement_is_streamed_after_done_and_persisted(monkeypatch: pytest.MonkeyPatch) -> None:
    """違反時は done の後に response_replaced が届き、保存済みノードも修復後の本文になる。"""
    from nous.application.chat import ChatService
    from nous.application.chat.pipeline import repair

    judgments = [{"violation": "tone", "detail": "語尾"}, {"violation": "none", "detail": ""}]

    async def fake_judge(config: Any, persona_identity: str, response: str) -> dict | None:
        return judgments.pop(0) if judgments else {"violation": "none", "detail": ""}

    async def fake_collect_text(provider: Any, *, messages: list[LLMMessage], **kwargs: Any) -> str:
        return "修復済みの応答"

    monkeypatch.setattr(repair, "judge_character", fake_judge)
    monkeypatch.setattr(repair, "collect_text", fake_collect_text)
    monkeypatch.setattr(repair, "get_provider", lambda *a, **k: object())

    replaced: dict[str, Any] = {}

    def _capture_replace(self: Any, msg_id: str, content: str) -> dict | None:
        replaced["msg_id"] = msg_id
        replaced["content"] = content
        return {"id": msg_id, "content": content}

    from nous.application.chat.tree_session import TreeSessionWindow

    with (
        patch("nous.application.chat.pipeline.inference.get_provider", return_value=_mock_provider("元の応答")),
        patch.object(TreeSessionWindow, "replace_response", _capture_replace),
    ):
        chunks: list[str] = []
        async for chunk in ChatService().chat(_ctx(), _config(), "sess2", "こんにちは"):
            chunks.append(chunk)

    types = [p.get("type") for p in _payloads(chunks)]
    assert "done" in types and "response_replaced" in types
    assert types.index("done") < types.index("response_replaced")

    payload = next(p for p in _payloads(chunks) if p.get("type") == "response_replaced")
    assert payload["content"] == "修復済みの応答"
    assert payload["assistant_msg_id"]
    assert replaced["content"] == "修復済みの応答"
    assert replaced["msg_id"] == payload["assistant_msg_id"]


class TestReplaceResponse:
    def _window(self) -> Any:
        from nous.application.chat.tree_session import TreeSessionWindow

        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.execute(
            "CREATE TABLE chat_sessions (persona TEXT, session_id TEXT, messages TEXT,"
            " timestamps TEXT, updated_at TEXT, PRIMARY KEY (persona, session_id))"
        )
        win = TreeSessionWindow()
        win.attach_db(conn, "p", "s")
        return win

    def test_rewrites_content_and_collapses_text_segments(self) -> None:
        win = self._window()
        msg_id = win.add(
            "assistant",
            "元の応答",
            segments=[
                {"type": "text", "content": "元の応答"},
                {"type": "tool_call", "name": "read_file"},
                {"type": "text", "content": "後半"},
            ],
        )
        win.flush()

        node = win.replace_response(msg_id, "修復済みの応答")

        assert node is not None
        assert node["content"] == "修復済みの応答"
        assert node["segments"] == [
            {"type": "text", "content": "修復済みの応答"},
            {"type": "tool_call", "name": "read_file"},
        ]

    def test_reload_sees_repaired_text(self) -> None:
        from nous.application.chat.tree_session import TreeSessionWindow

        win = self._window()
        msg_id = win.add("assistant", "元の応答", segments=[{"type": "text", "content": "元の応答"}])
        win.flush()
        win.replace_response(msg_id, "修復済みの応答")
        win.flush()

        reloaded = TreeSessionWindow.from_db(win._db, "p", "s")  # type: ignore[attr-defined]
        assert reloaded is not None
        messages = reloaded.get_active_path()
        assert messages[-1]["content"] == "修復済みの応答"

    def test_unknown_message_is_noop(self) -> None:
        assert self._window().replace_response("missing", "x") is None


@pytest.mark.asyncio
async def test_post_step_skips_done_when_asked() -> None:
    from nous.application.chat.events import DoneSSE
    from nous.application.chat.pipeline.post import PostProcessStep

    ctx = _ctx()
    config = _config()
    config.auto_extract = False
    config.session_summarize = False
    config.mental_model_enabled = False
    config.character_judge_enabled = False
    session = MagicMock()
    turn_ctx = ChatTurnContext(session_id="s", user_message="u")
    turn_ctx.full_response = "応答"

    events = [ev async for ev in PostProcessStep().run(ctx, config, session, turn_ctx, emit_done=False)]
    assert not any(isinstance(ev, DoneSSE) for ev in events)
