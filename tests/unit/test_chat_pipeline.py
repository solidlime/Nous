"""tests/unit/test_chat_pipeline.py — パイプライン各ステップのユニットテスト。"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from nous.application.chat.events import (
    DebugInfoSSE,
    DoneSSE,
    ErrorSSE,
    TextDeltaSSE,
    ToolCallSSE,
    ToolResultSSE,
)
from nous.application.chat.pipeline.context import ChatTurnContext
from nous.application.chat.pipeline.prepare import _compute_recency_decay
from nous.domain.shared.errors import DomainError
from nous.domain.shared.result import Failure, Success

# --- Events ---


class TestSSEEvents:
    def test_text_delta_sse(self):
        ev = TextDeltaSSE(content="hello")
        s = ev.to_sse()
        assert s.startswith("data: ")
        assert '"type": "text_delta"' in s
        assert '"hello"' in s

    def test_tool_call_sse(self):
        ev = ToolCallSSE(name="memory_create", input={"content": "x"}, id="tc1")
        s = ev.to_sse()
        assert '"type": "tool_call"' in s
        assert "memory_create" in s

    def test_tool_result_sse(self):
        ev = ToolResultSSE(name="memory_create", result={"status": "ok"}, id="tc1")
        s = ev.to_sse()
        assert '"type": "tool_result"' in s

    def test_done_sse(self):
        ev = DoneSSE()
        s = ev.to_sse()
        assert '"type": "done"' in s
        assert "completed" in s

    def test_error_sse(self):
        ev = ErrorSSE(message="oops")
        s = ev.to_sse()
        assert '"type": "error"' in s
        assert "oops" in s

    def test_debug_info_sse(self):
        ev = DebugInfoSSE(data={"key": "val"})
        s = ev.to_sse()
        assert '"type": "debug_info"' in s
        assert "val" in s


# --- ChatTurnContext ---


class TestChatTurnContext:
    def test_defaults(self):
        ctx = ChatTurnContext(session_id="s1", user_message="hello")
        assert ctx.context_section == ""
        assert ctx.related_memories == ""
        assert ctx.system_prompt == ""
        assert ctx.full_response == ""
        assert ctx.tool_call_count == 0
        assert ctx.messages == []
        assert ctx.tool_calls_log == []

    def test_session_and_message_set(self):
        ctx = ChatTurnContext(session_id="abc", user_message="test message")
        assert ctx.session_id == "abc"
        assert ctx.user_message == "test message"


# --- EmotionDecay ---


class TestComputeEmotionDecay:
    def test_zero_intensity_no_decay(self):
        """Zero intensity → no decay needed, returns (emotion, 0.0)."""
        from nous.domain.persona.emotion_decay import compute_emotion_decay

        _, result = compute_emotion_decay(intensity=0.0, elapsed_hours=10)
        assert result == 0.0

    def test_decay_after_elapsed(self):
        """intensity=0.8, elapsed=48h → effective_half_life=24*0.8=19.2h."""
        from nous.domain.persona.emotion_decay import compute_emotion_decay

        _, result = compute_emotion_decay(intensity=0.8, elapsed_hours=48.0)
        assert result > 0.0
        assert result < 0.8  # decayed
        # effective_half_life = 24 * max(0.3, 0.8) = 19.2h
        # factor = 0.5^(48/19.2) = 0.5^2.5 ≈ 0.1768
        # result = 0.8 * 0.1768 ≈ 0.1414
        assert 0.13 <= result <= 0.15

    def test_no_change_for_zero_elapsed(self):
        """Zero elapsed → decay returns (emotion, 0.0)."""
        from nous.domain.persona.emotion_decay import compute_emotion_decay

        _, result = compute_emotion_decay(intensity=0.8, elapsed_hours=0)
        assert result == 0.0

    def test_high_intensity_persists_longer(self):
        """Higher intensity (0.9) decays slower than lower intensity (0.3) over same period."""
        from nous.domain.persona.emotion_decay import compute_emotion_decay

        _, high = compute_emotion_decay(intensity=0.9, elapsed_hours=48.0)
        _, low = compute_emotion_decay(intensity=0.3, elapsed_hours=48.0)
        # high: effective_half_life = 24*0.9 = 21.6h, result ≈ 0.1931
        # low:  effective_half_life = 24*0.3 = 7.2h,  result ≈ 0.0030
        assert high > low
        assert high > 0.15  # well preserved
        assert low < 0.01  # almost gone

    def test_min_cap_prevents_instant_decay(self):
        """intensity=0.05 (below cap=0.3) uses min effective_half_life to avoid vanishing instantly."""
        from nous.domain.persona.emotion_decay import compute_emotion_decay

        _, result = compute_emotion_decay(intensity=0.05, elapsed_hours=6.0)
        # Without cap: effective_half_life = 24*0.05 = 1.2h
        #   factor = 0.5^(6/1.2) = 0.5^5 = 0.03125 → result ≈ 0.0016
        # With cap: effective_half_life = 24*0.3 = 7.2h
        #   factor = 0.5^(6/7.2) ≈ 0.560 → result ≈ 0.028
        assert result > 0.01  # cap prevents near-zero result
        assert result < 0.8

    def test_custom_half_life_affects_decay_rate(self):
        """Custom half_life_hours changes decay rate proportionally."""
        from nous.domain.persona.emotion_decay import compute_emotion_decay

        # Same intensity and elapsed, different half-life
        _, fast = compute_emotion_decay(intensity=0.8, elapsed_hours=48.0, half_life_hours=12.0)
        _, slow = compute_emotion_decay(intensity=0.8, elapsed_hours=48.0, half_life_hours=48.0)
        # Shorter half-life → more decay → lower value
        assert fast < slow
        # fast: effective_half_life = 12*0.8 = 9.6h, factor = 0.5^(48/9.6) = 0.5^5 = 0.03125
        #   result = 0.8 * 0.03125 ≈ 0.025
        assert 0.02 <= fast <= 0.03
        # slow: effective_half_life = 48*0.8 = 38.4h, factor = 0.5^(48/38.4) = 0.5^1.25 ≈ 0.420
        #   result = 0.8 * 0.420 ≈ 0.336
        assert 0.30 <= slow <= 0.37

    def test_custom_half_life_via_kwarg(self):
        """Custom half_life_hours can be passed as keyword argument."""
        from nous.domain.persona.emotion_decay import compute_emotion_decay

        _, result = compute_emotion_decay(intensity=0.5, elapsed_hours=24.0, half_life_hours=6.0)
        # effective_half_life = 6 * max(0.3, 0.5) = 6 * 0.5 = 3.0h
        # factor = 0.5^(24/3) = 0.5^8 = 0.0039
        # result = 0.5 * 0.0039 ≈ 0.00195
        assert result < 0.01  # very decayed with short half-life

    def test_custom_half_life_apply_if_needed(self):
        """apply_emotion_decay_if_needed passes half_life_hours through to compute."""
        from nous.domain.persona.emotion_decay import compute_emotion_decay

        # With very long half-life, decay should be minimal
        _, long_hl = compute_emotion_decay(intensity=0.9, elapsed_hours=48.0, half_life_hours=240.0)
        # effective_half_life = 240 * 0.9 = 216h
        # factor = 0.5^(48/216) ≈ 0.851
        # result = 0.9 * 0.851 ≈ 0.766
        assert long_hl > 0.7  # well preserved
        # Compare with default (24h) — default decays much more
        _, default_hl = compute_emotion_decay(intensity=0.9, elapsed_hours=48.0)
        assert long_hl > default_hl


# --- ToolRegistry ---


class TestToolRegistry:
    def test_builtin_tools_only(self):
        from nous.application.chat.tools.registry import ToolRegistry
        from nous.infrastructure.llm.base import ToolDefinition

        tools = [ToolDefinition(name="t1", description="d1", input_schema={})]
        reg = ToolRegistry(tools, mcp_pool=None)
        assert len(reg.get_all_tools()) == 1
        assert reg.get_all_tools()[0].name == "t1"

    def test_mcp_tool_detection(self):
        from nous.application.chat.tools.registry import ToolRegistry

        reg = ToolRegistry([], mcp_pool=None)
        assert reg.is_mcp_tool("server__tool") is True
        assert reg.is_mcp_tool("memory_create") is False

    def test_truncate_result(self):
        from nous.application.chat.tools.registry import ToolRegistry

        reg = ToolRegistry([], mcp_pool=None)
        result = {"content": "x" * 10000}
        truncated = reg.truncate_result(result, max_chars=100)
        assert isinstance(truncated, dict)

    def test_truncate_result_image_base64_replaced(self):
        """content_base64 should be replaced with compact image reference."""
        from nous.application.chat.tools.registry import ToolRegistry

        reg = ToolRegistry([], mcp_pool=None)
        b64_data = "iVBORw0KGgo" + "A" * (200 * 1024)  # ~200KB base64
        result = {
            "content": "some text result",
            "content_base64": b64_data,
            "content_type": "image/png",
        }
        truncated = reg.truncate_result(result, max_chars=10000)
        # content_base64 が参照文字列に置換されている
        assert truncated["content_base64"].startswith("[image: ")
        assert "KB" in truncated["content_base64"]
        assert "image/png" in truncated["content_base64"]
        # content_type は維持
        assert truncated["content_type"] == "image/png"
        # 参照文字列はコンパクト (生base64 <> 参照でサイズ差を確認)
        assert len(truncated["content_base64"]) < 200

    def test_truncate_result_artifacts_replaced(self):
        """artifacts entries should each be replaced with image reference."""
        from nous.application.chat.tools.registry import ToolRegistry

        reg = ToolRegistry([], mcp_pool=None)
        result = {
            "stdout": "execution ok",
            "artifacts": [
                "iVBORw0KGgo" + "B" * 50000,
                "iVBORw0KGgo" + "C" * 30000,
            ],
        }
        truncated = reg.truncate_result(result, max_chars=10000)
        assert len(truncated["artifacts"]) == 2
        for ref in truncated["artifacts"]:
            assert ref.startswith("[image: ")
            assert "KB" in ref
            assert "image/png" in ref

    def test_truncate_result_both_image_fields_replaced(self):
        """Both content_base64 and artifacts are replaced."""
        from nous.application.chat.tools.registry import ToolRegistry

        reg = ToolRegistry([], mcp_pool=None)
        result = {
            "content": "has both image types",
            "content_base64": "iVBORw0KGgo" + "D" * 20000,
            "content_type": "image/jpeg",
            "artifacts": ["iVBORw0KGgo" + "E" * 10000],
        }
        truncated = reg.truncate_result(result, max_chars=10000)
        assert truncated["content_base64"].startswith("[image: ")
        assert "image/jpeg" in truncated["content_base64"]
        assert len(truncated["artifacts"]) == 1
        assert truncated["artifacts"][0].startswith("[image: ")

    def test_truncate_result_image_text_truncated(self):
        """Text part should still be truncated even when images present."""
        from nous.application.chat.tools.registry import ToolRegistry

        reg = ToolRegistry([], mcp_pool=None)
        result = {
            "content": "x" * 10000,
            "content_base64": "iVBORw0KGgo",
            "content_type": "image/png",
        }
        truncated = reg.truncate_result(result, max_chars=100)
        assert truncated["content"].endswith("... [truncated]")
        assert truncated["content_base64"].startswith("[image: ")

    def test_truncate_result_data_uri_prefix(self):
        """content_base64 with data:image/...;base64, prefix is handled."""
        from nous.application.chat.tools.registry import ToolRegistry

        reg = ToolRegistry([], mcp_pool=None)
        raw_b64 = "iVBORw0KGgo" + "F" * 10000
        data_uri = f"data:image/webp;base64,{raw_b64}"
        result = {
            "content": "data uri style",
            "content_base64": data_uri,
        }
        truncated = reg.truncate_result(result, max_chars=10000)
        assert truncated["content_base64"].startswith("[image: ")
        assert "image/webp" in truncated["content_base64"]


# ──────────────────────────────────────────────
# PrepareStep — _compute_recency_decay
# ──────────────────────────────────────────────


class TestComputeRecencyDecay:
    """Tests for _compute_recency_decay()."""

    def test_none_created_at_returns_half(self):
        """When created_at is None, return 0.5 (default half-life decay)."""
        result = _compute_recency_decay(None)
        assert result == 0.5

    def test_tz_naive_created_at(self):
        """A timezone-naive datetime should be handled (converted to UTC)."""
        naive_dt = datetime.now().replace(tzinfo=None) - timedelta(days=1)
        result = _compute_recency_decay(naive_dt)
        assert 0.0 < result < 1.0

    def test_tz_aware_created_at(self):
        """A timezone-aware datetime should work directly."""
        aware_dt = datetime.now(UTC) - timedelta(days=1)
        result = _compute_recency_decay(aware_dt)
        assert 0.0 < result < 1.0

    def test_future_date_clamps_to_zero(self):
        """Created_at in the future should result in days_elapsed=0 → exp(0)=1."""
        future = datetime.now(UTC) + timedelta(days=365)
        result = _compute_recency_decay(future)
        assert result == 1.0

    def test_recent_memory_higher_than_old(self):
        """A very recent memory should have higher recency than a very old one."""
        recent = datetime.now(UTC) - timedelta(hours=1)
        old = datetime.now(UTC) - timedelta(days=30)
        recent_decay = _compute_recency_decay(recent)
        old_decay = _compute_recency_decay(old)
        assert recent_decay > old_decay


# ──────────────────────────────────────────────
# PrepareStep — _build_context_section tier structure
# ──────────────────────────────────────────────


class TestBuildContextSectionLightMode:
    """_build_context_section should skip heavy sections in light/aggressive mode."""

    @pytest.mark.asyncio
    async def test_light_mode_skips_heavy_sections(self):
        """compress_mode='light' should skip reflection, mental model, session summary, emotion history."""
        from unittest.mock import MagicMock

        from nous.application.chat.pipeline.prepare import _build_context_section

        ctx = MagicMock()
        ctx.persona = "test"
        ctx.memory_service = MagicMock()
        ctx.persona_service = MagicMock()
        ctx.equipment_service = MagicMock()

        # State with minimal data to trigger tiers
        state = MagicMock()
        state.last_conversation_time = None
        state.emotion = None
        state.mental_state = None
        state.physical_state = None
        state.environment = None
        state.relationship_status = None
        state.user_info = {}
        state.persona_info = {}
        state.fatigue = None
        state.pain = None
        state.arousal = None

        result = await _build_context_section(ctx, state, compress_mode="light")
        # Should still contain basic structure (time info moved to TIME_CONTEXT block)
        assert "【現在の状態】" in result
        # Should not call emotion history
        ctx.persona_service.get_emotion_history.assert_not_called()
        # Light mode should not fetch heavy sections (reflection, mental_model, session_summary)
        for call_args in ctx.memory_service.get_by_tags.call_args_list:
            tags = call_args[0][0]
            assert "reflection" not in tags
            assert "mental_model" not in tags
            assert "session_summary" not in tags


class TestBuildContextSectionNormalMode:
    """_build_context_section should include heavy sections in auto/normal mode."""

    @pytest.mark.asyncio
    async def test_normal_mode_includes_all_sections(self):
        """compress_mode='auto' should attempt to fetch all sections."""
        from unittest.mock import MagicMock

        from nous.application.chat.pipeline.prepare import _build_context_section
        from nous.domain.shared.result import Success

        ctx = MagicMock()
        ctx.persona = "test"
        ctx.memory_service = MagicMock()
        ctx.memory_service.get_by_tags.return_value = Success([])
        ctx.persona_service = MagicMock()
        ctx.persona_service.get_emotion_history.return_value = Success([])
        ctx.equipment_service = MagicMock()
        ctx.equipment_service.get_equipment.return_value = Success({})

        state = MagicMock()
        state.last_conversation_time = None
        state.emotion = None
        state.mental_state = None
        state.physical_state = None
        state.environment = None
        state.relationship_status = None
        state.user_info = {}
        state.persona_info = {}
        state.fatigue = None
        state.pain = None
        state.arousal = None

        result = await _build_context_section(ctx, state, compress_mode="auto")
        assert "【現在の状態】" in result


class TestBuildContextSectionTierContent:
    """Verify specific tier content in _build_context_section."""

    @pytest.mark.asyncio
    async def test_tier1_emotion_and_mental_state(self):
        """Tier1 should include emotion and mental state when present."""
        from unittest.mock import MagicMock

        from nous.application.chat.pipeline.prepare import _build_context_section

        ctx = MagicMock()
        ctx.persona = "test"
        ctx.memory_service = MagicMock()
        ctx.memory_service.get_by_tags.return_value = MagicMock()
        ctx.memory_service.get_by_tags.return_value.is_ok = False
        ctx.persona_service = MagicMock()
        ctx.persona_service.get_emotion_history.return_value = MagicMock()
        ctx.persona_service.get_emotion_history.return_value.is_ok = False
        ctx.equipment_service = MagicMock()
        ctx.equipment_service.get_equipment.return_value = MagicMock()
        ctx.equipment_service.get_equipment.return_value.is_ok = False

        state = MagicMock()
        state.last_conversation_time = None
        state.emotion = "喜び"
        state.emotion_intensity = 0.8
        state.physical_state = None
        state.environment = None
        state.relationship_status = None
        state.user_info = {}
        state.persona_info = {}
        state.fatigue = None
        state.pain = None
        state.arousal = None

        result = await _build_context_section(ctx, state)
        assert "喜び" in result
        assert "強い" in result  # intensity 0.8 > 0.6 → "強い"

    @pytest.mark.asyncio
    async def test_tier2_body_metrics_and_environment(self):
        """Tier2 should include body metrics and environment when present."""
        from unittest.mock import MagicMock

        from nous.application.chat.pipeline.prepare import _build_context_section

        ctx = MagicMock()
        ctx.persona = "test"
        ctx.memory_service = MagicMock()
        ctx.memory_service.get_by_tags.return_value = MagicMock()
        ctx.memory_service.get_by_tags.return_value.is_ok = False
        ctx.persona_service = MagicMock()
        ctx.persona_service.get_emotion_history.return_value = MagicMock()
        ctx.persona_service.get_emotion_history.return_value.is_ok = False
        ctx.equipment_service = MagicMock()
        ctx.equipment_service.get_equipment.return_value = MagicMock()
        ctx.equipment_service.get_equipment.return_value.is_ok = False

        state = MagicMock()
        state.last_conversation_time = None
        state.emotion = None
        state.mental_state = None
        state.physical_state = "少し疲れた"
        state.fatigue = 0.8
        state.pain = 0.0
        state.arousal = 0.3
        state.environment = "自室"
        state.relationship_status = None
        state.user_info = {}
        state.persona_info = {}
        state.equipped_items = None

        result = await _build_context_section(ctx, state)
        assert "身体:" in result
        assert "疲労" in result
        assert "自室" in result

    @pytest.mark.asyncio
    async def test_tier2_user_info_and_persona_info(self):
        """Tier2 should include user_info and persona_info."""
        from unittest.mock import MagicMock

        from nous.application.chat.pipeline.prepare import _build_context_section

        ctx = MagicMock()
        ctx.persona = "test"
        ctx.memory_service = MagicMock()
        ctx.memory_service.get_by_tags.return_value = MagicMock()
        ctx.memory_service.get_by_tags.return_value.is_ok = False
        ctx.persona_service = MagicMock()
        ctx.persona_service.get_emotion_history.return_value = MagicMock()
        ctx.persona_service.get_emotion_history.return_value.is_ok = False
        ctx.equipment_service = MagicMock()
        ctx.equipment_service.get_equipment.return_value = MagicMock()
        ctx.equipment_service.get_equipment.return_value.is_ok = False

        state = MagicMock()
        state.last_conversation_time = None
        state.emotion = None
        state.mental_state = None
        state.physical_state = None
        state.fatigue = None
        state.pain = None
        state.arousal = None
        state.environment = None
        state.relationship_status = None
        state.user_info = {"name": "Taro", "age": "30"}
        state.persona_info = {"role": "assistant", "goals": "hidden_goal"}

        result = await _build_context_section(ctx, state)
        assert "ユーザー情報:" in result
        assert "Taro" in result
        assert "ペルソナ情報:" in result
        assert "assistant" in result
        # goals should be filtered out (in _hidden set)
        assert "hidden_goal" not in result


class TestEmotionTrendTimestamp:
    """感情推移行に EmotionRecord.timestamp の時刻が含まれること（設計 §4.3 / P5）。

    形式: 当日 → HH:MM のみ / 過去日 → M/D HH:MM。
    """

    def _make_ctx(self, records):
        from unittest.mock import MagicMock

        ctx = MagicMock()
        ctx.persona = "test"
        ctx.memory_service = MagicMock()
        ctx.memory_service.get_by_tags.return_value = MagicMock()
        ctx.memory_service.get_by_tags.return_value.is_ok = False
        ctx.persona_service = MagicMock()
        eh = MagicMock()
        eh.is_ok = True
        eh.value = records
        ctx.persona_service.get_emotion_history.return_value = eh
        ctx.equipment_service = MagicMock()
        ctx.equipment_service.get_equipment.return_value = MagicMock()
        ctx.equipment_service.get_equipment.return_value.is_ok = False
        return ctx

    def _make_state(self, emotion):
        from unittest.mock import MagicMock

        state = MagicMock()
        state.last_conversation_time = None
        state.emotion = emotion
        state.emotion_intensity = 0.5
        state.mental_state = None
        state.physical_state = None
        state.environment = None
        state.relationship_status = None
        state.user_info = {}
        state.persona_info = {}
        state.fatigue = None
        state.pain = None
        state.arousal = None
        return state

    @pytest.mark.asyncio
    async def test_emotion_trend_includes_timestamps(self):
        import re
        from datetime import datetime, timedelta

        from nous.application.chat.pipeline.prepare import _build_context_section
        from nous.domain.persona.entities import EmotionRecord

        records = [
            EmotionRecord(emotion="平和", timestamp=datetime.now() - timedelta(hours=3), context="通常"),
            EmotionRecord(emotion="好奇心", timestamp=datetime.now() - timedelta(hours=1), context="強"),
        ]
        ctx = self._make_ctx(records)
        state = self._make_state("喜び")  # prev(好奇心) != 喜び → 推移行が出る

        result = await _build_context_section(ctx, state)

        assert "感情推移:" in result
        line = [ln for ln in result.splitlines() if "感情推移:" in ln][0]
        # 各要素に時刻（当日 HH:MM か過去日 M/D HH:MM）が付く
        stamps = re.findall(r"（(?:\d{1,2}/\d{1,2} )?\d{2}:\d{2}）", line)
        assert len(stamps) >= 2, f"expected timestamps in trend line: {line}"

    @pytest.mark.asyncio
    async def test_emotion_trend_no_timestamp_without_change(self):
        """前回と同じ感情なら推移行自体が出ない（既存挙動の維持）。"""
        from datetime import datetime, timedelta

        from nous.application.chat.pipeline.prepare import _build_context_section
        from nous.domain.persona.entities import EmotionRecord

        records = [
            EmotionRecord(emotion="喜び", timestamp=datetime.now() - timedelta(hours=3), context="通常"),
            EmotionRecord(emotion="喜び", timestamp=datetime.now() - timedelta(hours=1), context="強"),
        ]
        ctx = self._make_ctx(records)
        state = self._make_state("喜び")

        result = await _build_context_section(ctx, state)
        assert "感情推移:" not in result


class TestDecayNoteInContextSection:
    """decay_note が Tier 2（身体・環境）ブロックに出力されること。"""

    @pytest.mark.asyncio
    async def test_decay_note_appears_in_tier2(self):
        from unittest.mock import MagicMock

        from nous.application.chat.pipeline.prepare import _build_context_section
        from nous.domain.persona.entities import PersonaState

        note = "2時間の間に、joyの感情は減衰した（現在の強度: 0.4）\n3時間の経過で fatigue 40%→55% に上昇"
        state = PersonaState(persona="t", fatigue=0.55)
        result = await _build_context_section(MagicMock(), state, compress_mode="light", decay_note=note)
        assert "状態変化" in result and "fatigue 40%→55% に上昇" in result
        assert result.index("【身体・環境】") < result.index("状態変化")  # Tier 2 内

    @pytest.mark.asyncio
    async def test_no_decay_note_no_section(self):
        from unittest.mock import MagicMock

        from nous.application.chat.pipeline.prepare import _build_context_section
        from nous.domain.persona.entities import PersonaState

        result = await _build_context_section(MagicMock(), PersonaState(persona="t"), compress_mode="light")
        assert "状態変化" not in result


class TestPrepareStepBodyDecayNote:
    """PrepareStep.run: 身体減衰の前後差分が decay_note に連結されること。"""

    async def _run(self, after_fatigue):
        from types import SimpleNamespace
        from unittest.mock import AsyncMock, MagicMock, patch

        from nous.application.chat.pipeline.context import ChatTurnContext
        from nous.application.chat.pipeline.prepare import PrepareStep
        from nous.domain.persona.entities import PersonaState
        from nous.domain.shared.result import Success
        from nous.domain.shared.time_utils import get_now

        state = PersonaState(persona="t", fatigue=0.4, last_conversation_time=get_now() - timedelta(hours=3))

        async def body_decay(_ctx, _persona, s):
            s.fatigue = after_fatigue
            return s

        ctx = MagicMock()
        ctx.persona = "t"
        ctx.persona_service.get_context.return_value = Success(state)
        session = SimpleNamespace(pending_memory_task=None, _messages=[])
        turn_ctx = ChatTurnContext(session_id="s", user_message="hi")
        config = SimpleNamespace(
            context_compression_mode="light",
            memory_preload_count=0,
            episode_search_enabled=False,
            show_message_timestamps=False,
            memory_digest_count=0,
        )
        note = "2時間の間に、joyの感情は減衰した（現在の強度: 0.4）"
        with (
            patch("nous.api.mcp._tools_helpers._apply_emotion_decay", AsyncMock(return_value=(state, note))),
            patch("nous.api.mcp._tools_helpers._apply_body_decay", side_effect=body_decay),
            patch("nous.api.mcp._tools_helpers._apply_relationship_decay", AsyncMock(return_value="")),
            patch("nous.application.chat.pipeline.prepare._search_memories", AsyncMock(return_value=("", {}, []))),
        ):
            await PrepareStep().run(ctx, session, turn_ctx, config)
        return turn_ctx.context_section

    @pytest.mark.asyncio
    async def test_body_decay_delta_line_appended(self):
        section = await self._run(0.55)
        assert "3時間" in section and "fatigue 40%→55% に上昇" in section
        assert "joyの感情は減衰した" in section  # 感情ノートと連結済み

    @pytest.mark.asyncio
    async def test_no_delta_no_body_line(self):
        section = await self._run(0.405)  # 差分 < 0.01 → ノートなし
        assert "上昇" not in section and "40%→" not in section


# ──────────────────────────────────────────────
# AutoCapture — _scan_message
# ──────────────────────────────────────────────


class TestAutoCaptureScanMessage:
    """Tests for auto_capture._scan_message()."""

    def _scan(self, content: str) -> list[tuple[str, str, float]]:
        from nous.application.chat.pipeline.auto_capture import _scan_message

        return _scan_message(content)

    def test_decision_japanese(self):
        """日本語の決定表現 -> decision カテゴリ."""
        results = self._scan("来週からジムに通うことにした。")
        assert any(cat == "decision" for _, cat, _ in results)
        assert any("通うことにした" in text for text, _, _ in results)

    def test_decision_english(self):
        """英語の決定表現 -> decision カテゴリ."""
        results = self._scan("I decided to start learning Python.")
        assert any(cat == "decision" for _, cat, _ in results)

    def test_preference_japanese(self):
        """日本語の好み表現 -> preference カテゴリ."""
        results = self._scan("抹茶味のアイスが好きです。")
        assert any(cat == "preference" for _, cat, _ in results)

    def test_preference_english(self):
        """英語の好み表現 -> preference カテゴリ."""
        results = self._scan("I prefer coffee over tea in the morning.")
        assert any(cat == "preference" for _, cat, _ in results)

    def test_fact_japanese(self):
        """日本語の事実表現 -> fact カテゴリ."""
        results = self._scan("実は昨日新しい本を買いました。")
        assert any(cat == "fact" for _, cat, _ in results)

    def test_fact_english(self):
        """英語の事実表現 -> fact カテゴリ."""
        results = self._scan("I remember that we met at the conference.")
        assert any(cat == "fact" for _, cat, _ in results)

    def test_problem_japanese(self):
        """日本語の問題表現 -> problem カテゴリ."""
        results = self._scan("バッテリーの減りが早いのが問題です。")
        assert any(cat == "problem" for _, cat, _ in results)

    def test_commitment_english(self):
        """英語の約束表現 -> commitment カテゴリ."""
        results = self._scan("I promise I will finish the report by Friday.")
        assert any(cat == "commitment" for _, cat, _ in results)

    def test_commitment_japanese(self):
        """日本語の約束表現 -> commitment カテゴリ."""
        results = self._scan("必ず明日までに提出します。")
        assert any(cat == "commitment" for _, cat, _ in results)

    def test_no_match_returns_empty(self):
        """パターンに合致しないテキスト -> 空リスト."""
        results = self._scan("天気がいいですね。今日は何をしましたか。")
        assert results == []

    def test_empty_content_returns_empty(self):
        """空文字列 -> 空リスト."""
        assert self._scan("") == []
        assert self._scan(None) == []  # type: ignore[arg-type]

    def test_multi_category_in_one_message(self):
        """1メッセージに複数カテゴリが含まれる場合."""
        results = self._scan("抹茶味が好きです。来週からジムに通うことにした。実は昨夜ほとんど眠れなかった。")
        cats = {cat for _, cat, _ in results}
        assert "preference" in cats
        assert "decision" in cats
        assert "fact" in cats

    def test_extracted_sentence_is_reasonable_length(self):
        """抽出されたテキストは最低5文字以上."""
        results = self._scan("好きです。")
        texts = [text for text, _, _ in results]
        for t in texts:
            assert len(t) >= 5


# ──────────────────────────────────────────────
# AutoCapture — run_auto_capture
# ──────────────────────────────────────────────


class TestRunAutoCapture:
    """Tests for auto_capture.run_auto_capture()."""

    @pytest.mark.asyncio
    async def test_disabled_config_creates_no_memories(self):
        """auto_capture 無効時 -> メモリ作成されない."""
        from unittest.mock import MagicMock

        from nous.application.chat.pipeline.auto_capture import run_auto_capture

        ctx = MagicMock()
        ctx.settings.auto_capture.enabled = False
        ctx.persona = "test"
        result = await run_auto_capture(ctx, "test", [{"role": "user", "content": "来週からジムに通うことにした。"}])
        assert result == []


class TestAutoCaptureDecision:
    @pytest.mark.asyncio
    async def test_decision_creates_memory(self):
        """決定表現を含むメッセージ -> メモリが作成される."""
        from unittest.mock import AsyncMock, MagicMock

        from nous.application.chat.pipeline.auto_capture import run_auto_capture

        ctx = MagicMock()
        ctx.settings.auto_capture.enabled = True
        ctx.settings.auto_capture.max_memories = 5
        ctx.persona = "test"
        ctx.connection.get_memory_db.return_value.execute.return_value.fetchone.return_value = None

        fake_memory = MagicMock()
        fake_memory.key = "mem_key_001"
        ctx.memory_service.create_memory = AsyncMock(return_value=Success(fake_memory))
        ctx.vector_store = None

        result = await run_auto_capture(ctx, "test", [{"role": "user", "content": "来週からジムに通うことにした。"}])
        assert len(result) == 1
        assert result[0] == "mem_key_001"
        call_kwargs = ctx.memory_service.create_memory.call_args[1]
        assert "auto_captured" in call_kwargs["tags"]
        assert "decision" in call_kwargs["tags"]

    @pytest.mark.asyncio
    async def test_max_memories_enforced(self):
        """max_memories の上限が機能する."""
        from unittest.mock import AsyncMock, MagicMock

        from nous.application.chat.pipeline.auto_capture import run_auto_capture

        ctx = MagicMock()
        ctx.settings.auto_capture.enabled = True
        ctx.settings.auto_capture.max_memories = 2
        ctx.persona = "test"

        fake_memory = MagicMock()
        fake_memory.key = "mem_key_xxx"
        ctx.memory_service.create_memory = AsyncMock(return_value=Success(fake_memory))
        ctx.vector_store = None

        result = await run_auto_capture(
            ctx,
            "test",
            [
                {
                    "role": "user",
                    "content": "抹茶味が好きです。来週からジムに通うことにした。実は昨夜ほとんど眠れなかった。必ず提出します。",
                }
            ],
            max_memories=2,
        )
        assert len(result) <= 2
        assert ctx.memory_service.create_memory.call_count <= 2

    @pytest.mark.asyncio
    async def test_no_match_creates_no_memories(self):
        """パターンに合致しないメッセージ -> メモリ作成されない."""
        from unittest.mock import MagicMock

        from nous.application.chat.pipeline.auto_capture import run_auto_capture

        ctx = MagicMock()
        ctx.settings.auto_capture.enabled = True
        ctx.settings.auto_capture.max_memories = 5
        ctx.persona = "test"

        # No match expected → create_memory never awaited, no AsyncMock needed
        result = await run_auto_capture(
            ctx, "test", [{"role": "user", "content": "今日はいい天気ですね。何か食べましょう。"}]
        )
        assert result == []
        ctx.memory_service.create_memory.assert_not_called()

    @pytest.mark.asyncio
    async def test_assistant_message_also_scanned(self):
        """アシスタントの応答もスキャン対象."""
        from unittest.mock import AsyncMock, MagicMock

        from nous.application.chat.pipeline.auto_capture import run_auto_capture

        ctx = MagicMock()
        ctx.settings.auto_capture.enabled = True
        ctx.settings.auto_capture.max_memories = 5
        ctx.persona = "test"
        ctx.connection.get_memory_db.return_value.execute.return_value.fetchone.return_value = None

        fake_memory = MagicMock()
        fake_memory.key = "mem_key_asst"
        ctx.memory_service.create_memory = AsyncMock(return_value=Success(fake_memory))
        ctx.vector_store = None

        result = await run_auto_capture(
            ctx,
            "test",
            [{"role": "assistant", "content": "あなたはコーヒーより紅茶の方が好きだと覚えています。"}],
        )
        assert len(result) >= 1
        call_kwargs = ctx.memory_service.create_memory.call_args[1]
        assert call_kwargs["privacy_level"] == "private"

    @pytest.mark.asyncio
    async def test_memory_service_failure_handled_gracefully(self):
        """memory_service.create_memory の失敗が例外を伝播させない."""
        from unittest.mock import AsyncMock, MagicMock

        from nous.application.chat.pipeline.auto_capture import run_auto_capture

        ctx = MagicMock()
        ctx.settings.auto_capture.enabled = True
        ctx.settings.auto_capture.max_memories = 5
        ctx.persona = "test"

        ctx.memory_service.create_memory = AsyncMock(return_value=Failure(DomainError("DB error")))

        result = await run_auto_capture(ctx, "test", [{"role": "user", "content": "来週からジムに通うことにした。"}])
        assert result == []


# ──────────────────────────────────────────────
# TA03: Dynamic Temperature — EmotionDrivenSampler integration
# ──────────────────────────────────────────────


class TestDynamicTemperatureInference:
    """InferenceStep が effective_temp を受け取り、provider.stream() に正しく伝搬する。"""

    @pytest.mark.asyncio
    async def test_uses_effective_temp_when_provided(self):
        """effective_temp が指定された場合、provider.stream() にそれが使われる。"""
        from unittest.mock import MagicMock, patch

        from nous.application.chat.pipeline.inference import InferenceStep
        from nous.infrastructure.llm.base import TextDeltaEvent

        # Mock provider: async generator for stream()
        async def _mock_stream(**kwargs):
            yield TextDeltaEvent(content="hello")

        mock_provider = MagicMock()
        mock_provider.stream = _mock_stream

        config = MagicMock()
        config.debug_mode = False  # この環境には /data が無いため書き込みを無効化
        config.temperature = 0.7
        config.max_tokens = 100
        config.provider = "anthropic"
        config.get_effective_api_key.return_value = "test-key"
        config.get_effective_model.return_value = "claude-3"
        config.get_effective_base_url.return_value = ""
        config.max_tool_calls = 0
        config.enable_parallel_tools = True
        config.tool_result_max_chars = 4000
        config.top_p = None

        turn_ctx = MagicMock()
        turn_ctx.images = []
        turn_ctx.tool_call_count = 0
        turn_ctx.full_response = ""
        turn_ctx.user_message = "test"
        turn_ctx.system_prompt = "test sys"
        turn_ctx.tool_calls_log = []
        turn_ctx.skills_raw = []

        registry = MagicMock()

        ctx = MagicMock()
        session_messages = []

        effective_temp = 0.85

        with patch("nous.application.chat.pipeline.inference.get_provider", return_value=mock_provider):
            events = []
            async for event in InferenceStep().run(
                ctx, config, session_messages, turn_ctx, registry, effective_temp=effective_temp
            ):
                events.append(event)

        # Verify effective_temp != base_temp
        assert effective_temp != config.temperature, "effective_temp should differ from base_temp"
        assert len(events) == 1

    @pytest.mark.asyncio
    async def test_uses_config_temp_when_effective_temp_none(self):
        """effective_temp が None の場合、config.temperature が使われる。"""
        from unittest.mock import MagicMock, patch

        from nous.application.chat.pipeline.inference import InferenceStep
        from nous.infrastructure.llm.base import TextDeltaEvent

        captured_temp = [None]  # mutable capture

        async def _mock_stream(**kwargs):
            captured_temp[0] = kwargs.get("temperature")
            yield TextDeltaEvent(content="hello")

        mock_provider = MagicMock()
        mock_provider.stream = _mock_stream

        config = MagicMock()
        config.debug_mode = False  # この環境には /data が無いため書き込みを無効化
        config.temperature = 0.7
        config.max_tokens = 100
        config.provider = "anthropic"
        config.get_effective_api_key.return_value = "test-key"
        config.get_effective_model.return_value = "claude-3"
        config.get_effective_base_url.return_value = ""
        config.max_tool_calls = 0
        config.enable_parallel_tools = True
        config.tool_result_max_chars = 4000
        config.top_p = None

        turn_ctx = MagicMock()
        turn_ctx.images = []
        turn_ctx.tool_call_count = 0
        turn_ctx.full_response = ""
        turn_ctx.user_message = "test"
        turn_ctx.system_prompt = "test sys"
        turn_ctx.tool_calls_log = []
        turn_ctx.skills_raw = []

        registry = MagicMock()
        ctx = MagicMock()
        session_messages = []

        with patch("nous.application.chat.pipeline.inference.get_provider", return_value=mock_provider):
            events = []
            async for event in InferenceStep().run(
                ctx, config, session_messages, turn_ctx, registry, effective_temp=None
            ):
                events.append(event)

        assert captured_temp[0] == config.temperature
        assert len(events) == 1

    @pytest.mark.asyncio
    async def test_effective_temp_passed_to_stream(self):
        """provider.stream() は effective_temp を temperature パラメータとして受け取る。"""
        from unittest.mock import MagicMock, patch

        from nous.application.chat.pipeline.inference import InferenceStep
        from nous.infrastructure.llm.base import TextDeltaEvent

        captured_kwargs = [None]

        async def _mock_stream(**kwargs):
            captured_kwargs[0] = kwargs
            yield TextDeltaEvent(content="hello")

        mock_provider = MagicMock()
        mock_provider.stream = _mock_stream

        config = MagicMock()
        config.debug_mode = False  # この環境には /data が無いため書き込みを無効化
        config.temperature = 0.7
        config.max_tokens = 100
        config.provider = "anthropic"
        config.get_effective_api_key.return_value = "test-key"
        config.get_effective_model.return_value = "claude-3"
        config.get_effective_base_url.return_value = ""
        config.max_tool_calls = 0
        config.enable_parallel_tools = True
        config.tool_result_max_chars = 4000
        config.top_p = None

        turn_ctx = MagicMock()
        turn_ctx.images = []
        turn_ctx.tool_call_count = 0
        turn_ctx.full_response = ""
        turn_ctx.user_message = "test"
        turn_ctx.system_prompt = "test sys"
        turn_ctx.tool_calls_log = []
        turn_ctx.skills_raw = []

        registry = MagicMock()
        ctx = MagicMock()
        session_messages = []

        with patch("nous.application.chat.pipeline.inference.get_provider", return_value=mock_provider):
            async for _ in InferenceStep().run(ctx, config, session_messages, turn_ctx, registry, effective_temp=0.85):
                pass

        assert captured_kwargs[0] is not None
        assert captured_kwargs[0]["temperature"] == 0.85

    @pytest.mark.asyncio
    async def test_emotion_driven_sampler_compute_integration(self):
        """EmotionDrivenSampler.compute() が期待通り effective_temp を計算する。"""
        from nous.domain.sampling import EmotionDrivenSampler

        base_temp = 0.7
        # anger → modifier = +0.15, intensity=0.8, scale=0.2
        # effective_modifier = 0.15 * 0.8 * 0.2 = 0.024
        # effective_temp = 0.7 + 0.024 = 0.724 → rounded to 2 decimals = 0.72
        result = EmotionDrivenSampler.compute(base_temp, "anger", 0.8, scale=0.2)
        assert result == pytest.approx(0.72, rel=1e-3)

    @pytest.mark.asyncio
    async def test_emotion_driven_sampler_neutral_no_change(self):
        """neutral emotion → modifier=0 → effective_temp == base_temp. base_temp is 0.5 already without dynamic temp."""
        from nous.domain.sampling import EmotionDrivenSampler

        result = EmotionDrivenSampler.compute(0.7, "neutral", 0.9, scale=0.2)
        assert result == pytest.approx(0.7, rel=1e-3)


# ──────────────────────────────────────────────
# Reasoning — reasoning_effort propagation (R6)
# ──────────────────────────────────────────────


class TestReasoningPropagationInference:
    """InferenceStep が config.reasoning_enabled に従って reasoning_effort を stream() に渡す。"""

    async def _run(self, captured: list[dict | None], reasoning_enabled: bool, reasoning_effort: str) -> None:
        """Mock provider で InferenceStep を1ターン回す共通ヘルパー."""
        from unittest.mock import MagicMock, patch

        from nous.application.chat.pipeline.inference import InferenceStep
        from nous.infrastructure.llm.base import TextDeltaEvent

        async def _mock_stream(**kwargs):
            captured[0] = kwargs
            yield TextDeltaEvent(content="hello")

        mock_provider = MagicMock()
        mock_provider.stream = _mock_stream

        config = MagicMock()
        config.debug_mode = False  # この環境には /data が無いため書き込みを無効化
        config.temperature = 0.7
        config.max_tokens = 100
        config.provider = "anthropic"
        config.get_effective_api_key.return_value = "test-key"
        config.get_effective_model.return_value = "claude-3"
        config.get_effective_base_url.return_value = ""
        config.max_tool_calls = 0
        config.enable_parallel_tools = True
        config.tool_result_max_chars = 4000
        config.top_p = None
        config.reasoning_enabled = reasoning_enabled
        config.reasoning_effort = reasoning_effort
        config.debug_mode = False  # この環境には /data が無いため書き込みを無効化
        config.show_message_timestamps = False

        turn_ctx = MagicMock()
        turn_ctx.images = []
        turn_ctx.tool_call_count = 0
        turn_ctx.full_response = ""
        turn_ctx.user_message = "test"
        turn_ctx.system_prompt = "test sys"
        turn_ctx.tool_calls_log = []
        turn_ctx.skills_raw = []

        registry = MagicMock()
        ctx = MagicMock()

        with patch("nous.application.chat.pipeline.inference.get_provider", return_value=mock_provider):
            async for _ in InferenceStep().run(ctx, config, [], turn_ctx, registry):
                pass

    @pytest.mark.asyncio
    async def test_reasoning_effort_passed_when_enabled(self):
        """reasoning_enabled=True → reasoning_effort が stream() に渡る."""
        captured: list = [None]
        await self._run(captured, reasoning_enabled=True, reasoning_effort="high")
        assert captured[0] is not None
        assert captured[0]["reasoning_effort"] == "high"

    @pytest.mark.asyncio
    async def test_reasoning_effort_none_when_disabled(self):
        """reasoning_enabled=False → reasoning_effort=None（effort 設定があっても）."""
        captured: list = [None]
        await self._run(captured, reasoning_enabled=False, reasoning_effort="max")
        assert captured[0] is not None
        assert captured[0]["reasoning_effort"] is None


class TestThinkingSegmentInference:
    """InferenceStep が ThinkingDeltaEvent を ThinkingDeltaSSE + segments に変換する (SPEC R5)."""

    async def _run(self, events: list):
        """Mock provider が events を yield する InferenceStep 実行。SSE と turn_ctx を返す."""
        from unittest.mock import AsyncMock, MagicMock, patch

        from nous.application.chat.pipeline.inference import InferenceStep
        from nous.infrastructure.llm.base import DoneEvent

        async def _mock_stream(*args, **kwargs):
            for ev in events:
                yield ev
            yield DoneEvent(full_content="", tool_calls=[])

        mock_provider = MagicMock()
        mock_provider.stream = _mock_stream

        config = MagicMock()
        config.debug_mode = False  # この環境には /data が無いため書き込みを無効化
        config.temperature = 0.7
        config.max_tokens = 100
        config.provider = "anthropic"
        config.get_effective_api_key.return_value = "test-key"
        config.get_effective_model.return_value = "claude-3"
        config.get_effective_base_url.return_value = ""
        config.max_tool_calls = 0
        config.enable_parallel_tools = True
        config.tool_result_max_chars = 4000
        config.top_p = None
        config.reasoning_enabled = True
        config.reasoning_effort = "high"
        config.debug_mode = False
        config.show_message_timestamps = False

        turn_ctx = MagicMock()
        turn_ctx.images = []
        turn_ctx.tool_call_count = 0
        turn_ctx.full_response = ""
        turn_ctx.user_message = "test"
        turn_ctx.system_prompt = "test sys"
        turn_ctx.tool_calls_log = []
        turn_ctx.skills_raw = []
        turn_ctx.segments = []  # 実リストで検証可能にする

        registry = MagicMock()
        registry.execute = AsyncMock(return_value={})  # ツール実行を成功させてループを継続させる
        registry.truncate_result = MagicMock(return_value={})  # ツール結果の切り詰め（JSON 直列化可能）
        ctx = MagicMock()

        sse_events = []
        with patch("nous.application.chat.pipeline.inference.get_provider", return_value=mock_provider):
            async for ev in InferenceStep().run(ctx, config, [], turn_ctx, registry):
                sse_events.append(ev)
        return sse_events, turn_ctx

    @pytest.mark.asyncio
    async def test_thinking_delta_yields_thinking_sse_and_segment(self):
        """ThinkingDeltaEvent → ThinkingDeltaSSE yield + ループ終了時に thinking segment 保存."""
        from nous.application.chat.events import ThinkingDeltaSSE
        from nous.infrastructure.llm.base import ThinkingDeltaEvent

        sse_events, turn_ctx = await self._run(
            [
                ThinkingDeltaEvent(content="step one"),
                ThinkingDeltaEvent(content=" step two"),
            ]
        )
        thinking_sse = [ev for ev in sse_events if isinstance(ev, ThinkingDeltaSSE)]
        assert [ev.content for ev in thinking_sse] == ["step one", " step two"]
        thinking_segs = [s for s in turn_ctx.segments if s.get("type") == "thinking"]
        assert thinking_segs == [{"type": "thinking", "content": "step one step two"}]

    @pytest.mark.asyncio
    async def test_empty_thinking_adds_no_segment(self):
        """thinking テキストが空 → segment を追加しない."""
        from nous.infrastructure.llm.base import ThinkingDeltaEvent

        _, turn_ctx = await self._run([ThinkingDeltaEvent(content="")])
        assert not any(s.get("type") == "thinking" for s in turn_ctx.segments)

    @pytest.mark.asyncio
    async def test_thinking_segment_flushed_before_tool_call(self):
        """tool_call 前に thinking フラッシュ（thinking → tool_call の順で segments に入る）."""
        from nous.infrastructure.llm.base import ThinkingDeltaEvent, ToolCallEvent

        _, turn_ctx = await self._run(
            [
                ThinkingDeltaEvent(content="reasoning..."),
                ToolCallEvent(tool_name="memory_search", tool_input={"q": "x"}, tool_use_id="t1"),
            ]
        )
        # ツール実行の結果 tool_result も追加される（thinking → tool_call → tool_result の順）
        assert [s.get("type") for s in turn_ctx.segments] == ["thinking", "tool_call", "tool_result"]
        assert turn_ctx.segments[0] == {"type": "thinking", "content": "reasoning..."}

    @pytest.mark.asyncio
    async def test_thinking_not_mixed_into_text_segment(self):
        """thinking と text が混ざらない（text segment は text のみ）."""
        from nous.infrastructure.llm.base import TextDeltaEvent, ThinkingDeltaEvent

        _, turn_ctx = await self._run(
            [
                ThinkingDeltaEvent(content="secret"),
                TextDeltaEvent(content="public"),
            ]
        )
        text_segs = [s for s in turn_ctx.segments if s.get("type") == "text"]
        assert text_segs == [{"type": "text", "content": "public"}]
        assert all("secret" not in str(s.get("content", "")) for s in text_segs)


# ──────────────────────────────────────────────
# TA05: Timestamp Injection — show_message_timestamps
# ──────────────────────────────────────────────


class TestTimestampInjection:
    """InferenceStep が show_message_timestamps 設定に応じてメッセージにタイムスタンプを付与する。"""

    @pytest.mark.asyncio
    async def test_timestamps_injected_when_enabled(self):
        """show_message_timestamps=True で user/assistant メッセージに [HH:MM] が付与される。"""
        from datetime import datetime
        from unittest.mock import MagicMock, patch

        from nous.application.chat.pipeline.inference import InferenceStep
        from nous.infrastructure.llm.base import LLMMessage, TextDeltaEvent

        captured_messages = [None]

        async def _mock_stream(**kwargs):
            captured_messages[0] = kwargs.get("messages", [])
            yield TextDeltaEvent(content="")

        mock_provider = MagicMock()
        mock_provider.stream = _mock_stream

        config = MagicMock()
        config.debug_mode = False
        config.temperature = 0.7
        config.max_tokens = 100
        config.provider = "anthropic"
        config.get_effective_api_key.return_value = "test-key"
        config.get_effective_model.return_value = "claude-3"
        config.get_effective_base_url.return_value = ""
        config.max_tool_calls = 0
        config.enable_parallel_tools = True
        config.tool_result_max_chars = 4000
        config.top_p = None
        config.show_message_timestamps = True

        turn_ctx = MagicMock()
        turn_ctx.images = []
        turn_ctx.tool_call_count = 0
        turn_ctx.full_response = ""
        turn_ctx.user_message = "test"
        turn_ctx.system_prompt = "test sys"
        turn_ctx.tool_calls_log = []
        turn_ctx.skills_raw = []

        registry = MagicMock()
        ctx = MagicMock()

        ts1 = datetime(2025, 6, 15, 14, 30, 0)
        ts2 = datetime(2025, 6, 15, 14, 31, 0)
        session_messages = [
            LLMMessage(role="user", content="hello", timestamp=ts1),
            LLMMessage(role="assistant", content="hi there", timestamp=ts2),
        ]

        with patch("nous.application.chat.pipeline.inference.get_provider", return_value=mock_provider):
            async for _ in InferenceStep().run(ctx, config, session_messages, turn_ctx, registry):
                pass

        assert captured_messages[0] is not None
        # Check the two session messages had timestamps injected (HTML comment format)
        assert captured_messages[0][0].content == "<!-- msg_at: 2025-06-15 14:30 -->hello"
        assert captured_messages[0][1].content == "<!-- msg_at: 2025-06-15 14:31 -->hi there"

    @pytest.mark.asyncio
    async def test_no_timestamps_when_disabled(self):
        """show_message_timestamps=False では content が変更されない。"""
        from datetime import datetime
        from unittest.mock import MagicMock, patch

        from nous.application.chat.pipeline.inference import InferenceStep
        from nous.infrastructure.llm.base import LLMMessage, TextDeltaEvent

        captured_messages = [None]

        async def _mock_stream(**kwargs):
            captured_messages[0] = kwargs.get("messages", [])
            yield TextDeltaEvent(content="")

        mock_provider = MagicMock()
        mock_provider.stream = _mock_stream

        config = MagicMock()
        config.debug_mode = False
        config.temperature = 0.7
        config.max_tokens = 100
        config.provider = "anthropic"
        config.get_effective_api_key.return_value = "test-key"
        config.get_effective_model.return_value = "claude-3"
        config.get_effective_base_url.return_value = ""
        config.max_tool_calls = 0
        config.enable_parallel_tools = True
        config.tool_result_max_chars = 4000
        config.top_p = None
        config.show_message_timestamps = False

        turn_ctx = MagicMock()
        turn_ctx.images = []
        turn_ctx.tool_call_count = 0
        turn_ctx.full_response = ""
        turn_ctx.user_message = "test"
        turn_ctx.system_prompt = "test sys"
        turn_ctx.tool_calls_log = []
        turn_ctx.skills_raw = []

        registry = MagicMock()
        ctx = MagicMock()

        ts = datetime(2025, 6, 15, 14, 30, 0)
        session_messages = [
            LLMMessage(role="user", content="hello", timestamp=ts),
        ]

        with patch("nous.application.chat.pipeline.inference.get_provider", return_value=mock_provider):
            async for _ in InferenceStep().run(ctx, config, session_messages, turn_ctx, registry):
                pass

        assert captured_messages[0] is not None
        assert captured_messages[0][0].content == "hello"

    @pytest.mark.asyncio
    async def test_tool_messages_skipped(self):
        """tool ロールのメッセージにはタイムスタンプが付与されない。"""
        from datetime import datetime
        from unittest.mock import MagicMock, patch

        from nous.application.chat.pipeline.inference import InferenceStep
        from nous.infrastructure.llm.base import LLMMessage, TextDeltaEvent

        captured_messages = [None]

        async def _mock_stream(**kwargs):
            captured_messages[0] = kwargs.get("messages", [])
            yield TextDeltaEvent(content="")

        mock_provider = MagicMock()
        mock_provider.stream = _mock_stream

        config = MagicMock()
        config.debug_mode = False
        config.temperature = 0.7
        config.max_tokens = 100
        config.provider = "anthropic"
        config.get_effective_api_key.return_value = "test-key"
        config.get_effective_model.return_value = "claude-3"
        config.get_effective_base_url.return_value = ""
        config.max_tool_calls = 0
        config.enable_parallel_tools = True
        config.tool_result_max_chars = 4000
        config.top_p = None
        config.show_message_timestamps = True

        turn_ctx = MagicMock()
        turn_ctx.images = []
        turn_ctx.tool_call_count = 0
        turn_ctx.full_response = ""
        turn_ctx.user_message = "test"
        turn_ctx.system_prompt = "test sys"
        turn_ctx.tool_calls_log = []
        turn_ctx.skills_raw = []

        registry = MagicMock()
        ctx = MagicMock()

        ts = datetime(2025, 6, 15, 14, 30, 0)
        session_messages = [
            LLMMessage(role="user", content="hi", timestamp=ts),
            LLMMessage(role="tool", content='{"result": "ok"}', timestamp=ts),
        ]

        with patch("nous.application.chat.pipeline.inference.get_provider", return_value=mock_provider):
            async for _ in InferenceStep().run(ctx, config, session_messages, turn_ctx, registry):
                pass

        assert captured_messages[0] is not None
        assert captured_messages[0][0].content == "<!-- msg_at: 2025-06-15 14:30 -->hi"
        # tool message should NOT have timestamp prefix
        assert captured_messages[0][1].content == '{"result": "ok"}'

    @pytest.mark.asyncio
    async def test_none_timestamp_skipped(self):
        """timestamp=None のメッセージはスキップされる。"""
        from datetime import datetime
        from unittest.mock import MagicMock, patch

        from nous.application.chat.pipeline.inference import InferenceStep
        from nous.infrastructure.llm.base import LLMMessage, TextDeltaEvent

        captured_messages = [None]

        async def _mock_stream(**kwargs):
            captured_messages[0] = kwargs.get("messages", [])
            yield TextDeltaEvent(content="")

        mock_provider = MagicMock()
        mock_provider.stream = _mock_stream

        config = MagicMock()
        config.debug_mode = False
        config.temperature = 0.7
        config.max_tokens = 100
        config.provider = "anthropic"
        config.get_effective_api_key.return_value = "test-key"
        config.get_effective_model.return_value = "claude-3"
        config.get_effective_base_url.return_value = ""
        config.max_tool_calls = 0
        config.enable_parallel_tools = True
        config.tool_result_max_chars = 4000
        config.top_p = None
        config.show_message_timestamps = True

        turn_ctx = MagicMock()
        turn_ctx.images = []
        turn_ctx.tool_call_count = 0
        turn_ctx.full_response = ""
        turn_ctx.user_message = "test"
        turn_ctx.system_prompt = "test sys"
        turn_ctx.tool_calls_log = []
        turn_ctx.skills_raw = []

        registry = MagicMock()
        ctx = MagicMock()

        ts = datetime(2025, 6, 15, 14, 30, 0)
        session_messages = [
            LLMMessage(role="user", content="with ts", timestamp=ts),
            LLMMessage(role="user", content="no ts", timestamp=None),
        ]

        with patch("nous.application.chat.pipeline.inference.get_provider", return_value=mock_provider):
            async for _ in InferenceStep().run(ctx, config, session_messages, turn_ctx, registry):
                pass

        assert captured_messages[0] is not None
        assert captured_messages[0][0].content == "<!-- msg_at: 2025-06-15 14:30 -->with ts"
        assert captured_messages[0][1].content == "no ts"


# ──────────────────────────────────────────────
# PrepareStep — _build_time_context
# ──────────────────────────────────────────────


class TestBuildTimeContext:
    """_build_time_context() の出力検証"""

    def test_output_structure(self):
        """<time_context>...</time_context> で囲まれ、末尾に否定例付き指示が付加される"""
        from unittest.mock import MagicMock

        from nous.application.chat.pipeline.prepare import _build_time_context

        state = MagicMock()
        state.last_conversation_time = None
        result = _build_time_context(state)
        assert result.startswith("<time_context>")
        assert "</time_context>" in result
        assert "応答テキストにこの時刻情報やタグをそのまま出力しない" in result
        assert "【内部参照情報】" in result

    def test_contains_now_and_weekday(self):
        """出力に Now: と曜日が含まれる"""
        from unittest.mock import MagicMock

        from nous.application.chat.pipeline.prepare import _build_time_context

        state = MagicMock()
        state.last_conversation_time = None
        result = _build_time_context(state)
        assert "Now:" in result
        assert any(d in result for d in ["月曜日", "火曜日", "水曜日", "木曜日", "金曜日", "土曜日", "日曜日"])

    def test_no_gap_when_no_last_conversation(self):
        """last_conversation_time が None の場合、ギャップ表示なし"""
        from unittest.mock import MagicMock

        from nous.application.chat.pipeline.prepare import _build_time_context

        state = MagicMock()
        state.last_conversation_time = None
        result = _build_time_context(state)
        assert "Time since last conversation" not in result

    def test_gap_shows_only_above_15min(self):
        """15分未満の経過時間ではギャップ表示が出ない"""
        from datetime import timedelta
        from unittest.mock import MagicMock, patch
        from zoneinfo import ZoneInfo

        from nous.application.chat.pipeline.prepare import _build_time_context

        fixed_now = datetime(2025, 6, 15, 14, 30, 0, tzinfo=ZoneInfo("Asia/Tokyo"))
        recent_conv = fixed_now - timedelta(minutes=10)

        state2 = MagicMock()
        state2.last_conversation_time = recent_conv

        with patch("nous.application.chat.pipeline.context_loader.get_now", return_value=fixed_now):
            result = _build_time_context(state2)
        # 10min < 15min threshold → no gap
        assert "Time since last conversation" not in result


class TestGapClassification:
    """_classify_gap() の境界値テスト"""

    def test_same_session(self):
        from nous.application.chat.pipeline.prepare import _classify_gap

        assert _classify_gap(0.0) == ""
        assert _classify_gap(0.1) == "SAME_SESSION"
        assert _classify_gap(0.24) == "SAME_SESSION"

    def test_boundary_same_to_short(self):
        from nous.application.chat.pipeline.prepare import _classify_gap

        assert _classify_gap(0.24) == "SAME_SESSION"
        assert _classify_gap(0.26) == "SHORT_BREAK"

    def test_boundary_short_to_extended(self):
        from nous.application.chat.pipeline.prepare import _classify_gap

        assert _classify_gap(2.9) == "SHORT_BREAK"
        assert _classify_gap(3.1) == "EXTENDED_BREAK"

    def test_boundary_extended_to_next_day(self):
        from nous.application.chat.pipeline.prepare import _classify_gap

        assert _classify_gap(23.9) == "EXTENDED_BREAK"
        assert _classify_gap(24.1) == "FEW_DAYS"

    def test_long_absence(self):
        from nous.application.chat.pipeline.prepare import _classify_gap

        assert _classify_gap(168) == "LONG_ABSENCE"  # 7 days → LONG_ABSENCE
        assert _classify_gap(169) == "LONG_ABSENCE"

    def test_very_long_absence(self):
        from nous.application.chat.pipeline.prepare import _classify_gap

        assert _classify_gap(720) == "VERY_LONG_ABSENCE"  # 30 days → VERY_LONG_ABSENCE
        assert _classify_gap(1000) == "VERY_LONG_ABSENCE"


class TestEmotionDecayNoteNaturalLanguage:
    """衰退通知の自然言語フォーマット検証"""

    def test_no_debug_format(self):
        """出力がデバッグログ形式（(0.80) のような数値付き）でないこと"""
        from nous.api.mcp._tools_helpers import _format_emotion_decay_note
        from nous.domain.persona.emotion_decay import EmotionDecayResult

        result = EmotionDecayResult(
            before_emotion="happy",
            before_intensity=0.80,
            after_emotion="happy",
            after_intensity=0.45,
            elapsed_hours=48.0,
        )
        note = _format_emotion_decay_note(result)
        assert "(" not in note  # no debug parenthetical format
        assert "→" not in note  # no debug arrow format
        assert "faded" not in note  # no English debug term

    def test_neutralization_uses_different_phrasing(self):
        """完全減衰時と部分減衰時で異なる表現を使う"""
        from nous.api.mcp._tools_helpers import _format_emotion_decay_note
        from nous.domain.persona.emotion_decay import EmotionDecayResult

        # 完全減衰 (after == neutral, intensity == 0)
        neutralized = EmotionDecayResult(
            before_emotion="anger",
            before_intensity=0.7,
            after_emotion="neutral",
            after_intensity=0.0,
            elapsed_hours=48.0,
        )
        note_neutral = _format_emotion_decay_note(neutralized)
        assert "消失した" in note_neutral

        # 部分減衰 (same emotion, reduced intensity)
        partial = EmotionDecayResult(
            before_emotion="joy",
            before_intensity=0.9,
            after_emotion="joy",
            after_intensity=0.3,
            elapsed_hours=24.0,
        )
        note_partial = _format_emotion_decay_note(partial)
        assert "減衰した" in note_partial
        assert "消失した" not in note_partial


# ──────────────────────────────────────────────
# Task 5: §1 digest / §2 recall query / §3 trim 順序 / task_state / tz
# ──────────────────────────────────────────────


class TestBuildRecallQuery:
    """_build_recall_query(): 直近 user 発言 最大3件結合・800字上限。"""

    def test_build_recall_query_joins_recent_user_messages(self):
        from types import SimpleNamespace

        from nous.application.chat.pipeline.prepare import _build_recall_query

        session = SimpleNamespace(
            _messages=[
                {"role": "user", "content": "u1"},
                {"role": "assistant", "content": "a1"},
                {"role": "user", "content": "u2"},
                {"role": "user", "content": "u3"},
                {"role": "user", "content": "u4"},
            ]
        )
        q = _build_recall_query(session, "u5")
        # 5件あるので古い u1, u2 は落ちる（新しい方から3件）
        assert "u1" not in q and "u2" not in q
        assert "u3" in q and "u4" in q and "u5" in q
        # 現在メッセージが履歴末尾と同じなら重複追加しない
        session2 = SimpleNamespace(_messages=[{"role": "user", "content": "u5"}])
        assert _build_recall_query(session2, "u5") == "u5"

    def test_build_recall_query_caps_at_800_chars_newest_side(self):
        from types import SimpleNamespace

        from nous.application.chat.pipeline.prepare import _build_recall_query

        big = "x" * 400
        session = SimpleNamespace(
            _messages=[
                {"role": "user", "content": big},
                {"role": "user", "content": big},
                {"role": "user", "content": big},
            ]
        )
        current = "y" * 400
        q = _build_recall_query(session, current)
        assert len(q) == 800
        # 新しい方から採用: 末尾は現在メッセージの末尾
        assert q.endswith(current[-100:])


class TestBuildDigest:
    """_build_digest(): 無効化・フォーマット・例外握り。"""

    def _ctx_with(self, memories):
        from unittest.mock import MagicMock

        ctx = MagicMock()
        ctx.memory_service.get_recent.return_value = Success(memories)
        return ctx

    def test_build_digest_returns_empty_when_disabled(self):
        from unittest.mock import MagicMock

        from nous.application.chat.pipeline.prepare import _build_digest

        config = MagicMock()
        config.memory_digest_count = 0
        assert _build_digest(MagicMock(), config) == ""

    def test_build_digest_formats_recent_memories(self):
        from types import SimpleNamespace
        from unittest.mock import MagicMock

        from nous.application.chat.pipeline.prepare import _build_digest

        mem = SimpleNamespace(content="テスト記憶です", updated_at=datetime.now(UTC) - timedelta(hours=2))
        ctx = self._ctx_with([mem])
        digest = _build_digest(ctx, MagicMock(memory_digest_count=5))
        assert digest.startswith("[最近のできごと")
        assert "(2h ago)" in digest
        assert "テスト記憶です" in digest

    def test_build_digest_swallows_store_failure(self):
        from unittest.mock import MagicMock

        from nous.application.chat.pipeline.prepare import _build_digest

        ctx = MagicMock()
        ctx.memory_service.get_recent.side_effect = RuntimeError("db down")
        assert _build_digest(ctx, MagicMock(memory_digest_count=5)) == ""


class TestTrimOrderToolResultsBeforeMemorySections:
    """§3: 圧縮時ツール結果置換が先に走り、予算内なら関連記憶セクションが生き残る。"""

    @pytest.mark.asyncio
    async def test_trim_order_tool_results_before_memory_sections(self):
        from types import SimpleNamespace
        from unittest.mock import MagicMock

        from nous.application.chat.pipeline.compress import CompressStep
        from nous.infrastructure.llm.base import LLMMessage

        big_json = '{"success": true, "data": "' + "x" * 1000 + '"}'
        messages = []
        for i in range(12):
            messages.append(LLMMessage(role="assistant", content=f"a{i}"))
            messages.append(LLMMessage(role="tool", content=big_json, tool_call_id=f"t{i}"))

        memory_lines = "\n".join(f"- 記憶{i}" for i in range(10))
        turn_ctx = SimpleNamespace(system_prompt=f"base\n<related_memories>\n{memory_lines}\n</related_memories>")

        config = MagicMock()
        config.context_keep_recent_turns = 0
        config.context_compress_history = True
        config.context_compress_system_prompt = True
        config.context_compression_mode = "normal"
        config.max_stored_messages = 1000
        config.get_effective_model.return_value = "claude-3"
        config.context_max_tokens = 3000
        config.context_compression_threshold = 0.9

        result = await CompressStep().run(MagicMock(), config, turn_ctx, messages)

        # Stage 1（ツール結果置換）で予算内に収まった → Stage 2 未実行
        tool_msgs = [m for m in result if m.role == "tool"]
        assert all(m.content == "[ツール実行: 成功]" for m in tool_msgs[:8])
        assert all(m.content == big_json for m in tool_msgs[8:])
        # 関連記憶 10 行すべて生き残る（トリムされていない）
        assert turn_ctx.system_prompt.count("- 記憶") == 10


class TestTaskStateInjection:
    """Tier3 への task_state 注入。"""

    @pytest.mark.asyncio
    async def test_task_state_injected_into_tier3(self):
        from types import SimpleNamespace
        from unittest.mock import MagicMock

        from nous.application.chat.pipeline.context_loader import _build_context_section

        ctx = MagicMock()
        ctx.persona = "test"
        ctx.memory_service = MagicMock()

        def fake_get_by_tags(tags):
            if tags == ["task_state"]:
                mem = SimpleNamespace(content="Lane A 実装中", tags=["task_state"], created_at=datetime.now(UTC))
                return Success([mem])
            return Success([])

        ctx.memory_service.get_by_tags.side_effect = fake_get_by_tags
        ctx.persona_service = MagicMock()
        ctx.persona_service.get_emotion_history.return_value = Success([])
        ctx.equipment_service = MagicMock()
        ctx.equipment_service.get_equipment.return_value = Success({})

        state = MagicMock()
        state.last_conversation_time = None
        state.emotion = None
        state.mental_state = None
        state.physical_state = None
        state.environment = None
        state.relationship_status = None
        state.user_info = {}
        state.persona_info = {}
        state.fatigue = None
        state.pain = None
        state.arousal = None

        result = await _build_context_section(ctx, state)
        assert "作業状態:" in result
        assert "Lane A 実装中" in result


class TestTimestampTimezoneAndDoublePrefix:
    """tz 表記修正: settings.timezone 従属・二重 prefix ガード。"""

    @pytest.mark.asyncio
    async def test_timestamp_uses_settings_timezone_and_no_double_prefix(self):
        from datetime import datetime
        from types import SimpleNamespace
        from unittest.mock import MagicMock, patch

        from nous.application.chat.pipeline.inference import InferenceStep
        from nous.infrastructure.llm.base import LLMMessage, TextDeltaEvent

        captured_messages = [None]

        async def _mock_stream(**kwargs):
            captured_messages[0] = kwargs.get("messages", [])
            yield TextDeltaEvent(content="")

        mock_provider = MagicMock()
        mock_provider.stream = _mock_stream

        config = MagicMock()
        config.debug_mode = False
        config.temperature = 0.7
        config.max_tokens = 100
        config.provider = "anthropic"
        config.get_effective_api_key.return_value = "test-key"
        config.get_effective_model.return_value = "claude-3"
        config.get_effective_base_url.return_value = ""
        config.max_tool_calls = 0
        config.enable_parallel_tools = True
        config.tool_result_max_chars = 4000
        config.top_p = None
        config.show_message_timestamps = True

        turn_ctx = MagicMock()
        turn_ctx.images = []
        turn_ctx.tool_call_count = 0
        turn_ctx.full_response = ""
        turn_ctx.user_message = "test"
        turn_ctx.system_prompt = "test sys"
        turn_ctx.tool_calls_log = []
        turn_ctx.skills_raw = []

        registry = MagicMock()
        ctx = MagicMock()

        naive_ts = datetime(2025, 6, 15, 14, 30, 0)
        session_messages = [
            # 既に prefix 済み → 二重付与されない
            LLMMessage(role="user", content="<!-- msg_at: 2025-06-15 14:30 -->hello", timestamp=naive_ts),
            # prefix 無し → settings.timezone（UTC）で付与、"JST" 固定は消える
            LLMMessage(role="assistant", content="hi there", timestamp=naive_ts),
        ]

        fake_settings = SimpleNamespace(timezone="UTC")
        with (
            patch("nous.config.settings.get_settings", return_value=fake_settings),
            patch("nous.application.chat.pipeline.inference.get_provider", return_value=mock_provider),
        ):
            async for _ in InferenceStep().run(ctx, config, session_messages, turn_ctx, registry):
                pass

        assert captured_messages[0] is not None
        first, second = captured_messages[0][0], captured_messages[0][1]
        # 二重 prefix ガード
        assert first.content.count("<!-- msg_at:") == 1
        assert first.content == "<!-- msg_at: 2025-06-15 14:30 -->hello"
        # tz 変換（UTC 指定・naive はローカル扱いでそのまま時刻）
        assert second.content.startswith("<!-- msg_at: 2025-06-15 14:30 -->")
        assert "JST" not in second.content


# ──────────────────────────────────────────────
# BugFix: inference.py — 重複排除順序 / 継続メッセージ / max_tool_calls=0 / タイムスタンプ共有 / debug dir
# ──────────────────────────────────────────────


class TestInferenceBugfixes:
    """バグハント修正の回帰テスト。"""

    def _make_config(self, **overrides):
        from unittest.mock import MagicMock

        config = MagicMock()
        config.debug_mode = False
        config.temperature = 0.7
        config.max_tokens = 100
        config.provider = "anthropic"
        config.get_effective_api_key.return_value = "test-key"
        config.get_effective_model.return_value = "claude-3"
        config.get_effective_base_url.return_value = ""
        config.max_tool_calls = 5
        config.enable_parallel_tools = True
        config.tool_result_max_chars = 4000
        config.top_p = None
        config.show_message_timestamps = False
        for k, v in overrides.items():
            setattr(config, k, v)
        return config

    def _make_turn_ctx(self, tool_calls_log=None):
        from unittest.mock import MagicMock

        turn_ctx = MagicMock()
        turn_ctx.images = []
        turn_ctx.tool_call_count = 0
        turn_ctx.full_response = ""
        turn_ctx.user_message = "test"
        turn_ctx.system_prompt = "test sys"
        turn_ctx.tool_calls_log = tool_calls_log if tool_calls_log is not None else []
        turn_ctx.skills_raw = []
        turn_ctx.segments = []
        turn_ctx.recency_digest = ""
        turn_ctx.was_truncated = False
        return turn_ctx

    async def _run(self, mock_stream_fn, config, turn_ctx, session_messages=None):
        """mock_stream_fn(**kwargs) を provider.stream として InferenceStep を実行する。"""
        from unittest.mock import AsyncMock, MagicMock, patch

        from nous.application.chat.pipeline.inference import InferenceStep

        mock_provider = MagicMock()
        mock_provider.stream = mock_stream_fn
        registry = MagicMock()
        registry.execute = AsyncMock(return_value={"ok": True})
        registry.truncate_result = MagicMock(return_value={"ok": True})

        with patch("nous.application.chat.pipeline.inference.get_provider", return_value=mock_provider):
            sse_events = []
            async for ev in InferenceStep().run(MagicMock(), config, session_messages or [], turn_ctx, registry):
                sse_events.append(ev)
        return sse_events

    @pytest.mark.asyncio
    async def test_duplicate_tool_use_id_from_log_is_skipped_entirely(self):
        """同一ターンで実行済み tool_use_id の再送 → SSE/segment/pending に記録されない（#1）."""
        from nous.application.chat.events import ToolCallSSE
        from nous.infrastructure.llm.base import DoneEvent, ToolCallEvent

        async def _stream(**kwargs):
            # モデルが t1 を再送してくるシナリオ
            yield ToolCallEvent(tool_name="memory_search", tool_input={"q": "x"}, tool_use_id="t1")
            yield DoneEvent(finish_reason="stop")

        config = self._make_config()
        turn_ctx = self._make_turn_ctx(tool_calls_log=[{"id": "t1", "name": "memory_search"}])

        sse_events = await self._run(_stream, config, turn_ctx)

        # 再送された tool call は何も記録されない
        assert not any(isinstance(ev, ToolCallSSE) for ev in sse_events)
        assert not any(s.get("type") == "tool_call" for s in turn_ctx.segments)
        assert not any(s.get("type") == "tool_result" for s in turn_ctx.segments)

    @pytest.mark.asyncio
    async def test_duplicate_tool_use_id_within_batch_executes_once(self):
        """同一バッチ内で同一 tool_use_id が2回来る → 1回だけ実行・segment も1組（#1/#3）."""
        from nous.infrastructure.llm.base import DoneEvent, ToolCallEvent

        async def _stream(**kwargs):
            yield ToolCallEvent(tool_name="memory_search", tool_input={"q": "x"}, tool_use_id="t1")
            yield ToolCallEvent(tool_name="memory_search", tool_input={"q": "x"}, tool_use_id="t1")
            yield DoneEvent(finish_reason="stop")

        config = self._make_config()
        turn_ctx = self._make_turn_ctx()

        await self._run(_stream, config, turn_ctx)

        tc_segs = [s for s in turn_ctx.segments if s.get("type") == "tool_call"]
        tr_segs = [s for s in turn_ctx.segments if s.get("type") == "tool_result"]
        assert len(tc_segs) == 1
        assert len(tr_segs) == 1
        assert len(turn_ctx.tool_calls_log) == 1

    @pytest.mark.asyncio
    async def test_all_duplicates_no_orphan_assistant_tool_calls(self):
        """全件が重複で消滅 → tool_calls 付き assistant メッセージは永続化されない（#3）."""
        from nous.infrastructure.llm.base import DoneEvent, ToolCallEvent

        captured = []

        async def _stream(**kwargs):
            captured.append(list(kwargs["messages"]))
            yield ToolCallEvent(tool_name="memory_search", tool_input={"q": "x"}, tool_use_id="t1")
            yield DoneEvent(finish_reason="stop")

        config = self._make_config()
        turn_ctx = self._make_turn_ctx(tool_calls_log=[{"id": "t1", "name": "memory_search"}])

        await self._run(_stream, config, turn_ctx)

        # ループは1回で終了し、assistant(tool_calls) も tool メッセージも追加されない
        assert len(captured) == 1
        assert not any(m.role == "assistant" and m.tool_calls for m in captured[0])
        assert not any(m.role == "tool" for m in captured[0])

    @pytest.mark.asyncio
    async def test_continuation_user_message_is_non_empty(self):
        """finish_reason=length の自動継続時、user メッセージは非空（Anthropic 400 回避）（#2）."""
        from nous.infrastructure.llm.base import DoneEvent, TextDeltaEvent

        calls = []

        async def _stream(**kwargs):
            calls.append(list(kwargs["messages"]))
            if len(calls) == 1:
                yield TextDeltaEvent(content="part1")
                yield DoneEvent(finish_reason="length")
            else:
                yield TextDeltaEvent(content="part2")
                yield DoneEvent(finish_reason="stop")

        config = self._make_config()
        turn_ctx = self._make_turn_ctx()

        await self._run(_stream, config, turn_ctx)

        assert len(calls) == 2
        cont_msg = calls[1][-1]
        assert cont_msg.role == "user"
        assert cont_msg.content.strip() != ""

    @pytest.mark.asyncio
    async def test_max_tool_calls_zero_passes_no_tools(self):
        """max_tool_calls=0 → provider にツールを渡さない（#6）."""
        from nous.infrastructure.llm.base import DoneEvent, TextDeltaEvent

        captured = []

        async def _stream(**kwargs):
            captured.append(kwargs)
            yield TextDeltaEvent(content="hello")
            yield DoneEvent(finish_reason="stop")

        config = self._make_config(max_tool_calls=0)
        turn_ctx = self._make_turn_ctx()

        await self._run(_stream, config, turn_ctx)

        assert captured[0]["tools"] == []

    @pytest.mark.asyncio
    async def test_timestamp_injection_does_not_mutate_session_messages(self):
        """タイムスタンプ注入はコピーに対して行われ、session_messages を汚さない（#8）."""
        from datetime import datetime

        from nous.infrastructure.llm.base import DoneEvent, LLMMessage, TextDeltaEvent

        async def _stream(**kwargs):
            yield TextDeltaEvent(content="hello")
            yield DoneEvent(finish_reason="stop")

        config = self._make_config(show_message_timestamps=True)
        turn_ctx = self._make_turn_ctx()

        ts = datetime(2025, 6, 15, 14, 30, 0)
        session_msg = LLMMessage(role="user", content="hello", timestamp=ts)
        await self._run(_stream, config, turn_ctx, session_messages=[session_msg])

        # 元オブジェクトは汚されていない
        assert session_msg.content == "hello"

    @pytest.mark.asyncio
    async def test_debug_mode_writes_under_tempdir(self):
        """debug_mode=True でも Windows で例外にならず、tempdir 配下に書き出される（#9）."""
        import os
        import tempfile

        from nous.infrastructure.llm.base import DoneEvent, TextDeltaEvent

        async def _stream(**kwargs):
            yield TextDeltaEvent(content="hello")
            yield DoneEvent(finish_reason="stop")

        config = self._make_config(debug_mode=True)
        turn_ctx = self._make_turn_ctx()

        sse_events = await self._run(_stream, config, turn_ctx)  # 例外が出ないこと

        assert len(sse_events) == 1
        debug_dir = os.path.join(tempfile.gettempdir(), "nous_debug")
        assert any(f.startswith("prompt_") for f in os.listdir(debug_dir))
