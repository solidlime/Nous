"""Tests for CHARACTER_ADHERENCE_BLOCK and its injection in PromptBuildStep."""

from __future__ import annotations

from unittest.mock import MagicMock

from nous.application.chat.pipeline.prompt import CHARACTER_ADHERENCE_BLOCK, PromptBuildStep


def test_block_contains_anti_sycophancy_and_fewshot():
    assert "アシスタント" in CHARACTER_ADHERENCE_BLOCK
    assert "反論" in CHARACTER_ADHERENCE_BLOCK or "拒否" in CHARACTER_ADHERENCE_BLOCK
    assert "ユーザー:" in CHARACTER_ADHERENCE_BLOCK  # few-shot 例


def test_block_formats_with_persona():
    rendered = CHARACTER_ADHERENCE_BLOCK.format(persona="ヘルタ")
    assert "ヘルタ" in rendered


def test_prompt_build_appends_block():
    """PromptBuildStep.run が system prompt 末尾にブロックを追加すること。"""
    ctx = MagicMock()
    ctx.persona = "test_persona"

    config = MagicMock()
    config.system_prompt = "あなたはアシスタントです。"
    config.enabled_skills = []

    turn_ctx = MagicMock()
    turn_ctx.context_section = ""
    turn_ctx.related_memories = ""
    turn_ctx.author_note = None
    turn_ctx.system_prompt = ""
    turn_ctx.skills_raw = []

    step = PromptBuildStep()
    step.run(ctx, config, turn_ctx)

    assert CHARACTER_ADHERENCE_BLOCK.format(persona="test_persona") in turn_ctx.system_prompt
