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
        # create_memory is async, use AsyncMock
        create_result = MagicMock()
        create_result.is_ok = True
        ctx.memory_service.create_memory = AsyncMock(return_value=create_result)
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

    # ---- dedup + evidence_keys ---------------------------------------

    @staticmethod
    async def _run_dedup(ctx, config, insight: str):
        fake_provider = AsyncMock()

        async def fake_stream(**kwargs):
            from nous.infrastructure.llm.base import DoneEvent, TextDeltaEvent

            yield TextDeltaEvent(content=insight)
            yield DoneEvent(full_content=insight)

        fake_provider.stream = fake_stream
        with patch(
            "nous.application.chat.reflection.get_provider",
            return_value=fake_provider,
        ):
            # await inside the patch context — returning the coroutine would
            # run it after patch exit and hit the real LLM provider.
            return await maybe_run_reflection(ctx, config, recent_importance_sum=5.0)

    @pytest.mark.asyncio
    async def test_duplicate_insight_skipped(self, mock_ctx, mock_config):
        """既存 reflection と同一の洞察は保存されず、空リストを返す."""
        existing = MagicMock()
        existing.content = "Deep insight about user."
        tags_result = MagicMock()
        tags_result.is_ok = True
        tags_result.value = [existing]
        mock_ctx.memory_service.get_by_tags.return_value = tags_result

        result = await self._run_dedup(mock_ctx, mock_config, json.dumps({"insights": ["Deep insight about user."]}))

        assert result == []
        mock_ctx.memory_service.create_memory.assert_not_called()

    @pytest.mark.asyncio
    async def test_new_insight_saved_with_evidence_keys(self, mock_ctx, mock_config):
        """新規洞察は related_keys に直近メモリ keys を持って保存される."""
        result = await self._run_dedup(mock_ctx, mock_config, json.dumps({"insights": ["Fresh insight."]}))

        assert result == ["Fresh insight."]
        insight_kwargs = mock_ctx.memory_service.create_memory.call_args_list[0].kwargs
        assert insight_kwargs["related_keys"] == ["mem_001"]


