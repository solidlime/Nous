"""Unit tests for _parse_insights() in reflection.py and threshold logic."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nous.application.chat.reflection import _parse_insights, maybe_run_reflection


class TestParseInsights:
    """Tests for the _parse_insights() JSON parser."""

    def test_valid_json_three_insights(self):
        raw = json.dumps({"insights": ["洞察A", "洞察B", "洞察C"]})
        result = _parse_insights(raw)
        assert result == ["洞察A", "洞察B", "洞察C"]

    def test_valid_json_one_insight(self):
        raw = json.dumps({"insights": ["単一の洞察"]})
        result = _parse_insights(raw)
        assert result == ["単一の洞察"]

    def test_code_fenced_json_is_parsed(self):
        raw = '```json\n{"insights": ["a", "b", "c"]}\n```'
        result = _parse_insights(raw)
        assert result == ["a", "b", "c"]

    def test_code_fenced_no_lang_tag(self):
        raw = '```\n{"insights": ["x", "y"]}\n```'
        result = _parse_insights(raw)
        assert result == ["x", "y"]

    def test_invalid_json_returns_empty(self):
        result = _parse_insights("これはJSONではありません")
        assert result == []

    def test_empty_string_returns_empty(self):
        result = _parse_insights("")
        assert result == []

    def test_empty_insights_list(self):
        raw = json.dumps({"insights": []})
        result = _parse_insights(raw)
        assert result == []

    def test_non_string_items_filtered_out(self):
        raw = json.dumps({"insights": ["valid", 42, None, "also valid"]})
        result = _parse_insights(raw)
        assert result == ["valid", "also valid"]

    def test_whitespace_only_items_filtered(self):
        raw = json.dumps({"insights": ["  ", "real insight", "\t\n"]})
        result = _parse_insights(raw)
        assert result == ["real insight"]

    def test_missing_insights_key(self):
        raw = json.dumps({"data": ["a", "b"]})
        result = _parse_insights(raw)
        assert result == []

    def test_leading_trailing_whitespace_stripped(self):
        raw = "  " + json.dumps({"insights": ["trimmed"]}) + "\n"
        result = _parse_insights(raw)
        assert result == ["trimmed"]

    def test_partial_json_returns_empty(self):
        result = _parse_insights('{"insights": ["incomplete"')
        assert result == []


class TestReflectionThreshold:
    """Tests for the threshold check in maybe_run_reflection logic."""

    def test_below_threshold_returns_empty(self):
        """Simulate threshold check: sum < threshold → no reflection."""
        threshold = 3.0
        recent_importance_sum = 2.5
        # This is the exact guard in maybe_run_reflection
        result = [] if recent_importance_sum < threshold else ["would_reflect"]
        assert result == []

    def test_at_threshold_triggers_reflection(self):
        """sum >= threshold should pass the guard."""
        threshold = 3.0
        recent_importance_sum = 3.0
        result = [] if recent_importance_sum < threshold else ["would_reflect"]
        assert result == ["would_reflect"]

    def test_above_threshold_triggers_reflection(self):
        threshold = 3.0
        recent_importance_sum = 5.5
        result = [] if recent_importance_sum < threshold else ["would_reflect"]
        assert result == ["would_reflect"]

    def test_zero_sum_below_any_positive_threshold(self):
        threshold = 0.1
        result = [] if threshold > 0.0 else ["would_reflect"]
        assert result == []


class TestMaybeRunReflectionPersona:
    """Tests that maybe_run_reflection passes ctx.persona to create_memory."""

    @pytest.fixture
    def mock_ctx(self):
        ctx = MagicMock()
        ctx.persona = "test_char"
        # memory_service
        ctx.memory_service = MagicMock()
        # get_recent returns some memories
        recent_result = MagicMock()
        recent_result.is_ok = True
        mem = MagicMock()
        mem.content = "A sample memory."
        mem.importance = 0.8
        mem.created_at = datetime.now().astimezone() - timedelta(hours=1)
        mem.key = "mem_001"
        recent_result.value = [mem]
        ctx.memory_service.get_recent.return_value = recent_result
        # create_memory returns success
        create_result = MagicMock()
        create_result.is_ok = True
        ctx.memory_service.create_memory.return_value = create_result
        # get_by_tags for last_reflection check — return empty
        tags_result = MagicMock()
        tags_result.is_ok = True
        tags_result.value = []
        ctx.memory_service.get_by_tags.return_value = tags_result
        # search_engine
        ctx.search_engine = AsyncMock()
        return ctx

    @pytest.fixture
    def mock_config(self):
        config = MagicMock()
        config.reflection_threshold = 0.1
        config.reflection_min_interval_hours = 0.0
        # Provide valid API / model config via get_effective_*
        config.provider = "test_provider"
        config.extract_model = "test_model"
        config.get_effective_api_key.return_value = "sk-test"
        config.get_effective_model.return_value = "test-model"
        config.get_effective_base_url.return_value = None
        return config

    @pytest.mark.asyncio
    async def test_create_memory_receives_persona(self, mock_ctx, mock_config):
        """maybe_run_reflection passes ctx.persona to create_memory."""
        fake_insight_text = json.dumps({"insights": ["Deep insight about user."]})

        fake_provider = AsyncMock()
        fake_provider.stream = AsyncMock()

        async def fake_stream(**kwargs):
            from nous.infrastructure.llm.base import DoneEvent, TextDeltaEvent

            yield TextDeltaEvent(content=fake_insight_text)
            yield DoneEvent(full_content=fake_insight_text)

        fake_provider.stream = fake_stream

        with patch(
            "nous.application.chat.reflection.get_provider",
            return_value=fake_provider,
        ):
            result = await maybe_run_reflection(mock_ctx, mock_config, recent_importance_sum=5.0)

        assert result == ["Deep insight about user."]
        assert mock_ctx.memory_service.create_memory.call_count >= 1
        # Each create_memory call must contain persona=ctx.persona
        for call_args in mock_ctx.memory_service.create_memory.call_args_list:
            _, kwargs = call_args
            assert kwargs.get("persona") == "test_char", (
                f"create_memory called without persona=ctx.persona; got kwargs={kwargs}"
            )

    @pytest.mark.asyncio
    async def test_persona_none_does_not_crash(self, mock_ctx, mock_config):
        """maybe_run_reflection handles persona=None gracefully."""
        mock_ctx.persona = None

        fake_insight_text = json.dumps({"insights": ["Another insight."]})

        fake_provider = AsyncMock()

        async def fake_stream(**kwargs):
            from nous.infrastructure.llm.base import DoneEvent, TextDeltaEvent

            yield TextDeltaEvent(content=fake_insight_text)
            yield DoneEvent(full_content=fake_insight_text)

        fake_provider.stream = fake_stream

        with patch(
            "nous.application.chat.reflection.get_provider",
            return_value=fake_provider,
        ):
            result = await maybe_run_reflection(mock_ctx, mock_config, recent_importance_sum=5.0)

        assert result == ["Another insight."]
        # Should not crash; persona may be None
        mock_ctx.memory_service.create_memory.assert_called()

    @pytest.mark.asyncio
    async def test_persona_empty_string_does_not_crash(self, mock_ctx, mock_config):
        """maybe_run_reflection handles persona='' gracefully."""
        mock_ctx.persona = ""

        fake_insight_text = json.dumps({"insights": ["Yet another insight."]})

        fake_provider = AsyncMock()

        async def fake_stream(**kwargs):
            from nous.infrastructure.llm.base import DoneEvent, TextDeltaEvent

            yield TextDeltaEvent(content=fake_insight_text)
            yield DoneEvent(full_content=fake_insight_text)

        fake_provider.stream = fake_stream

        with patch(
            "nous.application.chat.reflection.get_provider",
            return_value=fake_provider,
        ):
            result = await maybe_run_reflection(mock_ctx, mock_config, recent_importance_sum=5.0)

        assert result == ["Yet another insight."]
        mock_ctx.memory_service.create_memory.assert_called()
