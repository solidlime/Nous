"""ActivityWorker — 予定が無い時の自発活動（kanban #47）のテスト。

既定オフ・idle 判定・日次上限・JSON 解釈・アクション振り分け・記録の 6 点。
感情/身体の更新経路には触れない（この worker は状態を読むだけ）。
"""

from __future__ import annotations

import json
from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

from nous.application.workers import activity_worker
from nous.domain.memory.session_event import SessionEvent
from nous.domain.session_config import SessionConfig
from nous.domain.shared.result import Success
from nous.domain.shared.time_utils import get_now
from nous.infrastructure.sqlite.session_event_repo import SessionEventRepository

PERSONA = "test"


def _insert(conn, event_type: str, minutes_ago: float, session_id: str = "main") -> None:
    SessionEventRepository(conn).insert(
        SessionEvent(
            session_id=session_id,
            persona=PERSONA,
            event_type=event_type,
            timestamp=get_now() - timedelta(minutes=minutes_ago),
            summary="x",
        )
    )


def _state(*, environment: str = "書斎", emotion: str = "curious", fatigue: float = 0.3):
    state = MagicMock()
    state.environment = environment
    state.emotion = emotion
    state.emotion_intensity = 0.6
    state.fatigue = fatigue
    state.warmth = 0.5
    state.arousal = 0.4
    state.physical_state = ""
    state.mental_state = ""
    return state


def _ctx(conn, **config) -> MagicMock:
    ctx = MagicMock()
    ctx.persona = PERSONA
    ctx.connection = conn
    cfg = MagicMock()
    cfg.max_stored_messages = 200
    cfg.session_config = SessionConfig(**config)
    ctx.config = cfg
    ctx.persona_service.get_context.return_value = Success(_state())
    recent = MagicMock()
    recent.content = "前に書いたメモ"
    ctx.memory_service.get_recent.return_value = Success([recent])
    ctx.memory_service.create_memory = AsyncMock(return_value=Success(MagicMock()))
    return ctx


@pytest.fixture
def chat(monkeypatch):
    """ChatService().chat の差し替え。LLM の返答を差し替える。"""
    state = {"text": json.dumps({"action": "nothing", "reason": "用がない"})}

    class _FakeChat:
        async def chat(self, ctx, config, session_id, user_message, **_kw):
            from nous.application.chat.events import TextDeltaSSE

            state["session_id"] = session_id
            state["prompt"] = user_message
            if state["text"]:
                yield TextDeltaSSE(content=state["text"]).to_sse()

    monkeypatch.setattr(activity_worker, "ChatService", _FakeChat)
    return state


@pytest.fixture
def tools(monkeypatch):
    """execute_tool の差し替え。呼ばれた (tool_name, tool_input) を記録する。"""
    import nous.application.chat.tools.builtin as builtin

    calls: list[tuple[str, dict]] = []

    async def _fake(ctx, config, tool_name, tool_input):
        calls.append((tool_name, tool_input))
        return {"status": "ok"}

    monkeypatch.setattr(builtin, "execute_tool", _fake)
    return calls


def _run(monkeypatch, ctx) -> activity_worker.ActivityWorker:
    from nous.application.use_cases import AppContextRegistry

    monkeypatch.setattr(AppContextRegistry, "personas", classmethod(lambda cls: [PERSONA]))
    monkeypatch.setattr(AppContextRegistry, "get", classmethod(lambda cls, persona: ctx))
    worker = activity_worker.ActivityWorker()
    worker.run_cycle()
    return worker


def _acted(conn) -> list[str]:
    return [e.event_type for e in SessionEventRepository(conn).get_by_persona(PERSONA, limit=20)]


class TestGating:
    def test_disabled_by_default(self, sqlite_conn, chat, tools, monkeypatch) -> None:
        _insert(sqlite_conn, "chat.message", 300)
        _run(monkeypatch, _ctx(sqlite_conn))
        assert tools == []

    def test_requires_idle(self, sqlite_conn, chat, tools, monkeypatch) -> None:
        _insert(sqlite_conn, "chat.message", 5)
        _run(monkeypatch, _ctx(sqlite_conn, activity_enabled=True))
        assert tools == []

    def test_never_spoken_to_stays_quiet(self, sqlite_conn, chat, tools, monkeypatch) -> None:
        _run(monkeypatch, _ctx(sqlite_conn, activity_enabled=True))
        assert tools == []

    def test_daily_limit_stops_after_n(self, sqlite_conn, chat, tools, monkeypatch) -> None:
        _insert(sqlite_conn, "chat.message", 300)
        for _ in range(2):
            _insert(sqlite_conn, activity_worker.ACTED_EVENT, 30)
        chat["text"] = json.dumps({"action": "move", "target": "書斎"})
        _run(monkeypatch, _ctx(sqlite_conn, activity_enabled=True, activity_daily_limit=2))
        assert tools == []


