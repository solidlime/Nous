"""装備コンテキストのテスト（旧 character-drift テストから装備分だけを残した）。

旧 character-drift テストから、判定器廃止後も生きる分だけを残した。
キャラ一貫性判定（character_judge / RepairStep）と drift 記憶の生成・注入は
2026-11 の遅延対策で全廃した。廃止の見張りは
tests/unit/test_post_process_validation.py の TestPerTurnJudgeRemoved にある。
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from nous.application.chat.pipeline.context_loader import _build_context_section
from nous.domain.shared.result import Success


def _make_state():
    return SimpleNamespace(
        persona="herta",
        emotion="",
        emotion_intensity=0.0,
        mental_state="",
        physical_state="",
        environment="",
        relationship_status="",
        user_info={},
        persona_info={},
    )


def _make_ctx():
    ctx = MagicMock()
    ctx.connection.get_memory_db.side_effect = Exception("no db in unit test")
    ctx.memory_service.get_by_tags = MagicMock(return_value=Success([]))
    ctx.persona_service.get_emotion_history = MagicMock(return_value=MagicMock(is_ok=False))
    ctx.equipment_service.get_equipment = MagicMock(return_value=MagicMock(is_ok=False))
    return ctx


class TestEquipmentContext:
    """装備コンテキスト: 装着済みスロットのみを注入する (audit M9-a)。

    未装着行は毎ターンの固定費で情報価値が無いため列挙しない。装着が 1 つも
    無ければブロック自体を出さない。
    """

    def _ctx_with_equipment(self, equipment: dict):
        from nous.domain.shared.result import Success

        ctx = _make_ctx()
        ctx.equipment_service.get_equipment = MagicMock(return_value=Success(equipment))
        return ctx

    @pytest.mark.asyncio
    async def test_only_equipped_slots_shown(self):
        from nous.domain.equipment.entities import VALID_SLOTS

        equipment: dict[str, str | None] = dict.fromkeys(VALID_SLOTS)
        equipment["top"] = "パーカー"
        section = await _build_context_section(self._ctx_with_equipment(equipment), _make_state())
        assert "top: パーカー" in section
        assert "未装着" not in section
        assert section.count("bottom:") == 0

    @pytest.mark.asyncio
    async def test_empty_equipment_omits_block(self):
        from nous.domain.equipment.entities import VALID_SLOTS

        section = await _build_context_section(self._ctx_with_equipment({s: None for s in VALID_SLOTS}), _make_state())
        assert "あなたの現在の装備" not in section
        assert "未装着" not in section

    @pytest.mark.asyncio
    async def test_every_equipped_slot_listed_exactly_once(self):
        from nous.domain.equipment.entities import VALID_SLOTS

        equipment: dict[str, str | None] = {s: ("テスト服" if s == "shoes" else None) for s in VALID_SLOTS}
        section = await _build_context_section(self._ctx_with_equipment(equipment), _make_state())
        assert "shoes: テスト服" in section
        assert section.count("shoes:") == 1
        # 未装着スロットは列挙しない
        for slot in VALID_SLOTS:
            if slot != "shoes":
                assert f"{slot}:" not in section
