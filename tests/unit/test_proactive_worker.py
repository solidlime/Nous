"""ProactiveWorker — 自発発言の push 経路（kanban #44）のテスト。

idle 判定は ``chat.message`` のみ・cooldown は ``proactive.spoke`` のみ、
``<silent>`` は何も残さない、話す時は main へ assistant 1 件 + SSE 3 発。
"""

from __future__ import annotations

import json
from datetime import timedelta
from unittest.mock import MagicMock

import pytest

from nous.application.chat.session_manager import SessionManager
from nous.application.workers import proactive_worker
from nous.domain.config.session_config import SessionConfig
from nous.domain.memory.session_event import SessionEvent
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


def _ctx(conn, **config) -> MagicMock:
    ctx = MagicMock()
    ctx.persona = PERSONA
    ctx.connection = conn
    cfg = MagicMock()
    cfg.max_stored_messages = 200
    cfg.session_config = SessionConfig(**config)
    ctx.config = cfg
    return ctx


def _messages(conn) -> list[dict]:
    return SessionManager.get_messages(conn.get_memory_db(), PERSONA, "main")


def _events(conn) -> list[str]:
    return [e.event_type for e in SessionEventRepository(conn).get_by_persona(PERSONA, limit=50)]


@pytest.fixture
def chat(monkeypatch):
    """ChatService().chat の差し替え。応答本文を差し替え可能にする。"""
    state = {"text": "ねえ、少し休んだら？"}

    class _FakeChat:
        async def chat(self, ctx, config, session_id, user_message, **_kw):
            from nous.application.chat.events import TextDeltaSSE

            state["session_id"] = session_id
            state["prompt"] = user_message
            if state["text"]:
                yield TextDeltaSSE(content=state["text"]).to_sse()

    monkeypatch.setattr(proactive_worker, "ChatService", _FakeChat)
    return state


@pytest.fixture
def published(monkeypatch):
    from nous.application.chat.turn_hub import TurnHub

    calls: list[tuple[str, str]] = []
    monkeypatch.setattr(TurnHub, "publish", lambda self, persona, sse: calls.append((persona, sse)))
    return calls


def _run(monkeypatch, ctx) -> proactive_worker.ProactiveWorker:
    from nous.application.use_cases import AppContextRegistry

    monkeypatch.setattr(AppContextRegistry, "all_personas", classmethod(lambda cls: [PERSONA]))
    monkeypatch.setattr(AppContextRegistry, "get", classmethod(lambda cls, persona: ctx))
    worker = proactive_worker.ProactiveWorker()
    worker.run_cycle()
    return worker


class TestLastUserMessageAt:
    def test_ignores_llm_responses(self, sqlite_conn) -> None:
        _insert(sqlite_conn, "chat.message", 300)
        _insert(sqlite_conn, "chat.llm_response", 1)
        last = SessionEventRepository(sqlite_conn).last_user_message_at(PERSONA)
        assert last is not None
        assert (get_now() - last) > timedelta(minutes=200)

    def test_ignores_internal_worker_sessions(self, sqlite_conn) -> None:
        _insert(sqlite_conn, "chat.message", 300)
        _insert(sqlite_conn, "chat.message", 1, session_id="proactive:2026-01-01")
        _insert(sqlite_conn, "chat.message", 1, session_id="self:2026-01-01")
        last = SessionEventRepository(sqlite_conn).last_user_message_at(PERSONA)
        assert last is not None
        assert (get_now() - last) > timedelta(minutes=200)

    def test_ignores_activity_worker_session(self, sqlite_conn) -> None:
        # kanban #65: activity: が抜けていて、自発活動が自分の内部ターンで
        # idle タイマーをリセットしていた。
        _insert(sqlite_conn, "chat.message", 300)
        _insert(sqlite_conn, "chat.message", 1, session_id="activity:2026-01-01")
        last = SessionEventRepository(sqlite_conn).last_user_message_at(PERSONA)
        assert last is not None
        assert (get_now() - last) > timedelta(minutes=200)

    def test_none_when_no_user_message(self, sqlite_conn) -> None:
        assert SessionEventRepository(sqlite_conn).last_user_message_at(PERSONA) is None


class TestGates:
    def test_disabled_does_nothing(self, sqlite_conn, chat, published, monkeypatch) -> None:
        _insert(sqlite_conn, "chat.message", 300)
        _run(monkeypatch, _ctx(sqlite_conn, proactive_enabled=False))
        assert "prompt" not in chat
        assert published == []

    def test_not_idle_enough_does_nothing(self, sqlite_conn, chat, published, monkeypatch) -> None:
        _insert(sqlite_conn, "chat.message", 10)
        _run(monkeypatch, _ctx(sqlite_conn, proactive_enabled=True, proactive_idle_minutes=180))
        assert "prompt" not in chat
        assert published == []

    def test_no_user_message_ever_does_nothing(self, sqlite_conn, chat, published, monkeypatch) -> None:
        _run(monkeypatch, _ctx(sqlite_conn, proactive_enabled=True))
        assert "prompt" not in chat

    def test_cooldown_blocks(self, sqlite_conn, chat, published, monkeypatch) -> None:
        _insert(sqlite_conn, "chat.message", 300)
        _insert(sqlite_conn, "proactive.spoke", 5)
        _run(monkeypatch, _ctx(sqlite_conn, proactive_enabled=True, proactive_cooldown_minutes=60))
        assert "prompt" not in chat
        assert published == []


