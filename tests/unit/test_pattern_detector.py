"""Unit tests for maybe_run_mental_model() with mocked ctx and config."""

from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nous.application.chat.pattern_detector import (
    _MENTAL_MODEL_META_TAG,
    _TYPE_TAGS,
    _get_last_abstraction_at,
    _has_new_memories_since,
    _parse_models,
    _store_last_abstraction_at,
    maybe_run_mental_model,
)
from nous.domain.memory.entities import Memory
from nous.domain.shared.result import Success
from nous.infrastructure.llm.base import DoneEvent, TextDeltaEvent

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_memory(
    key: str, content: str, tags: list[str] | None = None, created_at: datetime | None = None, importance: float = 0.5
) -> Memory:
    now = created_at or datetime.now()
    return Memory(
        key=key,
        content=content,
        created_at=now,
        updated_at=now,
        importance=importance,
        tags=tags or [],
    )


def _make_mock_ctx():
    """Build a mock AppContext with mocked memory_service."""
    ctx = MagicMock()
    ctx.persona = "test_persona"

    memory_service = MagicMock()
    memory_service.create_memory = AsyncMock(return_value=Success(MagicMock()))
    memory_service.delete_memory = MagicMock(return_value=Success(None))
    memory_service.get_by_tags = MagicMock(return_value=Success([]))

    ctx.memory_service = memory_service
    ctx.search_engine = MagicMock()
    return ctx


def _set_get_by_tags(ctx, mapping: dict[str, list[Memory]]) -> None:
    """Helper to configure get_by_tags side effect.

    mapping keys are type tag strings (e.g. 'decision'), values are memory lists.
    For _MENTAL_MODEL_META_TAG, use the key '_meta'.
    """

    def side_effect(tags: list[str]) -> Success:
        if tags == [_MENTAL_MODEL_META_TAG]:
            return Success(mapping.get("_meta", []))
        if tags and len(tags) == 1:
            return Success(mapping.get(tags[0], []))
        return Success([])

    ctx.memory_service.get_by_tags.side_effect = side_effect


def _make_mock_config(
    api_key: str = "test-key",
    model: str = "gpt-4o",
    base_url: str = "",
    provider: str = "openai",
    mental_model_enabled: bool = True,
    mental_model_min_samples: int = 3,
):
    config = MagicMock()
    config.get_effective_api_key = MagicMock(return_value=api_key)
    config.get_effective_model = MagicMock(return_value=model)
    config.get_effective_base_url = MagicMock(return_value=base_url)
    config.provider = provider
    config.extract_model = ""
    config.mental_model_enabled = mental_model_enabled
    config.mental_model_min_samples = mental_model_min_samples
    return config


# ---------------------------------------------------------------------------
# Tests for helper functions
# ---------------------------------------------------------------------------


class TestGetLastAbstractionAt:
    """Tests for _get_last_abstraction_at()."""

    def test_no_meta_tag_returns_none(self):
        ctx = _make_mock_ctx()
        result = _get_last_abstraction_at(ctx, "decision")
        assert result is None

    def test_returns_datetime_when_found(self):
        ts = datetime(2025, 6, 1, 12, 0, 0)
        meta_mem = _make_memory(
            key="meta_1", content=f"last_decision_abstraction: {ts.isoformat()}", tags=[_MENTAL_MODEL_META_TAG]
        )
        ctx = _make_mock_ctx()
        _set_get_by_tags(ctx, {"_meta": [meta_mem]})
        result = _get_last_abstraction_at(ctx, "decision")
        assert result is not None
        assert result.isoformat() == ts.isoformat()

    def test_returns_none_for_unrelated_type(self):
        meta_mem = _make_memory(
            key="meta_1", content="last_decision_abstraction: 2025-06-01T12:00:00", tags=[_MENTAL_MODEL_META_TAG]
        )
        ctx = _make_mock_ctx()
        _set_get_by_tags(ctx, {"_meta": [meta_mem]})
        result = _get_last_abstraction_at(ctx, "preference")
        assert result is None

    def test_invalid_isoformat_returns_none(self):
        meta_mem = _make_memory(
            key="meta_1", content="last_decision_abstraction: not-a-date", tags=[_MENTAL_MODEL_META_TAG]
        )
        ctx = _make_mock_ctx()
        _set_get_by_tags(ctx, {"_meta": [meta_mem]})
        result = _get_last_abstraction_at(ctx, "decision")
        assert result is None