class TestActions:
    def test_move_dispatches_move_tool(self, sqlite_conn, chat, tools, monkeypatch) -> None:
        _insert(sqlite_conn, "chat.message", 300)
        chat["text"] = json.dumps({"action": "move", "target": "書斎", "reason": "本を読みたい"})
        _run(monkeypatch, _ctx(sqlite_conn, activity_enabled=True))
        assert tools == [("move", {"place": "書斎"})]

    def test_research_dispatches_bash(self, sqlite_conn, chat, tools, monkeypatch) -> None:
        _insert(sqlite_conn, "chat.message", 300)
        chat["text"] = json.dumps({"action": "research", "command": "curl -s https://example.com"})
        _run(monkeypatch, _ctx(sqlite_conn, activity_enabled=True))
        assert tools[0][0] == "bash"
        assert "curl" in tools[0][1]["command"]

    def test_nothing_takes_no_action(self, sqlite_conn, chat, tools, monkeypatch) -> None:
        _insert(sqlite_conn, "chat.message", 300)
        _run(monkeypatch, _ctx(sqlite_conn, activity_enabled=True))
        assert tools == []

    def test_one_action_per_tick(self, sqlite_conn, chat, tools, monkeypatch) -> None:
        _insert(sqlite_conn, "chat.message", 300)
        chat["text"] = json.dumps({"action": "move", "target": "書斎"})
        _run(monkeypatch, _ctx(sqlite_conn, activity_enabled=True))
        assert len(tools) == 1


class TestRecording:
    def test_creates_memory_and_event(self, sqlite_conn, chat, tools, monkeypatch) -> None:
        _insert(sqlite_conn, "chat.message", 300)
        chat["text"] = json.dumps({"action": "move", "target": "書斎", "reason": "本を読みたい"})
        ctx = _ctx(sqlite_conn, activity_enabled=True)
        _run(monkeypatch, ctx)

        ctx.memory_service.create_memory.assert_awaited_once()
        content = ctx.memory_service.create_memory.await_args.kwargs["content"]
        assert "move" in content
        assert activity_worker.ACTED_EVENT in _acted(sqlite_conn)

    def test_does_not_touch_emotion_flow(self, sqlite_conn, chat, tools, monkeypatch) -> None:
        _insert(sqlite_conn, "chat.message", 300)
        chat["text"] = json.dumps({"action": "move", "target": "書斎"})
        ctx = _ctx(sqlite_conn, activity_enabled=True)
        _run(monkeypatch, ctx)
        # 状態は読むだけ。更新系のサービスは呼ばない。
        ctx.persona_service.get_context.assert_called()
        assert not ctx.persona_service.update_context.called


class TestParse:
    def test_tolerates_prose_and_fences(self) -> None:
        text = 'はい。\n```json\n{"action": "nothing", "reason": "x"}\n```\n以上。'
        assert activity_worker.ActivityWorker._parse(text) == {"action": "nothing", "reason": "x"}

    def test_returns_none_without_json(self) -> None:
        assert activity_worker.ActivityWorker._parse("何もしない") is None

    def test_returns_none_on_broken_json(self) -> None:
        assert activity_worker.ActivityWorker._parse("{action: nothing}") is None


class TestStateText:
    def test_includes_place_and_emotion(self, sqlite_conn) -> None:
        ctx = _ctx(sqlite_conn)
        text = activity_worker.ActivityWorker()._state_text(ctx)
        assert "場所=書斎" in text
        assert "感情=curious" in text

    def test_empty_when_state_fails(self, sqlite_conn) -> None:
        from nous.domain.shared.result import Failure

        ctx = _ctx(sqlite_conn)
        ctx.persona_service.get_context.return_value = Failure(MagicMock())
        assert activity_worker.ActivityWorker()._state_text(ctx) == ""