class TestSpeak:
    def test_silent_writes_nothing(self, sqlite_conn, chat, published, monkeypatch) -> None:
        _insert(sqlite_conn, "chat.message", 300)
        chat["text"] = "  <silent>  "
        _run(monkeypatch, _ctx(sqlite_conn, proactive_enabled=True))
        assert chat["session_id"].startswith("proactive:")
        assert _messages(sqlite_conn) == []
        assert "proactive.spoke" not in _events(sqlite_conn)
        assert published == []

    def test_speak_appends_main_and_records_event(self, sqlite_conn, chat, published, monkeypatch) -> None:
        _insert(sqlite_conn, "chat.message", 300)
        _run(monkeypatch, _ctx(sqlite_conn, proactive_enabled=True))

        messages = _messages(sqlite_conn)
        assert len(messages) == 1
        assert messages[0]["role"] == "assistant"
        assert messages[0]["content"] == "ねえ、少し休んだら？"
        assert "proactive.spoke" in _events(sqlite_conn)

        assert [p for p, _ in published] == [PERSONA] * 3
        types = [json.loads(sse.removeprefix("data: "))["type"] for _, sse in published]
        assert types == ["turn_started", "text_delta", "done"]
        assert json.loads(published[1][1].removeprefix("data: "))["content"] == "ねえ、少し休んだら？"

    def test_prompt_carries_idle_context_and_extra(self, sqlite_conn, chat, published, monkeypatch) -> None:
        _insert(sqlite_conn, "chat.message", 200)
        _run(
            monkeypatch,
            _ctx(sqlite_conn, proactive_enabled=True, proactive_prompt="下の句: 静かだ"),
        )
        prompt = chat["prompt"]
        assert "200分" in prompt
        assert "<silent>" in prompt
        assert prompt.endswith("下の句: 静かだ")

    def test_speaking_does_not_publish_chat_message(self, sqlite_conn, chat, published, monkeypatch) -> None:
        _insert(sqlite_conn, "chat.message", 300)
        _run(monkeypatch, _ctx(sqlite_conn, proactive_enabled=True))
        # 自発発言は chat.message を発行しない（ユーザー発言に数えると idle がリセットされる）
        assert _events(sqlite_conn).count("chat.message") == 1


class TestFailureDoesNotFreeze:
    """LLM 失敗で判断間隔を進めない・イベント記録失敗でも cooldown を効かせる（kanban #82 B3/B6）。"""

    def test_llm_failure_does_not_advance_check(self, sqlite_conn, chat, published, monkeypatch) -> None:
        _insert(sqlite_conn, "chat.message", 300)
        chat["text"] = ""  # LLM 失敗・ターン衝突は空文字で返る

        worker = _run(monkeypatch, _ctx(sqlite_conn, proactive_enabled=True, proactive_idle_minutes=120))

        assert worker._last_check == {}
        assert published == []

    def test_silent_decision_advances_check(self, sqlite_conn, chat, published, monkeypatch) -> None:
        _insert(sqlite_conn, "chat.message", 300)
        chat["text"] = proactive_worker.SILENT_MARK

        worker = _run(monkeypatch, _ctx(sqlite_conn, proactive_enabled=True, proactive_idle_minutes=120))

        assert PERSONA in worker._last_check

    def test_event_write_failure_keeps_cooldown(self, sqlite_conn, chat, published, monkeypatch) -> None:
        from nous.application.workers import announce

        _insert(sqlite_conn, "chat.message", 300)

        class _BrokenRepo:
            def __init__(self, *_a, **_kw) -> None:
                pass

            def insert(self, *_a, **_kw) -> None:
                raise RuntimeError("db down")

        monkeypatch.setattr(announce, "SessionEventRepository", _BrokenRepo)
        worker = _run(
            monkeypatch,
            _ctx(
                sqlite_conn,
                proactive_enabled=True,
                proactive_idle_minutes=120,
                proactive_cooldown_minutes=180,
                proactive_interval_minutes=0,
            ),
        )

        assert PERSONA in worker._spoke_at
        # 2 周目はイベントが無くてもプロセス内の時刻で止まる（話し続けない）
        spoken = len(published)
        worker.run_cycle()
        assert len(published) == spoken