class TestStoreLastAbstractionAt:
    """Tests for _store_last_abstraction_at()."""

    @pytest.mark.asyncio
    async def test_stores_meta_memory(self):
        ctx = _make_mock_ctx()
        _set_get_by_tags(ctx, {"_meta": []})
        ts = datetime.now().astimezone()
        await _store_last_abstraction_at(ctx, "decision", ts)
        ctx.memory_service.create_memory.assert_called_once()

    @pytest.mark.asyncio
    async def test_replaces_existing_meta(self):
        old_meta = _make_memory(
            key="old_meta", content="last_decision_abstraction: 2024-01-01T00:00:00", tags=[_MENTAL_MODEL_META_TAG]
        )
        ctx = _make_mock_ctx()
        _set_get_by_tags(ctx, {"_meta": [old_meta]})
        ts = datetime.now().astimezone()
        await _store_last_abstraction_at(ctx, "decision", ts)
        ctx.memory_service.delete_memory.assert_called_once_with("old_meta")
        ctx.memory_service.create_memory.assert_called_once()

    @pytest.mark.asyncio
    async def test_replaces_only_matching_type(self):
        old_meta_1 = _make_memory(
            key="meta_1", content="last_decision_abstraction: 2024-01-01T00:00:00", tags=[_MENTAL_MODEL_META_TAG]
        )
        old_meta_2 = _make_memory(
            key="meta_2", content="last_preference_abstraction: 2024-01-01T00:00:00", tags=[_MENTAL_MODEL_META_TAG]
        )
        ctx = _make_mock_ctx()
        _set_get_by_tags(ctx, {"_meta": [old_meta_1, old_meta_2]})
        ts = datetime.now().astimezone()
        await _store_last_abstraction_at(ctx, "decision", ts)
        ctx.memory_service.delete_memory.assert_called_once_with("meta_1")


class TestHasNewMemoriesSince:
    """Tests for _has_new_memories_since()."""

    def test_no_previous_abstraction_returns_true(self):
        ctx = _make_mock_ctx()
        _set_get_by_tags(ctx, {"_meta": []})
        old_mem = _make_memory("k1", "test", created_at=datetime(2020, 1, 1))
        assert _has_new_memories_since(ctx, "decision", [old_mem]) is True

    def test_new_memory_returns_true(self):
        now = datetime.now().astimezone()
        meta_mem = _make_memory(
            key="meta",
            content=f"last_decision_abstraction: {(now - timedelta(hours=1)).isoformat()}",
            tags=[_MENTAL_MODEL_META_TAG],
        )
        new_mem = _make_memory("k1", "new content", created_at=now)
        ctx = _make_mock_ctx()
        _set_get_by_tags(ctx, {"_meta": [meta_mem]})
        assert _has_new_memories_since(ctx, "decision", [new_mem]) is True

    def test_only_old_memories_returns_false(self):
        now = datetime.now().astimezone()
        meta_mem = _make_memory(
            key="meta", content=f"last_decision_abstraction: {now.isoformat()}", tags=[_MENTAL_MODEL_META_TAG]
        )
        old_mem = _make_memory("k1", "old content", created_at=now - timedelta(hours=2))
        ctx = _make_mock_ctx()
        _set_get_by_tags(ctx, {"_meta": [meta_mem]})
        assert _has_new_memories_since(ctx, "decision", [old_mem]) is False


