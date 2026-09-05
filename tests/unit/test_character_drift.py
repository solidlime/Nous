"""Tests for character-drift accumulation (spec: 2026-09-05-drift-memory-design)."""

from __future__ import annotations

from nous.application.chat.memory_prompts import _MEMORY_LLM_PROMPT, _build_drift_section


class TestDriftSection:
    def test_none_returns_empty(self):
        assert _build_drift_section(None) == ""

    def test_violation_renders_type_and_detail(self):
        section = _build_drift_section({"violation": "tone", "detail": "一人称が俺だった"})
        assert "tone" in section
        assert "一人称が俺だった" in section

    def test_template_has_placeholder(self):
        assert "{drift_section}" in _MEMORY_LLM_PROMPT

    def test_template_has_drift_rule(self):
        assert "character_drift" in _MEMORY_LLM_PROMPT
