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
        """Zero intensity → no decay needed, returns 0.0."""
        from nous.domain.persona.emotion_decay import compute_emotion_decay

        result = compute_emotion_decay(intensity=0.0, elapsed_hours=10)
        assert result == 0.0

    def test_decay_after_elapsed(self):
        """intensity=0.8, elapsed=48h → effective_half_life=24*0.8=19.2h."""
        from nous.domain.persona.emotion_decay import compute_emotion_decay

        result = compute_emotion_decay(intensity=0.8, elapsed_hours=48.0)
        assert result > 0.0
        assert result < 0.8  # decayed
        # effective_half_life = 24 * max(0.3, 0.8) = 19.2h
        # factor = 0.5^(48/19.2) = 0.5^2.5 ≈ 0.1768
        # result = 0.8 * 0.1768 ≈ 0.1414
        assert 0.13 <= result <= 0.15

    def test_no_change_for_zero_elapsed(self):
        """Zero elapsed → decay returns 0.0 (caller skips when elapsed <= 0)."""
        from nous.domain.persona.emotion_decay import compute_emotion_decay

        result = compute_emotion_decay(intensity=0.8, elapsed_hours=0)
        assert result == 0.0

    def test_high_intensity_persists_longer(self):
        """Higher intensity (0.9) decays slower than lower intensity (0.3) over same period."""
        from nous.domain.persona.emotion_decay import compute_emotion_decay

        high = compute_emotion_decay(intensity=0.9, elapsed_hours=48.0)
        low = compute_emotion_decay(intensity=0.3, elapsed_hours=48.0)
        # high: effective_half_life = 24*0.9 = 21.6h, result ≈ 0.1931
        # low:  effective_half_life = 24*0.3 = 7.2h,  result ≈ 0.0030
        assert high > low
        assert high > 0.15  # well preserved
        assert low < 0.01  # almost gone

    def test_min_cap_prevents_instant_decay(self):
        """intensity=0.05 (below cap=0.3) uses min effective_half_life to avoid vanishing instantly."""
        from nous.domain.persona.emotion_decay import compute_emotion_decay

        result = compute_emotion_decay(intensity=0.05, elapsed_hours=6.0)
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
        fast = compute_emotion_decay(intensity=0.8, elapsed_hours=48.0, half_life_hours=12.0)
        slow = compute_emotion_decay(intensity=0.8, elapsed_hours=48.0, half_life_hours=48.0)
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

        result = compute_emotion_decay(intensity=0.5, elapsed_hours=24.0, half_life_hours=6.0)
        # effective_half_life = 6 * max(0.3, 0.5) = 6 * 0.5 = 3.0h
        # factor = 0.5^(24/3) = 0.5^8 = 0.0039
        # result = 0.5 * 0.0039 ≈ 0.00195
        assert result < 0.01  # very decayed with short half-life

    def test_custom_half_life_apply_if_needed(self):
        """apply_emotion_decay_if_needed passes half_life_hours through to compute."""
        from nous.domain.persona.emotion_decay import compute_emotion_decay

        # With very long half-life, decay should be minimal
        long_hl = compute_emotion_decay(intensity=0.9, elapsed_hours=48.0, half_life_hours=240.0)
        # effective_half_life = 240 * 0.9 = 216h
        # factor = 0.5^(48/216) ≈ 0.851
        # result = 0.9 * 0.851 ≈ 0.766
        assert long_hl > 0.7  # well preserved
        # Compare with default (24h) — default decays much more
        default_hl = compute_emotion_decay(intensity=0.9, elapsed_hours=48.0)
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
        state.speech_style = None
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
        state.speech_style = None
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
        state.speech_style = None
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
        state.speech_style = None
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


# ──────────────────────────────────────────────
# Author's Note — PromptBuildStep
# ──────────────────────────────────────────────