# ---------------------------------------------------------------------------
# Tests for maybe_run_mental_model
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestMaybeRunMentalModel:
    """Integration-style tests for maybe_run_mental_model() with mocks."""

    async def test_empty_when_no_type_group_has_enough_memories(self):
        """No type group has >= min_samples → returns []."""
        ctx = _make_mock_ctx()
        config = _make_mock_config()
        # Each type tag returns 1 memory (below min_samples=3)
        mapping: dict[str, list[Memory]] = {"_meta": []}
        now = datetime.now()
        for tag in _TYPE_TAGS:
            mapping[tag] = [_make_memory(f"{tag}_1", f"{tag} content", created_at=now)]
        _set_get_by_tags(ctx, mapping)

        result = await maybe_run_mental_model(ctx, config)
        assert result == []

    async def test_empty_when_llm_not_configured(self):
        """No API key → returns []."""
        ctx = _make_mock_ctx()
        config = _make_mock_config(api_key="", model="")

        now = datetime.now()
        mapping: dict[str, list[Memory]] = {"_meta": []}
        for tag in _TYPE_TAGS:
            mapping[tag] = [_make_memory(f"{tag}_{i}", f"{tag} content {i}", created_at=now) for i in range(3)]
        _set_get_by_tags(ctx, mapping)

        result = await maybe_run_mental_model(ctx, config)
        assert result == []

    async def test_skipped_when_disabled(self):
        """mental_model_enabled=False → returns []."""
        ctx = _make_mock_ctx()
        config = _make_mock_config(mental_model_enabled=False)

        now = datetime.now()
        mapping: dict[str, list[Memory]] = {"_meta": []}
        for tag in _TYPE_TAGS:
            mapping[tag] = [_make_memory(f"{tag}_{i}", f"{tag} content {i}", created_at=now) for i in range(3)]
        _set_get_by_tags(ctx, mapping)

        result = await maybe_run_mental_model(ctx, config)
        assert result == []
        # create_memory should NOT have been called
        ctx.memory_service.create_memory.assert_not_called()

    async def test_calls_llm_and_stores_results(self):
        """When a type group has >= min_samples, calls LLM and stores results."""
        ctx = _make_mock_ctx()
        config = _make_mock_config()

        # Build 3 memories of type "decision"
        now = datetime.now()
        decision_mems = [
            _make_memory(
                f"dec_{i}",
                f"decision content {i}",
                tags=["decision"],
                created_at=now - timedelta(hours=i),
                importance=0.7,
            )
            for i in range(3)
        ]

        mapping: dict[str, list[Memory]] = {"_meta": []}
        for tag in _TYPE_TAGS:
            if tag == "decision":
                mapping[tag] = decision_mems
            else:
                mapping[tag] = [_make_memory(f"{tag}_1", f"{tag} content", created_at=now)]
        _set_get_by_tags(ctx, mapping)

        # Mock LLM provider
        mock_provider = AsyncMock()

        async def mock_stream(**kwargs):
            yield TextDeltaEvent(content='{"models": ["pattern1", "pattern2"]}')
            yield DoneEvent()

        mock_provider.stream = mock_stream

        with patch("nous.application.chat.pattern_detector.get_provider", return_value=mock_provider):
            result = await maybe_run_mental_model(ctx, config)

        assert len(result) == 2
        assert "pattern1" in result
        assert "pattern2" in result

        # Verify create_memory was called for each model
        assert ctx.memory_service.create_memory.call_count >= 2

        # Verify meta tag was stored
        meta_calls = [
            call
            for call in ctx.memory_service.create_memory.call_args_list
            if call[1].get("tags") == [_MENTAL_MODEL_META_TAG]
        ]
        assert len(meta_calls) == 1
        assert "last_decision_abstraction:" in meta_calls[0][1]["content"]

    async def test_does_not_reprocess_already_abstracted_groups(self):
        """Groups with no new memories since last abstraction are skipped."""
        ctx = _make_mock_ctx()
        config = _make_mock_config()

        now = datetime.now().astimezone()

        decision_mems = [
            _make_memory(
                f"dec_{i}",
                f"decision content {i}",
                tags=["decision"],
                created_at=now - timedelta(hours=2),
                importance=0.7,
            )
            for i in range(3)
        ]

        # Meta memory says we already abstracted AFTER those memories were created
        meta_mem = _make_memory(
            key="meta_1",
            content=f"last_decision_abstraction: {(now - timedelta(hours=1)).isoformat()}",
            tags=[_MENTAL_MODEL_META_TAG],
        )

        mapping: dict[str, list[Memory]] = {"_meta": [meta_mem]}
        for tag in _TYPE_TAGS:
            if tag == "decision":
                mapping[tag] = decision_mems
            else:
                mapping[tag] = [_make_memory(f"{tag}_1", f"{tag} content", created_at=now)]
        _set_get_by_tags(ctx, mapping)

        result = await maybe_run_mental_model(ctx, config)
        assert result == []

    async def test_empty_result_on_llm_failure(self):
        """When LLM call fails, returns [] gracefully."""
        ctx = _make_mock_ctx()
        config = _make_mock_config()

        now = datetime.now()
        decision_mems = [
            _make_memory(
                f"dec_{i}",
                f"decision content {i}",
                tags=["decision"],
                created_at=now - timedelta(hours=i),
                importance=0.7,
            )
            for i in range(3)
        ]

        mapping: dict[str, list[Memory]] = {"_meta": []}
        for tag in _TYPE_TAGS:
            if tag == "decision":
                mapping[tag] = decision_mems
            else:
                mapping[tag] = [_make_memory(f"{tag}_1", f"{tag} content", created_at=now)]
        _set_get_by_tags(ctx, mapping)

        # Mock provider init to raise
        with patch("nous.application.chat.pattern_detector.get_provider", side_effect=Exception("LLM unavailable")):
            result = await maybe_run_mental_model(ctx, config)
        assert result == []

    async def test_multiple_type_groups_processed(self):
        """Multiple type groups with >= min_samples are all processed."""
        ctx = _make_mock_ctx()
        config = _make_mock_config()

        now = datetime.now()
        mapping: dict[str, list[Memory]] = {"_meta": []}
        for tag in _TYPE_TAGS:
            mapping[tag] = [
                _make_memory(
                    f"{tag}_{i}", f"{tag} content {i}", tags=[tag], created_at=now - timedelta(hours=i), importance=0.6
                )
                for i in range(3)
            ]
        _set_get_by_tags(ctx, mapping)

        mock_provider = AsyncMock()

        async def mock_stream(**kwargs):
            yield TextDeltaEvent(content='{"models": ["pattern_a", "pattern_b"]}')
            yield DoneEvent()

        mock_provider.stream = mock_stream

        with patch("nous.application.chat.pattern_detector.get_provider", return_value=mock_provider):
            result = await maybe_run_mental_model(ctx, config)

        # 5 type groups × 2 models = 10 total
        assert len(result) == 10

        # Verify meta tags were stored for all 5 types
        meta_calls = [
            call
            for call in ctx.memory_service.create_memory.call_args_list
            if call[1].get("tags") == [_MENTAL_MODEL_META_TAG]
        ]
        assert len(meta_calls) == 5

    async def test_get_by_tags_empty_skips_type(self):
        """When get_by_tags returns empty result for a type tag, that type is skipped."""
        ctx = _make_mock_ctx()
        config = _make_mock_config()

        # Only _meta returns empty; other types return not enough (1 memory)
        mapping: dict[str, list[Memory]] = {"_meta": []}
        now = datetime.now()
        for tag in _TYPE_TAGS:
            mapping[tag] = [_make_memory(f"{tag}_1", "content", created_at=now)]
        # Override 'decision' to return failure (not .is_ok)
        ctx.memory_service.get_by_tags.side_effect = None

        def side_effect(tags):
            if tags == [_MENTAL_MODEL_META_TAG]:
                return Success([])
            if tags == ["decision"]:
                from nous.domain.shared.errors import SearchError
                from nous.domain.shared.result import Failure

                return Failure(SearchError("db error"))
            return Success(mapping.get(tags[0], []))

        ctx.memory_service.get_by_tags.side_effect = side_effect

        result = await maybe_run_mental_model(ctx, config)
        assert result == []

    async def test_llm_stream_exception_handled(self):
        """When LLM stream raises an exception, it should be caught and skipped."""
        ctx = _make_mock_ctx()
        config = _make_mock_config()

        now = datetime.now()
        decision_mems = [
            _make_memory(
                f"dec_{i}",
                f"decision content {i}",
                tags=["decision"],
                created_at=now - timedelta(hours=i),
                importance=0.7,
            )
            for i in range(3)
        ]
        mapping: dict[str, list[Memory]] = {"_meta": []}
        for tag in _TYPE_TAGS:
            if tag == "decision":
                mapping[tag] = decision_mems
            else:
                mapping[tag] = [_make_memory(f"{tag}_1", f"{tag} content", created_at=now)]
        _set_get_by_tags(ctx, mapping)

        mock_provider = AsyncMock()

        async def failing_stream(**kwargs):
            raise RuntimeError("LLM stream failure")
            yield  # pragma: no cover

        mock_provider.stream = failing_stream

        with patch("nous.application.chat.pattern_detector.get_provider", return_value=mock_provider):
            result = await maybe_run_mental_model(ctx, config)
        assert result == []

    async def test_no_models_parsed_skips_type(self):
        """When LLM returns empty/unparseable models, the type is skipped."""
        ctx = _make_mock_ctx()
        config = _make_mock_config()

        now = datetime.now()
        decision_mems = [
            _make_memory(
                f"dec_{i}",
                f"decision content {i}",
                tags=["decision"],
                created_at=now - timedelta(hours=i),
                importance=0.7,
            )
            for i in range(3)
        ]
        mapping: dict[str, list[Memory]] = {"_meta": []}
        for tag in _TYPE_TAGS:
            if tag == "decision":
                mapping[tag] = decision_mems
            else:
                mapping[tag] = [_make_memory(f"{tag}_1", f"{tag} content", created_at=now)]
        _set_get_by_tags(ctx, mapping)

        mock_provider = AsyncMock()

        async def empty_stream(**kwargs):
            yield TextDeltaEvent(content="invalid non-json text")
            yield DoneEvent()

        mock_provider.stream = empty_stream

        with patch("nous.application.chat.pattern_detector.get_provider", return_value=mock_provider):
            result = await maybe_run_mental_model(ctx, config)
        assert result == []

    async def test_outer_exception_on_create_memory(self):
        """When create_memory raises, the outer exception handler catches it."""
        ctx = _make_mock_ctx()
        config = _make_mock_config(api_key="test-key", model="gpt-4o")

        now = datetime.now()
        decision_mems = [
            _make_memory(
                f"dec_{i}",
                f"decision content {i}",
                tags=["decision"],
                created_at=now - timedelta(hours=i),
                importance=0.7,
            )
            for i in range(3)
        ]
        mapping: dict[str, list[Memory]] = {"_meta": []}
        for tag in _TYPE_TAGS:
            if tag == "decision":
                mapping[tag] = decision_mems
            else:
                mapping[tag] = [_make_memory(f"{tag}_1", f"{tag} content", created_at=now)]
        _set_get_by_tags(ctx, mapping)

        # Make create_memory raise to trigger outer exception handler
        ctx.memory_service.create_memory.side_effect = RuntimeError("create failed")

        mock_provider = AsyncMock()

        async def ok_stream(**kwargs):
            yield TextDeltaEvent(content='{"models": ["pattern1"]}')
            yield DoneEvent()

        mock_provider.stream = ok_stream

        with patch("nous.application.chat.pattern_detector.get_provider", return_value=mock_provider):
            result = await maybe_run_mental_model(ctx, config)
        # Exception is caught, type is skipped, result should be empty
        assert result == []


