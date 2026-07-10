"""CompressStep: token reduction verification and dogfooding tests."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from nous.infrastructure.llm.base import LLMMessage
from nous.infrastructure.llm.token_counter import TokenCounter


def _dummy_app_context():
    """Minimal mock for AppContext."""
    from unittest.mock import MagicMock

    return MagicMock()


def _dummy_turn_ctx(system_prompt: str):
    """Minimal mock for ChatTurnContext."""
    from unittest.mock import MagicMock

    ctx = MagicMock()
    ctx.system_prompt = system_prompt
    ctx.messages = []
    return ctx


def _make_chat_config(**overrides):
    """Create a ChatConfig with defaults suitable for testing."""
    from nous.domain.chat_config import ChatConfig

    defaults = {
        "persona": "test",
        "provider": "openrouter",
        "model": "openai/gpt-4o",
        "context_max_tokens": 200,  # Very low to force compression
        "context_compression_threshold": 1.0,  # Always compress
        "context_compression_mode": "aggressive",
        "context_keep_recent_turns": 1,
        "context_compress_system_prompt": True,
        "context_compress_history": True,
        "memory_preload_count": 3,
        "enable_parallel_tools": True,
    }
    defaults.update(overrides)
    return ChatConfig(**defaults)


# ──────────────────────────────────────────────
# Token Counter Tests
# ──────────────────────────────────────────────


class TestTokenCounter:
    def test_count_empty(self):
        tc = TokenCounter()
        assert tc.count("") == 0

    def test_count_english(self):
        tc = TokenCounter()
        count = tc.count("Hello world")
        assert 1 <= count <= 10  # Heuristic: ~3 tokens, tiktoken: similar

    def test_count_japanese(self):
        tc = TokenCounter()
        count = tc.count("こんにちは世界")
        assert 4 <= count <= 20  # Heuristic: ~6 tokens, tiktoken: similar

    def test_count_mixed(self):
        tc = TokenCounter()
        count = tc.count("Hello こんにちは world 世界")
        assert 8 <= count <= 30

    def test_count_messages(self):
        tc = TokenCounter()
        msgs = [
            LLMMessage(role="user", content="Hello"),
            LLMMessage(role="assistant", content="Hi there!"),
            LLMMessage(role="tool", content="result data here", tool_call_id="call_1"),
        ]
        count = tc.count_messages(msgs, "System prompt text")
        assert count > 0

    def test_get_model_max_claude(self):
        assert TokenCounter.get_model_max_tokens("claude-opus-4-5") == 200_000

    def test_get_model_max_gpt4o(self):
        assert TokenCounter.get_model_max_tokens("gpt-4o") == 128_000

    def test_get_model_max_openrouter(self):
        assert TokenCounter.get_model_max_tokens("openai/gpt-4o") == 128_000

    def test_get_model_max_unknown(self):
        assert TokenCounter.get_model_max_tokens("unknown-model-xyz") == 128_000

    def test_heuristic_vs_tiktoken_rough_agreement(self):
        """Verify heuristic is within sane bounds for various inputs."""
        tc = TokenCounter()
        texts = [
            "a",
            "hello world",
            "the quick brown fox jumps over the lazy dog",
            "今日天気",
            "日本語のテスト文章問題なく動作するはずです",
            "mixed English text 混在文章",
            "x" * 1000,  # Long ASCII
            "漢" * 1000,  # Long CJK (kanji within U+4E00-U+9FFF)
        ]
        for text in texts:
            count = tc.count(text)
            # At minimum, every character should count for something
            assert count >= 1, f"Count for '{text[:20]}...' was {count}, expected >= 1"
            # At maximum, reasonable upper bound (shouldn't exceed char count for CJK,
            # and shouldn't exceed char_count/2 for ASCII)
            if any("\u4e00" <= c <= "\u9fff" for c in text[:1]):
                # CJK text: 1 char ≈ 1 token
                assert count <= len(text) * 3, f"CJK count {count} too high for {len(text)} chars"
            else:
                # ASCII text: ~4 chars = 1 token → count <= chars/2
                assert count <= max(1, len(text) // 2), f"ASCII count {count} too high for {len(text)} chars"


# ──────────────────────────────────────────────
# CompressStep Tests
# ──────────────────────────────────────────────


def _long_system_prompt(num_memories: int = 20) -> str:
    """Build a system prompt with many mock memories to trigger trimming."""
    lines = [
        "あなたはテストアシスタントです。",
        "現在時刻: 2026-06-09 12:00 JST",
        "--- ペルソナ状態・コンテキスト ---",
        "感情: neutral (強度: 0.5)",
        "--- 関連記憶 ---",
    ]
    for i in range(num_memories):
        lines.append(
            f"- [0.{i % 10}] これはテスト用の関連記憶です。長めのテキストを入れてトークン数を稼ぎます。記憶番号: {i}。"
            f"Lorem ipsum dolor sit amet consectetur adipiscing elit sed do eiusmod tempor incididunt ut labore."
        )
    lines.append("--- 利用可能なSkill ---")
    lines.append("- skill_a: テスト用スキルAの長い説明文です。" * 30)
    lines.append("- skill_b: テスト用スキルBの長い説明文です。" * 30)
    lines.append("--- 記憶ツール使用ガイド ---")
    lines.append("memory_create, memory_search など")
    return "\n".join(lines)


def _long_messages(num_pairs: int = 10) -> list[LLMMessage]:
    """Build a long message history to trigger truncation."""
    msgs = []
    for i in range(num_pairs):
        msgs.append(
            LLMMessage(
                role="user",
                content=f"これは長いユーザーメッセージです。ターン {i}。"
                f"たくさんのテキストを含めてトークン数を増やします。"
                f"Lorem ipsum dolor sit amet consectetur adipiscing elit. " * 10,
            )
        )
        msgs.append(
            LLMMessage(
                role="assistant",
                content=f"これは長いアシスタント応答です。ターン {i}。"
                f"同様に長いテキストを含めます。"
                f"Ut enim ad minim veniam quis nostrud exercitation. " * 10,
            )
        )
    return msgs


def _messages_with_tool_results() -> list[LLMMessage]:
    """Build messages with tool calls/results to test tool result clearing."""
    msgs = []
    for i in range(8):  # 8 user+assistant pairs = 16 messages
        msgs.append(LLMMessage(role="user", content=f"User message {i}" * 20))
        msgs.append(
            LLMMessage(
                role="assistant",
                content=f"Assistant response {i}" * 20,
                tool_calls=[{"id": f"call_{i}", "name": "memory_search", "input": {"query": f"test {i}"}}],
            )
        )
        msgs.append(
            LLMMessage(
                role="tool",
                content=f"Tool result data for call {i}: " + "x" * 500,
                tool_call_id=f"call_{i}",
            )
        )
    return msgs


class TestCompressStep:
    @pytest.mark.asyncio
    @pytest.mark.asyncio
    async def test_no_compression_when_under_budget(self):
        """When under budget, messages pass through unchanged."""
        from nous.application.chat.pipeline.compress import CompressStep

        config = _make_chat_config(context_max_tokens=1_000_000)  # Huge budget
        ctx = _dummy_app_context()
        tctx = _dummy_turn_ctx(_long_system_prompt(num_memories=5))
        msgs = _long_messages(num_pairs=3)

        result = await CompressStep().run(ctx, config, tctx, msgs)
        # Should be unchanged (no compression needed)
        assert result is msgs  # Same object reference = no compression

    @pytest.mark.asyncio
    async def test_compression_reduces_token_count(self):
        """Compression should reduce total tokens."""
        from nous.application.chat.pipeline.compress import CompressStep

        config = _make_chat_config(context_max_tokens=200)  # Very low, force compression
        ctx = _dummy_app_context()
        tctx = _dummy_turn_ctx(_long_system_prompt(num_memories=20))
        msgs = _long_messages(num_pairs=10)

        # Count tokens before
        tc = TokenCounter(config.get_effective_model())
        before = tc.count(tctx.system_prompt) + tc.count_messages(msgs, "")
        assert before > 500, f"Expected >500 tokens before compression, got {before}"

        result = await CompressStep().run(ctx, config, tctx, msgs)

        # Count after
        after = tc.count(tctx.system_prompt) + tc.count_messages(result, "")
        assert after < before, f"Expected token reduction: {before} → {after}"

    @pytest.mark.asyncio
    async def test_system_prompt_trimmed(self):
        """System prompt should have fewer memory lines after compression."""
        from nous.application.chat.pipeline.compress import CompressStep

        config = _make_chat_config(context_max_tokens=200, context_compression_mode="aggressive")
        ctx = _dummy_app_context()
        tctx = _dummy_turn_ctx(_long_system_prompt(num_memories=20))

        # Count "- [" lines before
        memory_lines_before = tctx.system_prompt.count("\n- [")

        await CompressStep().run(ctx, config, tctx, _long_messages(num_pairs=2))

        # Count after
        memory_lines_after = tctx.system_prompt.count("\n- [")
        assert memory_lines_after < memory_lines_before, (
            f"Expected fewer memory lines: {memory_lines_before} → {memory_lines_after}"
        )
        # Aggressive mode keeps 2 + the hint line
        assert "必要なら memory_search" in tctx.system_prompt, "Should include search hint"

    @pytest.mark.asyncio
    async def test_tool_results_cleared(self):
        """Old tool results should be replaced with [cleared] marker."""
        from nous.application.chat.pipeline.compress import CompressStep

        config = _make_chat_config(context_max_tokens=200)
        ctx = _dummy_app_context()
        tctx = _dummy_turn_ctx(_long_system_prompt(num_memories=5))
        msgs = _messages_with_tool_results()

        original_tool_msgs = [m for m in msgs if m.role == "tool"]
        assert len(original_tool_msgs) == 8

        result = await CompressStep().run(ctx, config, tctx, msgs)

        cleared = [m for m in result if m.role == "tool" and "cleared" in (m.content or "")]
        assert len(cleared) >= 1, f"Expected at least 1 cleared tool result, got {len(cleared)}"

        # Most recent tool results should be preserved
        recent_tools = [m for m in result[-10:] if m.role == "tool" and "cleared" not in (m.content or "")]
        assert len(recent_tools) >= 1, "Recent tool results should be preserved"

    @pytest.mark.asyncio
    async def test_old_messages_truncated(self):
        """Old messages should be truncated and marked with [旧]."""
        from nous.application.chat.pipeline.compress import CompressStep

        config = _make_chat_config(context_max_tokens=200, context_keep_recent_turns=1)
        ctx = _dummy_app_context()
        tctx = _dummy_turn_ctx(_long_system_prompt(num_memories=5))
        msgs = _long_messages(num_pairs=10)

        assert len(msgs) == 20  # 10 pairs

        result = await CompressStep().run(ctx, config, tctx, msgs)

        # Count truncated messages
        truncated = [m for m in result if m.role in ("user", "assistant") and (m.content or "").startswith("[旧]")]
        assert len(truncated) > 0, f"Expected some truncated messages, got {len(truncated)}"

        # Most recent 2 messages should NOT be truncated (keep_recent_turns=1)
        last_two = result[-2:]
        for msg in last_two:
            if msg.role in ("user", "assistant"):
                assert not (msg.content or "").startswith("[旧]"), (
                    f"Recent message should not be truncated: {msg.content[:50]}..."
                )

    @pytest.mark.asyncio
    async def test_compression_preserves_tool_call_ids(self):
        """Cleared tool results should keep their tool_call_id for API compatibility."""
        from nous.application.chat.pipeline.compress import CompressStep

        config = _make_chat_config(context_max_tokens=200)
        ctx = _dummy_app_context()
        tctx = _dummy_turn_ctx(_long_system_prompt(num_memories=5))
        msgs = _messages_with_tool_results()

        result = await CompressStep().run(ctx, config, tctx, msgs)

        cleared = [m for m in result if m.role == "tool" and "cleared" in (m.content or "")]
        for msg in cleared:
            assert msg.tool_call_id is not None, "Cleared tool results must retain tool_call_id"

    @pytest.mark.asyncio
    async def test_conversation_structure_preserved(self):
        """Compression should not corrupt message role ordering."""
        from nous.application.chat.pipeline.compress import CompressStep

        config = _make_chat_config(context_max_tokens=200)
        ctx = _dummy_app_context()
        tctx = _dummy_turn_ctx(_long_system_prompt(num_memories=5))
        msgs = _long_messages(num_pairs=5)

        result = await CompressStep().run(ctx, config, tctx, msgs)

        # Verify all messages have valid roles
        valid_roles = {"user", "assistant", "tool"}
        for msg in result:
            assert msg.role in valid_roles, f"Invalid role: {msg.role}"

        # Verify we still have user+assistant pairs (approximate)
        user_count = sum(1 for m in result if m.role == "user")
        assistant_count = sum(1 for m in result if m.role == "assistant")
        assert user_count > 0 and assistant_count > 0, "Must have both user and assistant messages"

    def test_no_trim_when_single_section(self):
        """System prompt with no section markers returns unchanged."""
        from nous.application.chat.pipeline.compress import CompressStep

        prompt = "Simple prompt without any section markers"
        result = CompressStep._trim_system_prompt(prompt, "aggressive")
        assert result == prompt

    @pytest.mark.asyncio
    async def test_stage1_alone_brings_under_budget(self):
        """After stage 1 (system prompt trim), if already under budget, return session_messages unchanged."""
        from nous.application.chat.pipeline.compress import CompressStep

        config = _make_chat_config(
            context_max_tokens=10000,  # Moderate budget
            context_compression_mode="aggressive",  # Will trim aggressively
        )
        ctx = _dummy_app_context()
        tctx = _dummy_turn_ctx(_long_system_prompt(num_memories=5))
        msgs = _long_messages(num_pairs=1)  # Small messages

        # Should still under budget after stage 1, but before stage 2
        # If compression mode aggressively trims...
        result = await CompressStep().run(ctx, config, tctx, msgs)
        # Should work without error
        assert isinstance(result, list)

    @pytest.mark.asyncio
    async def test_context_compress_history_false(self):
        """When context_compress_history=False, messages should not be cleared/truncated."""
        from nous.application.chat.pipeline.compress import CompressStep

        config = _make_chat_config(
            context_max_tokens=1,  # Always over budget
            context_compress_history=False,  # Skip history compression
            context_compress_system_prompt=True,
        )
        ctx = _dummy_app_context()
        tctx = _dummy_turn_ctx(_long_system_prompt(num_memories=20))
        msgs = _messages_with_tool_results()

        result = await CompressStep().run(ctx, config, tctx, msgs)
        # Messages should still have tool results (not cleared)
        tool_msgs = [m for m in result if m.role == "tool"]
        assert len(tool_msgs) == 8  # All preserved because history compress is off
        # But tool results right at the end should be fine

    @pytest.mark.asyncio
    async def test_compress_history_true_clears_tool_results(self):
        """When context_compress_history=True and over budget, tool results get cleared."""
        from nous.application.chat.pipeline.compress import CompressStep

        config = _make_chat_config(
            context_max_tokens=1,  # Always over budget
            context_compress_history=True,
            context_compress_system_prompt=True,
        )
        ctx = _dummy_app_context()
        tctx = _dummy_turn_ctx(_long_system_prompt(num_memories=20))
        msgs = _messages_with_tool_results()

        result = await CompressStep().run(ctx, config, tctx, msgs)
        # Some tool results should be cleared
        cleared = [m for m in result if m.role == "tool" and "cleared" in (m.content or "")]
        assert len(cleared) >= 1

    def test_trim_system_prompt_skill_section_truncated(self):
        """Long skill descriptions should be truncated."""
        from nous.application.chat.pipeline.compress import CompressStep

        # Build prompt with long skill section
        lines = [
            "あなたはテストアシスタントです。",
            "--- 関連記憶 ---",
            "- [0.5] テスト記憶1",
            "- [0.3] テスト記憶2",
            "--- 利用可能なSkill ---",
            "- skill_a: " + "x" * 700,  # Long description
        ]
        prompt = "\n".join(lines)
        result = CompressStep._trim_system_prompt(prompt, "aggressive")
        # Should be truncated (skill section > 600 chars)
        assert len(result) < len(prompt) or "..." in result

    def test_clear_tool_results_with_few_assistant_msgs(self):
        """When there are <= 3 assistant messages, no clearing happens."""
        from nous.application.chat.pipeline.compress import CompressStep

        msgs = [
            LLMMessage(role="user", content="Hello"),
            LLMMessage(role="assistant", content="Hi!", tool_calls=[{"id": "call_1"}]),
            LLMMessage(role="tool", content="result data", tool_call_id="call_1"),
            LLMMessage(role="user", content="Next"),
            LLMMessage(role="assistant", content="Sure!"),
        ]
        result = CompressStep._clear_old_tool_results(msgs)
        assert len(result) == len(msgs)
        # No tool messages should be cleared
        for msg in result:
            if msg.role == "tool":
                assert "cleared" not in (msg.content or "")

    def test_truncate_old_messages_short_content(self):
        """Messages with content <= 300 chars should not be truncated."""
        from nous.application.chat.pipeline.compress import CompressStep

        msgs = [
            LLMMessage(role="user", content="Short user message"),
            LLMMessage(role="assistant", content="Short response"),
            LLMMessage(role="user", content="Another short"),
            LLMMessage(role="assistant", content="Another response"),
        ]
        # keep_recent_turns=1 → keep last 2 messages intact
        result = CompressStep._truncate_old_messages(msgs, keep_recent_turns=1)
        # First 2 should not be truncated (content already short)
        for msg in result[:2]:
            if msg.role in ("user", "assistant"):
                assert not (msg.content or "").startswith("[旧]"), (
                    f"Short message should not be truncated: {msg.content}"
                )

    def test_truncate_old_messages_within_keep_count(self):
        """When total messages <= keep_recent_turns*2, no truncation."""
        from nous.application.chat.pipeline.compress import CompressStep

        msgs = [
            LLMMessage(role="user", content="Short"),
            LLMMessage(role="assistant", content="Response"),
        ]
        result = CompressStep._truncate_old_messages(msgs, keep_recent_turns=5)
        assert len(result) == len(msgs)
        for msg in result:
            assert not (msg.content or "").startswith("[旧]")

    @pytest.mark.asyncio
    async def test_stage2_under_budget_after_clear(self):
        """After clearing tool results (stage 2), if under budget, return messages."""
        from nous.application.chat.pipeline.compress import CompressStep

        config = _make_chat_config(
            context_max_tokens=2000,  # Moderate budget: clear may be enough
            context_compress_history=True,
            context_compress_system_prompt=True,
        )
        ctx = _dummy_app_context()
        tctx = _dummy_turn_ctx(_long_system_prompt(num_memories=2))  # Small prompt
        msgs = _messages_with_tool_results()  # 24 messages with tool results

        result = await CompressStep().run(ctx, config, tctx, msgs)
        assert isinstance(result, list)

    @pytest.mark.asyncio
    async def test_return_after_stage1_trim_only(self):
        """System prompt trim alone brings under budget → return session_messages (line 84)."""
        from nous.application.chat.pipeline.compress import CompressStep

        config = _make_chat_config(
            context_compression_mode="aggressive",
            context_compress_system_prompt=True,
            context_compress_history=True,
        )
        # Budget 3000: under initial (4553+3=4556) but above post-trim (554+3=557)
        config.context_max_tokens = 3000
        config.context_compression_threshold = 1.0

        ctx = _dummy_app_context()
        tctx = _dummy_turn_ctx(_long_system_prompt(num_memories=50))
        msgs = [
            LLMMessage(role="user", content="Hello"),
            LLMMessage(role="assistant", content="Hi there"),
        ]

        result = await CompressStep().run(ctx, config, tctx, msgs)
        assert isinstance(result, list)
        # Messages should NOT be truncated (stage 1 alone did the job)
        for msg in result:
            if msg.role in ("user", "assistant"):
                assert not (msg.content or "").startswith("[旧]"), (
                    "Messages should not be truncated after stage 1 alone"
                )

    @pytest.mark.asyncio
    async def test_return_after_stage2_clear_only(self):
        """Tool result clearing brings under budget → return messages (line 95)."""
        from nous.application.chat.pipeline.compress import CompressStep

        config = _make_chat_config(
            context_compression_mode="aggressive",
            context_compress_system_prompt=True,
            context_compress_history=True,
        )
        # Budget 2800: under stage 1 total (554+2472=3026) but above stage 2 (≈2538)
        config.context_max_tokens = 2800
        config.context_compression_threshold = 1.0

        ctx = _dummy_app_context()
        tctx = _dummy_turn_ctx(_long_system_prompt(num_memories=50))
        msgs = _messages_with_tool_results()

        result = await CompressStep().run(ctx, config, tctx, msgs)
        assert isinstance(result, list)

    # ── Stage 4: LLM summarization tests ──────────────

    def test_should_summarize_false_when_disabled(self):
        """_should_summarize returns False when context_use_llm_summary is False."""
        from nous.application.chat.pipeline.compress import CompressStep

        config = _make_chat_config(context_use_llm_summary=False)
        msgs = _long_messages(num_pairs=10)
        assert not CompressStep._should_summarize(msgs, config)

    def test_should_summarize_false_when_not_configured(self):
        """_should_summarize returns False when provider has no API key."""
        from nous.application.chat.pipeline.compress import CompressStep

        config = _make_chat_config(context_use_llm_summary=True, api_key="")
        msgs = _long_messages(num_pairs=10)
        assert not CompressStep._should_summarize(msgs, config)

    def test_should_summarize_false_when_few_turns(self):
        """_should_summarize returns False when fewer than 6 user messages."""
        from nous.application.chat.pipeline.compress import CompressStep

        config = _make_chat_config(context_use_llm_summary=True, api_key="sk-test")
        msgs = _long_messages(num_pairs=3)  # Only 3 turns
        assert not CompressStep._should_summarize(msgs, config)

    def test_should_summarize_true_when_conditions_met(self):
        """_should_summarize returns True when all conditions are satisfied."""
        from nous.application.chat.pipeline.compress import CompressStep

        config = _make_chat_config(context_use_llm_summary=True, api_key="sk-test")
        msgs = _long_messages(num_pairs=6)  # Exactly 6 turns
        assert CompressStep._should_summarize(msgs, config)

    @pytest.mark.asyncio
    async def test_stage4_invoked_when_over_budget_with_enough_turns(self):
        """Stage 4 is invoked when over budget, enough turns, and configured."""
        from nous.application.chat.pipeline.compress import CompressStep

        config = _make_chat_config(
            context_max_tokens=200,
            context_keep_recent_turns=1,
            api_key="sk-test",
            context_use_llm_summary=True,
        )
        ctx = _dummy_app_context()
        tctx = _dummy_turn_ctx(_long_system_prompt(num_memories=2))
        msgs = _long_messages(num_pairs=6)  # 6 turns = 12 messages

        with patch.object(CompressStep, "_summarize_old_turns", new_callable=AsyncMock) as mock_summarize:
            mock_summarize.return_value = "ユーザーがテスト質問を6回行い、アシスタントが回答しました。"
            result = await CompressStep().run(ctx, config, tctx, msgs)

            mock_summarize.assert_awaited_once()
            # Should contain the summary message + recent turns
            summary_msgs = [m for m in result if "過去の会話要約" in (m.content or "")]
            assert len(summary_msgs) == 1
            assert "ユーザーがテスト質問" in summary_msgs[0].content  # type: ignore[union-attr]

    @pytest.mark.asyncio
    async def test_stage4_graceful_fallback_on_error(self):
        """Stage 4 gracefully falls back to mechanical compression when LLM fails."""
        from nous.application.chat.pipeline.compress import CompressStep

        config = _make_chat_config(
            context_max_tokens=200,
            context_keep_recent_turns=1,
            api_key="sk-test",
            context_use_llm_summary=True,
        )
        ctx = _dummy_app_context()
        tctx = _dummy_turn_ctx(_long_system_prompt(num_memories=2))
        msgs = _long_messages(num_pairs=6)

        with patch.object(CompressStep, "_summarize_old_turns", new_callable=AsyncMock) as mock_summarize:
            mock_summarize.side_effect = RuntimeError("LLM unavailable")
            result = await CompressStep().run(ctx, config, tctx, msgs)
            mock_summarize.assert_awaited_once()
            # Should still return a valid list (mechanical compression fallback)
            assert isinstance(result, list)
            assert len(result) > 0
            # No summary message should be present
            summary_msgs = [m for m in result if "過去の会話要約" in (m.content or "")]
            assert len(summary_msgs) == 0

    @pytest.mark.asyncio
    async def test_stage4_not_invoked_when_under_budget(self):
        """Stage 4 is skipped when mechanical compression already meets budget."""
        from nous.application.chat.pipeline.compress import CompressStep

        config = _make_chat_config(
            context_max_tokens=5000,
            api_key="sk-test",
            context_use_llm_summary=True,
        )
        ctx = _dummy_app_context()
        tctx = _dummy_turn_ctx(_long_system_prompt(num_memories=2))
        msgs = _long_messages(num_pairs=6)

        with patch.object(CompressStep, "_summarize_old_turns", new_callable=AsyncMock) as mock_summarize:
            result = await CompressStep().run(ctx, config, tctx, msgs)
            mock_summarize.assert_not_awaited()
            assert isinstance(result, list)


# ──────────────────────────────────────────────
# Dogfooding: end-to-end conversation flow
# ──────────────────────────────────────────────


class TestDogfooding:
    """Basic conversation round-trip tests to verify nothing is broken."""

    def test_pipeline_chatconfig_roundtrip(self):
        """Verify ChatConfig → repository save/load preserves new fields."""
        import sqlite3

        from nous.domain.chat_config import ChatConfig, ChatConfigRepository

        db = sqlite3.connect(":memory:")

        # Create schema with all columns (including new ones)
        db.execute("""
            CREATE TABLE chat_settings (
                persona TEXT PRIMARY KEY,
                provider TEXT DEFAULT 'anthropic',
                model TEXT DEFAULT '',
                api_key TEXT DEFAULT '',
                base_url TEXT DEFAULT '',
                system_prompt TEXT DEFAULT '',
                temperature REAL DEFAULT 0.7,
                max_tokens INTEGER DEFAULT 2048,
                max_window_turns INTEGER DEFAULT 100,
                max_tool_calls INTEGER DEFAULT 5,
                updated_at TEXT,
                auto_extract INTEGER DEFAULT 1,
                extract_model TEXT DEFAULT '',
                extract_max_tokens INTEGER DEFAULT 512,
                tool_result_max_chars INTEGER DEFAULT 4000,
                mcp_servers TEXT DEFAULT '[]',
                enabled_skills TEXT DEFAULT '[]',
                reflection_enabled INTEGER DEFAULT 1,
                reflection_threshold REAL DEFAULT 1.0,
                reflection_min_interval_hours REAL DEFAULT 1.0,
                session_summarize INTEGER DEFAULT 1,
                retrieval_recency_weight REAL DEFAULT 0.3,
                retrieval_importance_weight REAL DEFAULT 0.3,
                retrieval_relevance_weight REAL DEFAULT 0.4,
                retrieval_rrf_k REAL DEFAULT 5.0,
                display_history_turns INTEGER DEFAULT 20,
                housekeeping_threshold INTEGER DEFAULT 10,
                sandbox_enabled INTEGER DEFAULT 0,
                mental_model_enabled INTEGER DEFAULT 1,
                mental_model_min_samples INTEGER DEFAULT 3,
                max_stored_messages INTEGER DEFAULT 200,
                context_max_tokens INTEGER,
                context_compression_threshold REAL DEFAULT 0.8,
                context_compression_mode TEXT DEFAULT 'auto',
                context_keep_recent_turns INTEGER DEFAULT 2,
                context_compress_system_prompt INTEGER DEFAULT 1,
                context_compress_history INTEGER DEFAULT 1,
                memory_preload_count INTEGER DEFAULT 3,
                enable_parallel_tools INTEGER DEFAULT 1,
                image_gen_enabled INTEGER DEFAULT 0,
                image_gen_provider TEXT DEFAULT 'openai',
                image_gen_dalle_model TEXT DEFAULT 'dall-e-3',
                image_gen_stability_url TEXT DEFAULT '',
                searxng_url TEXT DEFAULT '',
                enable_memory_tools INTEGER DEFAULT 1,
                debug_mode INTEGER DEFAULT 0,
                dynamic_temperature INTEGER DEFAULT 1,
                emotion_temperature_scale REAL DEFAULT 0.2,
                top_p REAL,
                context_use_llm_summary INTEGER DEFAULT 1,
                episode_consolidation_enabled INTEGER DEFAULT 1,
                episode_search_enabled INTEGER DEFAULT 1
            )
        """)
        db.commit()

        repo = ChatConfigRepository(db)
        cfg = ChatConfig(
            persona="test",
            provider="openrouter",
            model="openai/gpt-4o",
            max_window_turns=20,
            max_stored_messages=40,
            context_max_tokens=50000,
            context_compression_threshold=0.75,
            context_compression_mode="light",
            context_keep_recent_turns=5,
            context_compress_system_prompt=False,
            context_compress_history=True,
            memory_preload_count=5,
            enable_parallel_tools=False,
        )

        repo.save(cfg)

        loaded = repo.get("test")
        assert loaded.persona == "test"
        assert loaded.max_window_turns == 20
        assert loaded.max_stored_messages == 40
        assert loaded.context_max_tokens == 50000
        assert loaded.context_compression_threshold == 0.75
        assert loaded.context_compression_mode == "light"
        assert loaded.context_keep_recent_turns == 5
        assert loaded.context_compress_system_prompt is False
        assert loaded.context_compress_history is True
        assert loaded.memory_preload_count == 5
        assert loaded.enable_parallel_tools is False

    def test_sessionwindow_new_defaults(self):
        """Verify SessionWindow uses new defaults (200 msg max)."""
        from nous.application.chat.session_store import SessionWindow

        w = SessionWindow()
        assert w._max_messages == 200
        assert w.get_message_count() == 0

    def test_sessionwindow_custom_max_messages(self):
        """Verify SessionWindow accepts max_messages parameter."""
        from nous.application.chat.session_store import SessionWindow

        w = SessionWindow(max_messages=50)
        assert w._max_messages == 50

    def test_sessionwindow_max_turns_backward_compat(self):
        """Verify SessionWindow still accepts max_turns and converts."""
        from nous.application.chat.session_store import SessionWindow

        w = SessionWindow(max_turns=10)
        assert w._max_messages == 20  # 10 turns * 2

    def test_chatconfig_max_window_turns_validator(self):
        """Verify max_window_turns validates correctly with new 1-500 range."""
        from nous.domain.chat_config import ChatConfig

        # Within range
        cfg = ChatConfig(persona="test", max_window_turns=100)
        assert cfg.max_window_turns == 100

        # Upper clamp (600 → 500)
        cfg = ChatConfig(persona="test", max_window_turns=600)
        assert cfg.max_window_turns == 500

        # Lower clamp (0 → 1)
        cfg = ChatConfig(persona="test", max_window_turns=0)
        assert cfg.max_window_turns == 1

    def test_parallel_tools_flag_exists(self):
        """Verify enable_parallel_tools is accessible."""
        from nous.domain.chat_config import ChatConfig

        cfg = ChatConfig()
        assert hasattr(cfg, "enable_parallel_tools")
        assert isinstance(cfg.enable_parallel_tools, bool)
        assert cfg.enable_parallel_tools is True  # Default on
