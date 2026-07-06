"""Tests for importance labels and critical goal protection."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nous.domain.memory.entities import Memory
from nous.domain.shared.result import Success
from nous.domain.value_objects import importance_to_label
from nous.infrastructure.llm.base import DoneEvent, TextDeltaEvent


class TestImportanceToLabel:
    """Boundary tests for importance_to_label conversion."""

    def test_critical_at_1_0(self):
        """importance=1.0 → critical."""
        assert importance_to_label(1.0) == "critical"

    def test_critical_at_0_9(self):
        """importance=0.9 → critical (lower bound)."""
        assert importance_to_label(0.9) == "critical"

    def test_high_below_critical(self):
        """importance=0.899 → high (just below critical)."""
        assert importance_to_label(0.899) == "high"

    def test_high_at_0_7(self):
        """importance=0.7 → high (lower bound)."""
        assert importance_to_label(0.7) == "high"

    def test_normal_below_high(self):
        """importance=0.699 → normal (just below high)."""
        assert importance_to_label(0.699) == "normal"

    def test_normal_at_0_4(self):
        """importance=0.4 → normal (lower bound)."""
        assert importance_to_label(0.4) == "normal"

    def test_low_below_normal(self):
        """importance=0.399 → low (just below normal)."""
        assert importance_to_label(0.399) == "low"

    def test_low_at_0_0(self):
        """importance=0.0 → low (lower bound)."""
        assert importance_to_label(0.0) == "low"

    def test_low_negative(self):
        """Negative importance → low (clamped elsewhere, but should handle gracefully)."""
        assert importance_to_label(-0.1) == "low"


# ===========================================================================
# Housekeeping critical goal protection
# ===========================================================================


class TestHousekeepingCriticalProtection:
    """Critical goals (importance >= 0.9) must not be auto-cancelled by housekeeping."""

    @pytest.mark.asyncio
    async def test_housekeeping_skips_critical_goal(self):
        """A critical goal (importance=0.95) should NOT be cancelled by housekeeping."""
        from nous.application.chat.memory_llm import run_context_housekeeping

        mock_ctx = MagicMock()
        mock_ctx.persona = "test_persona"

        # Mock memory_service.get_by_tags to return a critical goal
        critical_mem = Memory(
            key="goal_critical",
            content="This is a critical goal",
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
            tags=["goal", "active"],
            importance=0.95,
        )
        mock_ctx.memory_service.get_by_tags.return_value = Success([critical_mem])

        # Mock equipment_service.search_items
        mock_ctx.equipment_service.search_items.return_value = Success([])

        # Mock the LLM provider to return a response that includes the critical goal
        json_response = '{"cancel_goals":["goal_critical"],"cancel_promises":[],"remove_items":[]}'
        mock_provider_instance = AsyncMock()

        async def mock_stream(*args, **kwargs):
            yield TextDeltaEvent(content=json_response)
            yield DoneEvent(full_content=json_response)

        mock_provider_instance.stream = mock_stream

        mock_config = MagicMock()
        mock_config.get_effective_api_key.return_value = "test-key"
        mock_config.extract_model = "test-model"
        mock_config.provider = "anthropic"
        mock_config.get_effective_base_url.return_value = None

        with patch("nous.application.chat.memory_llm.get_provider", return_value=mock_provider_instance):
            result = await run_context_housekeeping(mock_ctx, mock_config)

        # The critical goal should be in the response but NOT in cancelled_goals
        assert isinstance(result, dict)
        assert "cancelled_goals" in result
        assert "goal_critical" not in result["cancelled_goals"], (
            f"Critical goal was cancelled! cancelled_goals={result['cancelled_goals']}"
        )

        # Verify update_memory was NOT called for the critical goal
        for call_args in mock_ctx.memory_service.update_memory.call_args_list:
            args, kwargs = call_args
            if args and args[0] == "goal_critical":
                pytest.fail(f"update_memory was called for critical goal: {call_args}")

    @pytest.mark.asyncio
    async def test_housekeeping_allows_low_importance_cancel(self):
        """A low-importance goal (importance=0.3) SHOULD be cancelled by housekeeping."""
        from nous.application.chat.memory_llm import run_context_housekeeping

        mock_ctx = MagicMock()
        mock_ctx.persona = "test_persona"

        normal_mem = Memory(
            key="goal_normal",
            content="A normal goal",
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
            tags=["goal", "active"],
            importance=0.3,
        )
        mock_ctx.memory_service.get_by_tags.return_value = Success([normal_mem])
        mock_ctx.memory_service.update_memory.return_value = Success(None)
        mock_ctx.equipment_service.search_items.return_value = Success([])

        json_response = '{"cancel_goals":["goal_normal"],"cancel_promises":[],"remove_items":[]}'
        mock_provider_instance = AsyncMock()

        async def mock_stream(*args, **kwargs):
            yield TextDeltaEvent(content=json_response)
            yield DoneEvent(full_content=json_response)

        mock_provider_instance.stream = mock_stream

        mock_config = MagicMock()
        mock_config.get_effective_api_key.return_value = "test-key"
        mock_config.extract_model = "test-model"
        mock_config.provider = "anthropic"
        mock_config.get_effective_base_url.return_value = None

        with patch("nous.application.chat.memory_llm.get_provider", return_value=mock_provider_instance):
            result = await run_context_housekeeping(mock_ctx, mock_config)

        assert isinstance(result, dict)
        assert "goal_normal" in result.get("cancelled_goals", []), f"Low-importance goal was not cancelled: {result}"

    @pytest.mark.asyncio
    async def test_housekeeping_skips_critical_interpersonal_goal(self):
        """A critical interpersonal goal (importance=0.92) should NOT be cancelled."""
        from nous.application.chat.memory_llm import run_context_housekeeping

        mock_ctx = MagicMock()
        mock_ctx.persona = "test_persona"

        self_goal = Memory(
            key="goal_self",
            content="Self goal",
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
            tags=["goal", "active"],
            importance=0.5,
        )
        interpersonal_critical = Memory(
            key="goal_inter_critical",
            content="Critical interpersonal goal",
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
            tags=["goal", "active", "interpersonal"],
            importance=0.92,
        )

        # First call = self goals, second call = interpersonal goals
        mock_ctx.memory_service.get_by_tags.side_effect = [
            Success([self_goal]),
            Success([interpersonal_critical]),
        ]
        mock_ctx.equipment_service.search_items.return_value = Success([])

        json_response = '{"cancel_goals":["goal_self"],"cancel_promises":["goal_inter_critical"],"remove_items":[]}'
        mock_provider_instance = AsyncMock()

        async def mock_stream(*args, **kwargs):
            yield TextDeltaEvent(content=json_response)
            yield DoneEvent(full_content=json_response)

        mock_provider_instance.stream = mock_stream

        mock_config = MagicMock()
        mock_config.get_effective_api_key.return_value = "test-key"
        mock_config.extract_model = "test-model"
        mock_config.provider = "anthropic"
        mock_config.get_effective_base_url.return_value = None

        with patch("nous.application.chat.memory_llm.get_provider", return_value=mock_provider_instance):
            result = await run_context_housekeeping(mock_ctx, mock_config)

        # Self goal should be cancelled (importance=0.5, not critical)
        assert "goal_self" in result.get("cancelled_goals", [])

        # Critical interpersonal goal should NOT be cancelled
        assert "goal_inter_critical" not in result.get("cancelled_promises", []), (
            f"Critical interpersonal goal was cancelled! {result}"
        )

        # Verify update_memory was NOT called for the critical interpersonal goal
        for call_args in mock_ctx.memory_service.update_memory.call_args_list:
            args, kwargs = call_args
            if args and args[0] == "goal_inter_critical":
                pytest.fail(f"update_memory was called for critical interpersonal goal: {call_args}")
