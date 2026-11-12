"""``update_context(environment=...)`` も ``move`` と同じ経路を通る（kanban #49）."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nous.api.mcp._tools_persona import _tool_update_context
from nous.domain.persona.entities import PersonaState
from nous.domain.shared.result import Failure, Success


def _ctx(state: PersonaState | None = None) -> MagicMock:
    ctx = MagicMock()
    ctx.persona = "herta"
    ctx.session_id = "s1"
    ctx.persona_service.get_context.return_value = Success(
        state or PersonaState(persona="herta", environment="自室", fatigue=0.2, arousal=0.3)
    )
    ctx.persona_service.update_physical_state.return_value = Success(None)
    ctx.event_bus.publish = AsyncMock()
    return ctx


@pytest.fixture(name="rec")
def _record_patch():
    with patch("nous.application.movement.record_place_event") as rec:
        yield rec


class TestEnvironmentMovesTheCharacter:
    @pytest.mark.asyncio
    async def test_change_records_place_moved_with_cost(self, rec):
        ctx = _ctx()
        r = await _tool_update_context(ctx, "herta", environment="ラウンジ")

        assert r["ok"] is True
        assert "environment=ラウンジ" in r["result"]
        kwargs = ctx.persona_service.update_physical_state.call_args.kwargs
        assert kwargs["environment"] == "ラウンジ"
        assert kwargs["fatigue"] == pytest.approx(0.2075)  # 自室→ラウンジ = 5 分
        rec.assert_called_once()
        detail = rec.call_args.args[1]
        assert detail["from"] == "自室"
        assert detail["to"] == "ラウンジ"
        assert detail["minutes"] == 5

    @pytest.mark.asyncio
    async def test_free_text_environment_is_preserved(self, rec):
        """自由記述のまま書いても、解決できるなら同じ場所＝コストを課さない。"""
        ctx = _ctx(PersonaState(persona="herta", environment="自室", fatigue=0.2, arousal=0.3))
        await _tool_update_context(ctx, "herta", environment="自室。外は雨。")

        kwargs = ctx.persona_service.update_physical_state.call_args.kwargs
        assert kwargs["environment"] == "自室。外は雨。"
        assert "fatigue" not in kwargs
        rec.assert_not_called()

    @pytest.mark.asyncio
    async def test_unknown_place_costs_default_minutes(self, rec):
        ctx = _ctx()
        r = await _tool_update_context(ctx, "herta", environment="実験室")

        assert "environment=実験室(+10min)" in r["result"]
        rec.assert_called_once()
        assert rec.call_args.args[1]["to"] == "実験室"

    @pytest.mark.asyncio
    async def test_unreadable_state_does_not_block_other_fields(self, rec):
        """状態が読めなくても、他のフィールドの更新は成立する（移動だけ諦める）。"""
        ctx = _ctx()
        ctx.persona_service.get_context.return_value = Failure(MagicMock())
        ctx.persona_service.update_emotion.return_value = Success(None)

        r = await _tool_update_context(ctx, "herta", emotion="joy", environment="ラウンジ")

        assert r["ok"] is True
        assert "emotion=joy" in r["result"]
        assert "environment=" not in r["result"]
        rec.assert_not_called()
        ctx.persona_service.update_physical_state.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_environment_keeps_physical_updates_only(self, rec):
        ctx = _ctx()
        await _tool_update_context(ctx, "herta", physical_state="眠い")

        kwargs = ctx.persona_service.update_physical_state.call_args.kwargs
        assert kwargs == {"physical_state": "眠い"}
        rec.assert_not_called()
