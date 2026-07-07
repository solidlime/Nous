"""Tests for the language-agnostic ReflectionEngine (Park et al. 2023)."""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from nous.application.chat.reflection import ReflectionEngine
from nous.domain.memory.reflection_schema import (
    OUTPUT_FORMAT,
    REFLECTION_SCHEMA,
    ReflectionQuestion,
)


class TestReflectionSchema:
    """reflection_schema.py の基本構造テスト."""

    def test_all_questions_have_required_fields(self):
        assert len(REFLECTION_SCHEMA) >= 1
        for q in REFLECTION_SCHEMA:
            assert isinstance(q, ReflectionQuestion)
            assert isinstance(q.id, str) and q.id
            assert isinstance(q.intent, str) and q.intent
            assert isinstance(q.output_key, str) and q.output_key

    def test_reflection_schema_ids_are_unique(self):
        ids = [q.id for q in REFLECTION_SCHEMA]
        assert len(ids) == len(set(ids))

    def test_output_format_is_valid_json(self):
        # OUTPUT_FORMAT must be JSON-serializable
        raw = json.dumps(OUTPUT_FORMAT)
        parsed = json.loads(raw)
        assert parsed["type"] == "json_array"
        assert "items" in parsed
        assert "insight" in parsed["items"]
        assert "evidence_keys" in parsed["items"]
        assert "confidence" in parsed["items"]


class TestReflectionEngine:
    """ReflectionEngine のユニットテスト."""

    # ---- fixtures -----------------------------------------------------

    @pytest.fixture
    def engine(self):
        return ReflectionEngine()

    @pytest.fixture
    def mock_memory(self):
        mem = MagicMock()
        mem.content = "The user mentioned they enjoy reading science fiction."
        mem.key = "mem_001"
        return mem

    @pytest.fixture
    def recent_memories(self, mock_memory):
        """Return 15 memories (above MIN_MEMORIES threshold)."""
        return [mock_memory for _ in range(15)]

    @pytest.fixture
    def mock_memory_service(self, recent_memories):
        svc = MagicMock()
        result = MagicMock()
        result.is_ok = True
        result.value = recent_memories
        svc.get_recent.return_value = result

        def create_memory_side_effect(**kwargs):
            r = MagicMock()
            r.is_ok = True
            r.value = {"key": "mem_new"}
            return r

        svc.create_memory = MagicMock(side_effect=create_memory_side_effect)
        return svc

    @pytest.fixture
    def mock_llm(self):
        provider = MagicMock()

        async def stream_iter(**kwargs):
            from nous.infrastructure.llm.base import DoneEvent, TextDeltaEvent

            response = json.dumps([
                {
                    "insight": "The user consistently prefers sci-fi themes.",
                    "evidence_keys": ["mem_001"],
                    "confidence": 0.85,
                },
                {
                    "insight": "There is a pattern of interest in futuristic technology.",
                    "evidence_keys": ["mem_001"],
                    "confidence": 0.72,
                },
            ])
            yield TextDeltaEvent(content=response)
            yield DoneEvent(full_content=response)

        provider.stream = stream_iter
        return provider

    # ---- tests --------------------------------------------------------

    @pytest.mark.asyncio
    async def test_empty_memories_returns_empty(self, engine):
        """get_recent returns empty → reflect() returns []."""
        svc = MagicMock()
        result = MagicMock()
        result.is_ok = True
        result.value = []
        svc.get_recent.return_value = result

        llm = MagicMock()
        result_list = await engine.reflect("test_persona", svc, llm)
        assert result_list == []

    @pytest.mark.asyncio
    async def test_below_threshold_skips(self, engine):
        """Fewer than MIN_MEMORIES memories → reflect() returns []."""
        svc = MagicMock()
        result = MagicMock()
        result.is_ok = True
        result.value = [MagicMock() for _ in range(5)]  # only 5
        svc.get_recent.return_value = result

        llm = MagicMock()
        result_list = await engine.reflect("test_persona", svc, llm)
        assert result_list == []

    @pytest.mark.asyncio
    async def test_reflect_returns_insights(self, engine, mock_memory_service, mock_llm):
        """Normal flow: valid insights returned."""
        results = await engine.reflect("test_persona", mock_memory_service, mock_llm)
        assert len(results) >= 1
        assert results[0]["insight"] == "The user consistently prefers sci-fi themes."
        assert results[0]["confidence"] == 0.85
        # Verify create_memory was called
        assert mock_memory_service.create_memory.call_count >= 1

    @pytest.mark.asyncio
    async def test_llm_failure_returns_empty(self, engine, mock_memory_service):
        """LLM raises an exception → reflect() returns []."""
        bad_llm = MagicMock()
        bad_llm.stream.side_effect = RuntimeError("LLM unavailable")
        results = await engine.reflect("test_persona", mock_memory_service, bad_llm)
        assert results == []

    @pytest.mark.asyncio
    async def test_system_message_includes_persona(self, engine):
        """_build_system_message includes persona name."""
        memories = [MagicMock(content=f"memory {i}") for i in range(12)]
        msg = engine._build_system_message("Alice", memories)
        assert "Alice" in msg
        assert "Reflection tasks" in msg
        assert "Recent memories" in msg
        assert "memory 0" in msg

    def test_parse_insights_valid_array(self, engine):
        raw = json.dumps([
            {"insight": "a", "evidence_keys": [], "confidence": 0.5},
            {"insight": "b", "evidence_keys": [], "confidence": 0.6},
        ])
        result = engine._parse_insights_json(raw)
        assert len(result) == 2

    def test_parse_insights_with_insights_key(self, engine):
        raw = json.dumps({
            "insights": [
                {"insight": "x", "evidence_keys": [], "confidence": 0.9},
            ],
        })
        result = engine._parse_insights_json(raw)
        assert len(result) == 1
        assert result[0]["insight"] == "x"

    def test_parse_insights_empty(self, engine):
        assert engine._parse_insights_json("") == []
        assert engine._parse_insights_json("not json") == []
        assert engine._parse_insights_json("[]") == []

    def test_parse_insights_code_fenced(self, engine):
        raw = "```json\n[{\"insight\": \"fenced\"}]\n```"
        result = engine._parse_insights_json(raw)
        assert len(result) == 1
        assert result[0]["insight"] == "fenced"

    def test_output_format_is_valid_json_schema(self):
        """OUTPUT_FORMAT must be serializable and self-consistent."""
        raw = json.dumps(OUTPUT_FORMAT)
        parsed = json.loads(raw)
        items = parsed["items"]
        assert "insight" in items
        assert "evidence_keys" in items
        assert "confidence" in items
        # confidence should be a float range
        assert "float" in items["confidence"]