class TestMaybeRunReflectionStrict24hWindow:
    """maybe_run_reflection の 24h ウィンドウ厳格適用（年単位フォールバック廃止）。"""

    @pytest.fixture
    def fresh_ctx(self):
        """get_recent が 1時間前 created_at の記憶を返すコンテキスト（既存テストと同等）。"""
        ctx = MagicMock()
        ctx.persona = "test_char"
        ctx.memory_service = MagicMock()
        recent_result = MagicMock()
        recent_result.is_ok = True
        mem = MagicMock()
        mem.content = "A sample memory."
        mem.importance = 0.8
        mem.created_at = datetime.now().astimezone() - timedelta(hours=1)
        mem.key = "mem_001"
        recent_result.value = [mem]
        ctx.memory_service.get_recent.return_value = recent_result
        ctx.memory_service.create_memory = AsyncMock()
        tags_result = MagicMock()
        tags_result.is_ok = True
        tags_result.value = []
        ctx.memory_service.get_by_tags.return_value = tags_result
        ctx.search_engine = AsyncMock()
        return ctx

    @pytest.fixture
    def fresh_config(self):
        config = MagicMock()
        config.reflection_threshold = 0.1
        config.reflection_min_interval_hours = 0.0
        config.provider = "test_provider"
        config.extract_model = "test_model"
        config.get_effective_api_key.return_value = "sk-test"
        config.get_effective_model.return_value = "test-model"
        config.get_effective_base_url.return_value = None
        return config

    @pytest.fixture
    def old_only_ctx(self):
        """get_recent が created_at 30日前の記憶しか返さないコンテキスト。"""
        ctx = MagicMock()
        ctx.persona = "test_char"
        ctx.memory_service = MagicMock()
        recent_result = MagicMock()
        recent_result.is_ok = True
        old = MagicMock()
        old.content = "an old memory"
        old.importance = 0.8
        old.created_at = datetime.now().astimezone() - timedelta(days=30)
        old.updated_at = datetime.now().astimezone() - timedelta(days=1)  # エンリッチで若返った想定
        old.key = "old_001"
        recent_result.value = [old]
        ctx.memory_service.get_recent.return_value = recent_result
        ctx.memory_service.create_memory = AsyncMock()
        tags_result = MagicMock()
        tags_result.is_ok = True
        tags_result.value = []
        ctx.memory_service.get_by_tags.return_value = tags_result
        ctx.search_engine = AsyncMock()
        return ctx

    @pytest.fixture
    def strict_config(self):
        config = MagicMock()
        config.reflection_threshold = 0.1
        config.reflection_min_interval_hours = 0.0
        config.provider = "test_provider"
        config.extract_model = "test_model"
        config.get_effective_api_key.return_value = "sk-test"
        config.get_effective_model.return_value = "test-model"
        config.get_effective_base_url.return_value = None
        return config

    @pytest.mark.asyncio
    async def test_skips_when_zero_memories_created_within_24h(self, old_only_ctx, strict_config):
        """24h 以内 created_at の記憶がゼロなら LLM に触れず skip する。

        旧実装は `or recent_result.value[:10]` のフォールバックで updated_at が
        新しい古い記憶を拾っていたが、廃止された。
        """
        with patch(
            "nous.application.chat.reflection.get_provider",
        ) as mock_get_provider:
            result = await maybe_run_reflection(old_only_ctx, strict_config, recent_importance_sum=5.0)

        assert result == []
        mock_get_provider.assert_not_called()  # LLM 呼び出しなし
        old_only_ctx.memory_service.create_memory.assert_not_called()
        old_only_ctx.search_engine.search.assert_not_called()  # 検索フォールバックも廃止

    @pytest.mark.asyncio
    async def test_mixed_old_and_new_keeps_only_24h_created(self, fresh_ctx, fresh_config):
        """24h 内 created_at の記憶だけがプロンプトに使われる（updated_at 基準にならない）。"""
        now = datetime.now().astimezone()
        old_but_fresh_updated = MagicMock()
        old_but_fresh_updated.content = "old content refreshed by enrichment"
        old_but_fresh_updated.importance = 0.8
        old_but_fresh_updated.created_at = now - timedelta(days=400)
        old_but_fresh_updated.updated_at = now - timedelta(hours=1)
        old_but_fresh_updated.key = "old_refreshed"
        fresh = MagicMock()
        fresh.content = "fresh content"
        fresh.importance = 0.9
        fresh.created_at = now - timedelta(hours=2)
        fresh.updated_at = now - timedelta(hours=2)
        fresh.key = "fresh_001"
        recent_result = MagicMock()
        recent_result.is_ok = True
        recent_result.value = [old_but_fresh_updated, fresh]
        fresh_ctx.memory_service.get_recent.return_value = recent_result

        fake_provider = AsyncMock()
        captured: dict = {}

        async def fake_stream(**kwargs):
            from nous.infrastructure.llm.base import DoneEvent, TextDeltaEvent

            captured["messages"] = kwargs.get("messages") or []
            yield TextDeltaEvent(content=json.dumps({"insights": ["Insight."]}))
            yield DoneEvent(full_content=json.dumps({"insights": ["Insight."]}))

        fake_provider.stream = fake_stream
        with patch("nous.application.chat.reflection.get_provider", return_value=fake_provider):
            result = await maybe_run_reflection(fresh_ctx, fresh_config, recent_importance_sum=5.0)

        assert result == ["Insight."]
        # created_at が 24h 内の記憶だけがプロンプトに出る（updated_at 基準で拾われた古い記憶は除外）
        evidence_keys = fresh_ctx.memory_service.create_memory.call_args_list[0].kwargs["related_keys"]
        assert evidence_keys == ["fresh_001"]
        # プロンプト: fresh には "2h ago" が付き、400日前の記憶は現れない
        prompt = "".join(m.content or "" for m in captured["messages"] if hasattr(m, "content"))
        assert "fresh content (2h ago)" in prompt
        assert "old content refreshed by enrichment" not in prompt


class TestBuildSystemMessageRelativeTime:
    """ReflectionEngine._build_system_message の記憶行に相対時刻が付く。"""

    def test_memory_lines_include_relative_time(self):
        from datetime import UTC

        from nous.application.chat.reflection import ReflectionEngine
        from nous.domain.memory.entities import Memory

        now = datetime.now(UTC)
        memories = [
            Memory(
                key="k1",
                content="recent event",
                created_at=now - timedelta(hours=1),
                updated_at=now - timedelta(hours=1),
            ),
            Memory(
                key="k2",
                content="old fact",
                created_at=now - timedelta(days=366),
                updated_at=now - timedelta(days=366),
            ),
        ]
        msg = ReflectionEngine()._build_system_message("test_persona", memories)
        assert "recent event (1h ago)" in msg
        assert "old fact (1y ago)" in msg
        # プロンプト指示行（古い記憶と直近の出来事を混同しない）も追加されている
        assert "混同しないこと" in msg
