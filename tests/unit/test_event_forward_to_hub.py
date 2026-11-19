"""config.updated / context.* を chat hub へ流す転送（kanban #81 W4）."""

from __future__ import annotations

import asyncio

import pytest

from nous.application.context.event_handlers import EventHandlersMixin

pytestmark = pytest.mark.unit


class _Host(EventHandlersMixin):
    persona = "herta"


def test_forward_keeps_event_name_and_uses_event_persona(monkeypatch) -> None:
    """SSE のハンドラ名を変えない（core/sse.js が同名で拾う）。"""
    seen: list[tuple[str, str, dict]] = []

    class _Hub:
        def publish_event(self, persona: str, name: str, data: dict) -> None:
            seen.append((persona, name, data))

    monkeypatch.setattr("nous.application.chat.service.get_turn_hub", lambda: _Hub())
    payload = {"persona": "someone", "emotion": "joy"}
    asyncio.run(_Host()._forward_to_hub("context.emotion_changed", payload))
    assert seen == [("someone", "context.emotion_changed", payload)]


def test_forward_falls_back_to_context_persona(monkeypatch) -> None:
    seen: list[tuple[str, str, dict]] = []

    class _Hub:
        def publish_event(self, persona: str, name: str, data: dict) -> None:
            seen.append((persona, name, data))

    monkeypatch.setattr("nous.application.chat.service.get_turn_hub", lambda: _Hub())
    asyncio.run(_Host()._forward_to_hub("config.updated", {}))
    assert seen == [("herta", "config.updated", {})]