class TestReflectionEngineEdgeCases:
    """Edge cases and error handling."""

    @pytest.fixture
    def engine(self):
        return ReflectionEngine()

    @pytest.mark.asyncio
    async def test_memory_service_error(self, engine):
        """get_recent returns Failure → reflect() returns []."""
        svc = MagicMock()
        result = MagicMock()
        result.is_ok = False
        svc.get_recent.return_value = result

        llm = MagicMock()
        results = await engine.reflect("p", svc, llm)
        assert results == []

    @pytest.mark.asyncio
    async def test_create_memory_failure_does_not_crash(self, engine):
        """create_memory fails but reflect should still return successful ones."""
        svc = MagicMock()
        ok_result = MagicMock()
        ok_result.is_ok = True
        ok_result.value = [MagicMock(content=f"mem {i}") for i in range(12)]
        svc.get_recent.return_value = ok_result

        # First create_memory succeeds, second fails
        def create_side(**kwargs):
            r = MagicMock()
            r.is_ok = kwargs.get("content", "").startswith("First")
            return r

        svc.create_memory = MagicMock(side_effect=create_side)

        llm_instance = MagicMock()

        async def stream_ok(**kwargs):
            from nous.infrastructure.llm.base import DoneEvent, TextDeltaEvent

            yield TextDeltaEvent(
                content=json.dumps([
                    {"insight": "First insight", "evidence_keys": [], "confidence": 0.8},
                    {"insight": "Second insight", "evidence_keys": [], "confidence": 0.7},
                ])
            )
            yield DoneEvent(full_content="")

        llm_instance.stream = stream_ok
        results = await engine.reflect("p", svc, llm_instance)
        assert len(results) == 1  # only the one that succeeded

    def test_custom_schema(self):
        """Engine accepts a custom schema."""
        custom_schema = [
            ReflectionQuestion(id="test_q", intent="test intent", output_key="result"),
        ]
        eng = ReflectionEngine(schema=custom_schema)
        assert eng._schema == custom_schema

    def test_default_schema(self):
        """Engine uses REFLECTION_SCHEMA by default."""
        eng = ReflectionEngine()
        assert eng._schema is REFLECTION_SCHEMA