# ──────────────────────────────────────────────
# Tests for _parse_models
# ──────────────────────────────────────────────


class TestParseModels:
    """Tests for _parse_models()."""

    def test_empty_text_returns_empty_list(self):
        assert _parse_models("") == []

    def test_whitespace_text_returns_empty_list(self):
        assert _parse_models("   ") == []

    def test_valid_json(self):
        result = _parse_models('{"models": ["model1", "model2"]}')
        assert result == ["model1", "model2"]

    def test_json_with_empty_models(self):
        result = _parse_models('{"models": []}')
        assert result == []

    def test_json_with_non_string_items(self):
        result = _parse_models('{"models": ["valid", 123, null]}')
        assert result == ["valid"]

    def test_markdown_code_block(self):
        text = '```json\n{"models": ["m1", "m2"]}\n```'
        result = _parse_models(text)
        assert result == ["m1", "m2"]

    def test_markdown_code_block_trailing_backticks_on_last_line(self):
        """JSON code block where last line is just '```' works."""
        text = '```\n{"models": ["m1"]}\n```'
        result = _parse_models(text)
        assert result == ["m1"]

    def test_invalid_json_returns_empty(self):
        result = _parse_models("not json at all")
        assert result == []

    def test_parse_non_dict_json(self):
        result = _parse_models('["list", "not", "dict"]')
        assert result == []
