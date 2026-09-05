"""Active skills resident injection — state store + handler + prompt tests."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest


def _mock_ctx(persona: str = "herta", session_id: str = "s1") -> MagicMock:
    ctx = MagicMock()
    ctx.persona = persona
    ctx.session_id = session_id
    return ctx


def test_activate_and_get_roundtrip():
    from nous.application.chat import skills_state

    skills_state.clear_session("herta", "s1")
    assert skills_state.get_active("herta", "s1") == []
    skills_state.activate("herta", "s1", "search")
    assert skills_state.get_active("herta", "s1") == ["search"]


def test_activate_is_idempotent_and_moves_to_end():
    from nous.application.chat import skills_state

    skills_state.clear_session("herta", "s1")
    skills_state.activate("herta", "s1", "a")
    skills_state.activate("herta", "s1", "b")
    skills_state.activate("herta", "s1", "a")
    assert skills_state.get_active("herta", "s1") == ["b", "a"]


def test_deactivate_removes():
    from nous.application.chat import skills_state

    skills_state.clear_session("herta", "s1")
    skills_state.activate("herta", "s1", "a")
    skills_state.deactivate("herta", "s1", "a")
    assert skills_state.get_active("herta", "s1") == []


def test_max_active_evicts_oldest():
    from nous.application.chat import skills_state

    skills_state.clear_session("herta", "s1")
    for i in range(skills_state.MAX_ACTIVE_SKILLS + 2):
        skills_state.activate("herta", "s1", f"s{i}")
    active = skills_state.get_active("herta", "s1")
    assert len(active) == skills_state.MAX_ACTIVE_SKILLS
    assert active[0] == "s2"


def test_none_session_id_is_noop():
    from nous.application.chat import skills_state

    assert skills_state.activate("herta", None, "a") == []
    assert skills_state.get_active("herta", None) == []
    assert skills_state.deactivate("herta", None, "a") == []


def test_sessions_isolated():
    from nous.application.chat import skills_state

    skills_state.clear_session("herta", "s1")
    skills_state.clear_session("herta", "s2")
    skills_state.activate("herta", "s1", "a")
    assert skills_state.get_active("herta", "s2") == []


@pytest.mark.asyncio
async def test_handle_invoke_skill_records_activation(monkeypatch):
    from nous.application.chat import skills_state
    from nous.application.chat.tools.builtin import _handle_invoke_skill

    async def fake_tool(ctx, persona, name, task):
        assert name == "search"
        return {"ok": True, "result": "FULL BODY"}

    monkeypatch.setattr("nous.application.chat.tools.builtin._tool_invoke_skill", fake_tool)
    skills_state.clear_session("herta", "s1")

    ctx = _mock_ctx()
    out = await _handle_invoke_skill(ctx, MagicMock(), {"name": "search"})
    assert out["status"] == "ok"
    assert skills_state.get_active("herta", "s1") == ["search"]


@pytest.mark.asyncio
async def test_handle_invoke_skill_deactivate(monkeypatch):
    from nous.application.chat import skills_state
    from nous.application.chat.tools.builtin import _handle_invoke_skill

    async def must_not_call(ctx, persona, name, task):
        raise AssertionError("deactivate must not fetch body")

    monkeypatch.setattr("nous.application.chat.tools.builtin._tool_invoke_skill", must_not_call)
    skills_state.clear_session("herta", "s1")
    skills_state.activate("herta", "s1", "search")

    ctx = _mock_ctx()
    out = await _handle_invoke_skill(ctx, MagicMock(), {"name": "search", "action": "deactivate"})
    assert out["status"] == "ok"
    assert skills_state.get_active("herta", "s1") == []