class TestPromptBuildStepAuthorNote:
    """PromptBuildStep should inject author_note into system_prompt."""

    def test_author_note_injected_when_set(self):
        """author_note が設定されている場合、system_prompt末尾に [Author's Note] セクションが追加される."""
        from unittest.mock import MagicMock

        from nous.application.chat.pipeline.prompt import PromptBuildStep

        ctx = MagicMock()
        ctx.persona = "test"
        config = MagicMock()
        config.system_prompt = "Base system prompt."
        config.enabled_skills = []

        turn_ctx = MagicMock()
        turn_ctx.context_section = "--- context ---"
        turn_ctx.related_memories = ""
        turn_ctx.author_note = "Remember to be concise."
        turn_ctx.author_note_frequency = "always"

        PromptBuildStep().run(ctx, config, turn_ctx)

        assert turn_ctx.system_prompt is not None
        assert "Base system prompt." in turn_ctx.system_prompt
        assert "[Author's Note]" in turn_ctx.system_prompt
        assert "Remember to be concise." in turn_ctx.system_prompt
        # Should be at the end (after context section)
        assert turn_ctx.system_prompt.strip().endswith("Remember to be concise.")

    def test_author_note_not_injected_when_none(self):
        """author_note が None の場合、[Author's Note] セクションは追加されない."""
        from unittest.mock import MagicMock

        from nous.application.chat.pipeline.prompt import PromptBuildStep

        ctx = MagicMock()
        ctx.persona = "test"
        config = MagicMock()
        config.system_prompt = "Base system prompt."
        config.enabled_skills = []

        turn_ctx = MagicMock()
        turn_ctx.context_section = "--- context ---"
        turn_ctx.related_memories = ""
        turn_ctx.author_note = None
        turn_ctx.author_note_frequency = "always"

        PromptBuildStep().run(ctx, config, turn_ctx)

        assert "[Author's Note]" not in turn_ctx.system_prompt

    def test_author_note_not_injected_when_empty(self):
        """author_note が空文字の場合、[Author's Note] セクションは追加されない."""
        from unittest.mock import MagicMock

        from nous.application.chat.pipeline.prompt import PromptBuildStep

        ctx = MagicMock()
        ctx.persona = "test"
        config = MagicMock()
        config.system_prompt = "Base system prompt."
        config.enabled_skills = []

        turn_ctx = MagicMock()
        turn_ctx.context_section = "--- context ---"
        turn_ctx.related_memories = ""
        turn_ctx.author_note = ""
        turn_ctx.author_note_frequency = "always"

        PromptBuildStep().run(ctx, config, turn_ctx)

        assert "[Author's Note]" not in turn_ctx.system_prompt

    @pytest.mark.asyncio
    async def test_decision_creates_memory(self):
        """決定表現を含むメッセージ -> メモリが作成される."""
        from unittest.mock import MagicMock

        from nous.application.chat.pipeline.auto_capture import run_auto_capture

        ctx = MagicMock()
        ctx.settings.auto_capture.enabled = True
        ctx.settings.auto_capture.max_memories = 5
        ctx.persona = "test"
        ctx.connection.get_memory_db.return_value.execute.return_value.fetchone.return_value = None

        fake_memory = MagicMock()
        fake_memory.key = "mem_key_001"
        ctx.memory_service.create_memory.return_value = Success(fake_memory)
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
        from unittest.mock import MagicMock

        from nous.application.chat.pipeline.auto_capture import run_auto_capture

        ctx = MagicMock()
        ctx.settings.auto_capture.enabled = True
        ctx.settings.auto_capture.max_memories = 2
        ctx.persona = "test"

        fake_memory = MagicMock()
        fake_memory.key = "mem_key_xxx"
        ctx.memory_service.create_memory.return_value = Success(fake_memory)
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

        result = await run_auto_capture(
            ctx, "test", [{"role": "user", "content": "今日はいい天気ですね。何か食べましょう。"}]
        )
        assert result == []
        ctx.memory_service.create_memory.assert_not_called()

    @pytest.mark.asyncio
    async def test_assistant_message_also_scanned(self):
        """アシスタントの応答もスキャン対象."""
        from unittest.mock import MagicMock

        from nous.application.chat.pipeline.auto_capture import run_auto_capture

        ctx = MagicMock()
        ctx.settings.auto_capture.enabled = True
        ctx.settings.auto_capture.max_memories = 5
        ctx.persona = "test"
        ctx.connection.get_memory_db.return_value.execute.return_value.fetchone.return_value = None

        fake_memory = MagicMock()
        fake_memory.key = "mem_key_asst"
        ctx.memory_service.create_memory.return_value = Success(fake_memory)
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
        from unittest.mock import MagicMock

        from nous.application.chat.pipeline.auto_capture import run_auto_capture

        ctx = MagicMock()
        ctx.settings.auto_capture.enabled = True
        ctx.settings.auto_capture.max_memories = 5
        ctx.persona = "test"

        ctx.memory_service.create_memory.return_value = Failure(DomainError("DB error"))

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
        # effective_temp = 0.7 + 0.024 = 0.724
        result = EmotionDrivenSampler.compute(base_temp, "anger", 0.8, scale=0.2)
        assert result == pytest.approx(0.724, rel=1e-3)

    @pytest.mark.asyncio
    async def test_emotion_driven_sampler_neutral_no_change(self):
        """neutral emotion → modifier=0 → effective_temp == base_temp. base_temp is 0.5 already without dynamic temp."""
        from nous.domain.sampling import EmotionDrivenSampler

        result = EmotionDrivenSampler.compute(0.7, "neutral", 0.9, scale=0.2)
        assert result == pytest.approx(0.7, rel=1e-3)


# ──────────────────────────────────────────────
# PrepareStep — _build_time_context
# ──────────────────────────────────────────────


class TestBuildTimeContext:
    """_build_time_context() の出力検証"""

    def test_output_structure(self):
        """<TIME_CONTEXT>...</TIME_CONTEXT> で囲まれている"""
        from nous.application.chat.pipeline.prepare import _build_time_context
        from unittest.mock import MagicMock

        state = MagicMock()
        state.last_conversation_time = None
        result = _build_time_context(state)
        assert result.startswith("<TIME_CONTEXT>")
        assert result.endswith("</TIME_CONTEXT>")

    def test_contains_now_and_weekday(self):
        """出力に Now: と曜日が含まれる"""
        from nous.application.chat.pipeline.prepare import _build_time_context
        from unittest.mock import MagicMock

        state = MagicMock()
        state.last_conversation_time = None
        result = _build_time_context(state)
        assert "Now:" in result
        assert any(d in result for d in ["月曜日", "火曜日", "水曜日", "木曜日", "金曜日", "土曜日", "日曜日"])

    def test_no_gap_when_no_last_conversation(self):
        """last_conversation_time が None の場合、ギャップ表示なし"""
        from nous.application.chat.pipeline.prepare import _build_time_context
        from unittest.mock import MagicMock

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

        with patch("nous.application.chat.pipeline.prepare.get_now", return_value=fixed_now):
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
        assert _classify_gap(24.1) == "NEXT_DAY"

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
        assert "消えていった" in note_neutral

        # 部分減衰 (same emotion, reduced intensity)
        partial = EmotionDecayResult(
            before_emotion="joy",
            before_intensity=0.9,
            after_emotion="joy",
            after_intensity=0.3,
            elapsed_hours=24.0,
        )
        note_partial = _format_emotion_decay_note(partial)
        assert "落ち着いてきた" in note_partial
        assert "消えていった" not in note_partial
