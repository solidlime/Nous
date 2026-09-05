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


def _build_prompt_with_skills(monkeypatch, enabled_skills, session_id, bodies):
    """PromptBuildStep を Fake スキルで実行し system_prompt を返す。"""
    from types import SimpleNamespace

    from nous.application.chat.pipeline.prompt import PromptBuildStep

    def fake_load(self, *args, **kwargs):
        return [
            SimpleNamespace(
                name=name,
                description=f"{name} の説明",
                content=content,
                model_dump=lambda n=name, c=content: {
                    "name": n,
                    "description": f"{n} の説明",
                    "content": c,
                },
            )
            for name, content in bodies.items()
        ]

    monkeypatch.setattr("nous.domain.skill.SkillRepository.load_from_dir", fake_load)

    ctx = MagicMock()
    ctx.persona = "herta"
    ctx.session_id = session_id
    config = MagicMock()
    config.system_prompt = "あなたはヘルタその人です。"
    config.enabled_skills = enabled_skills
    turn_ctx = MagicMock()
    turn_ctx.time_context = ""
    turn_ctx.context_section = ""
    turn_ctx.related_memories = ""
    turn_ctx.system_prompt = ""
    turn_ctx.skills_raw = []
    PromptBuildStep().run(ctx, config, turn_ctx)
    return turn_ctx.system_prompt


def test_prompt_injects_active_skill_body(monkeypatch):
    from nous.application.chat import skills_state

    skills_state.clear_session("herta", "s1")
    skills_state.activate("herta", "s1", "search")
    prompt = _build_prompt_with_skills(
        monkeypatch,
        enabled_skills=["search"],
        session_id="s1",
        bodies={"search": "# search スキル本文ダミー"},
    )
    assert "<active_skills>" in prompt
    assert "# search スキル本文ダミー" in prompt


def test_prompt_omits_block_when_no_active(monkeypatch):
    from nous.application.chat import skills_state

    skills_state.clear_session("herta", "s1")
    prompt = _build_prompt_with_skills(
        monkeypatch,
        enabled_skills=["search"],
        session_id="s1",
        bodies={"search": "# search スキル本文ダミー"},
    )
    assert "<active_skills>" not in prompt


def test_prompt_drops_active_missing_from_map(monkeypatch):
    from nous.application.chat import skills_state

    skills_state.clear_session("herta", "s1")
    skills_state.activate("herta", "s1", "ghost")
    prompt = _build_prompt_with_skills(
        monkeypatch,
        enabled_skills=["search"],
        session_id="s1",
        bodies={"search": "# search スキル本文ダミー"},
    )
    assert "<active_skills>" not in prompt
