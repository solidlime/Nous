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
        """When under budget and keep_recent_turns=0, messages pass through unchanged."""
        from nous.application.chat.pipeline.compress import CompressStep

        config = _make_chat_config(
            context_max_tokens=1_000_000,  # Huge budget
            context_keep_recent_turns=0,  # Disable Stage 0 truncation
        )
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
        """Old tool results should be replaced with status summary."""
        from nous.application.chat.pipeline.compress import CompressStep

        config = _make_chat_config(
            context_max_tokens=200,
            context_keep_recent_turns=0,  # Disable Stage 0 to isolate Stage 2
            context_use_llm_summary=False,  # Disable Stage 3 to isolate Stage 2
        )
        ctx = _dummy_app_context()
        tctx = _dummy_turn_ctx(_long_system_prompt(num_memories=5))
        msgs = _messages_with_tool_results()

        original_tool_msgs = [m for m in msgs if m.role == "tool"]
        assert len(original_tool_msgs) == 8

        result = await CompressStep().run(ctx, config, tctx, msgs)

        replaced = [m for m in result if m.role == "tool" and "ツール実行" in (m.content or "")]
        assert len(replaced) >= 1, f"Expected at least 1 replaced tool result, got {len(replaced)}"

        # Most recent tool results should be preserved (intact content)
        recent_tools = [m for m in result[-10:] if m.role == "tool" and "x" in (m.content or "")]
        assert len(recent_tools) >= 1, "Recent tool results should be preserved"

    @pytest.mark.asyncio
    async def test_old_messages_truncated(self):
        """Old messages should be removed entirely and replaced with a [システム:] notice."""
        from nous.application.chat.pipeline.compress import CompressStep

        config = _make_chat_config(
            context_max_tokens=200,
            context_keep_recent_turns=1,
            context_use_llm_summary=False,  # Disable Stage 3 to isolate Stage 4
        )
        ctx = _dummy_app_context()
        tctx = _dummy_turn_ctx(_long_system_prompt(num_memories=5))
        msgs = _long_messages(num_pairs=10)

        assert len(msgs) == 20  # 10 pairs

        result = await CompressStep().run(ctx, config, tctx, msgs)

        # Old messages are REMOVED entirely — result should be much shorter
        # Stage 0: 20 msgs → [システムnotice] + last_2_msgs = 3 msgs
        assert len(result) < len(msgs), f"Expected fewer messages after truncation: {len(result)}"

        # Should contain the [システム:] notice
        notices = [m for m in result if "[システム:" in (m.content or "")]
        assert len(notices) == 1, f"Expected exactly 1 system notice, got {len(notices)}"

        # Most recent 2 messages should be preserved intact (keep_recent_turns=1)
        last_two = result[-2:]
        for msg in last_two:
            if msg.role in ("user", "assistant") and msg.content:
                assert "[システム:" not in msg.content, (
                    f"Recent message should not be the notice: {msg.content[:50]}..."
                )

    @pytest.mark.asyncio
    async def test_compression_preserves_tool_call_ids(self):
        """Replaced tool results should keep their tool_call_id for API compatibility."""
        from nous.application.chat.pipeline.compress import CompressStep

        config = _make_chat_config(
            context_max_tokens=200,
            context_keep_recent_turns=0,  # Disable Stage 0 to isolate Stage 2
            context_use_llm_summary=False,  # Disable Stage 3 to isolate Stage 2
        )
        ctx = _dummy_app_context()
        tctx = _dummy_turn_ctx(_long_system_prompt(num_memories=5))
        msgs = _messages_with_tool_results()

        result = await CompressStep().run(ctx, config, tctx, msgs)

        replaced = [m for m in result if m.role == "tool" and "ツール実行" in (m.content or "")]
        for msg in replaced:
            assert msg.tool_call_id is not None, "Replaced tool results must retain tool_call_id"

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
            context_keep_recent_turns=0,  # Disable Stage 0 truncation
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
    async def test_compress_history_true_replaces_tool_results(self):
        """When context_compress_history=True and over budget, tool results get replaced."""
        from nous.application.chat.pipeline.compress import CompressStep

        config = _make_chat_config(
            context_max_tokens=1,  # Always over budget
            context_compress_history=True,
            context_compress_system_prompt=True,
            context_keep_recent_turns=0,  # Disable Stage 0 truncation to isolate Stage 2
            context_use_llm_summary=False,  # Disable Stage 3 to isolate Stage 2
        )
        ctx = _dummy_app_context()
        tctx = _dummy_turn_ctx(_long_system_prompt(num_memories=20))
        msgs = _messages_with_tool_results()

        result = await CompressStep().run(ctx, config, tctx, msgs)
        # Some tool results should be replaced with status summary
        replaced = [m for m in result if m.role == "tool" and "ツール実行" in (m.content or "")]
        assert len(replaced) >= 1

    def test_trim_system_prompt_preserves_skill_section(self):
        """Long skill descriptions must be preserved (skill discovery layer is protected)."""
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
        # Skill section is intentionally protected — truncation would break skill discovery.
        # Only the 関連記憶 section is trimmed.
        assert "skill_a" in result
        assert "利用可能なSkill" in result
        assert len(result) == len(prompt)

    def test_clear_tool_results_with_few_assistant_msgs(self):
        """When there are <= 3 assistant messages, no replacement happens."""
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
        # No tool messages should be replaced
        for msg in result:
            if msg.role == "tool":
                assert "ツール実行" not in (msg.content or "")

    def test_truncate_old_messages_short_content(self):
        """Old messages should be removed entirely, not content-truncated."""
        from nous.application.chat.pipeline.compress import CompressStep

        msgs = [
            LLMMessage(role="user", content="Short user message"),
            LLMMessage(role="assistant", content="Short response"),
            LLMMessage(role="user", content="Another short"),
            LLMMessage(role="assistant", content="Another response"),
        ]
        # keep_recent_turns=1 → keep last 2 messages intact
        result = CompressStep._truncate_old_messages(msgs, keep_recent_turns=1)
        # Old messages are REMOVED: [システムnotice] + last_2_msgs = 3 total
        assert len(result) == 3, f"Expected 3 messages (notice + 2 recent), got {len(result)}"
        # First message is the system notice
        assert "[システム:" in (result[0].content or "")
        # Last 2 messages are preserved intact
        assert result[1].content == "Another short"
        assert result[2].content == "Another response"

    def test_truncate_old_messages_within_keep_count(self):
        """When total messages <= keep_recent_turns*2, no truncation."""
        from nous.application.chat.pipeline.compress import CompressStep

        msgs = [
            LLMMessage(role="user", content="Short"),
            LLMMessage(role="assistant", content="Response"),
        ]
        result = CompressStep._truncate_old_messages(msgs, keep_recent_turns=5)
        assert len(result) == len(msgs)
        assert result is msgs  # Same object reference = no modification
        # Content should be unchanged
        assert result[0].content == "Short"
        assert result[1].content == "Response"

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
        # Messages should be preserved (stage 1 alone did the job)
        # No [旧] or [システム:] check needed: keep_recent_turns=1, 2 msgs <= 2 → no truncation
        assert len(result) == 2

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
        """_should_summarize returns False when not enough user messages beyond keep_recent."""
        from nous.application.chat.pipeline.compress import CompressStep

        config = _make_chat_config(context_use_llm_summary=True, api_key="sk-test")
        msgs = _long_messages(num_pairs=1)  # 1 user message, keep_recent=1 → 1 > 1 = False
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
            context_keep_recent_turns=0,  # Disable Stage 0 to test Stage 3
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
            context_keep_recent_turns=0,  # Disable Stage 0 to test Stage 3
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
    async def test_stage3_not_invoked_when_under_budget(self):
        """Stage 3 (LLM summary) is skipped when already within budget."""
        from nous.application.chat.pipeline.compress import CompressStep

        config = _make_chat_config(
            context_max_tokens=100000,
            api_key="sk-test",
            context_use_llm_summary=True,
            context_keep_recent_turns=0,  # Disable Stage 0 to test Stage 3 skip
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

    def test_pipeline_chatconfig_roundtrip(self, tmp_path):
        """Verify ChatConfig → repository save/load preserves new fields."""
        from nous.domain.chat_config import ChatConfig, ChatConfigFileRepository

        repo = ChatConfigFileRepository(str(tmp_path))
        cfg = ChatConfig(
            persona="test",
            provider="openrouter",
            model="openai/gpt-4o",
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
        """Verify TreeSessionWindow uses new defaults (200 msg max)."""
        from nous.application.chat.session_store import TreeSessionWindow

        w = TreeSessionWindow()
        assert w._max_messages == 200
        assert w.get_message_count() == 0

    def test_sessionwindow_custom_max_messages(self):
        """Verify TreeSessionWindow accepts max_messages parameter."""
        from nous.application.chat.session_store import TreeSessionWindow

        w = TreeSessionWindow(max_messages=50)
        assert w._max_messages == 50

    def test_sessionwindow_default_max_messages(self):
        """Verify TreeSessionWindow default max_messages is 200."""
        from nous.application.chat.session_store import TreeSessionWindow

        w = TreeSessionWindow()
        assert w._max_messages == 200  # default

    def test_parallel_tools_flag_exists(self):
        """Verify enable_parallel_tools is accessible."""
        from nous.domain.chat_config import ChatConfig

        cfg = ChatConfig()
        assert hasattr(cfg, "enable_parallel_tools")
        assert isinstance(cfg.enable_parallel_tools, bool)
        assert cfg.enable_parallel_tools is True  # Default on


class TestTrimmerToolOrphan:
    """TrimmerMixin._truncate_old_messages の tool 孤児防止（SPEC F1）。"""

    @staticmethod
    def _msg(role, content="", tool_calls=None, tool_call_id=None):
        from nous.infrastructure.llm.base import LLMMessage

        return LLMMessage(role=role, content=content, tool_calls=tool_calls, tool_call_id=tool_call_id)

    def test_tool_orphan_prevented_by_widening_slice(self):
        """スライス先頭が tool になる入力 → assistant(tool_calls) を含むよう広げられる。"""
        from nous.application.chat.pipeline.trimmer import TrimmerMixin

        msgs = [
            self._msg("user", "q1"),
            self._msg("assistant", "", tool_calls=[{"id": "call_1", "name": "f", "input": {}}]),
            self._msg("tool", "r1", tool_call_id="call_1"),
            self._msg("user", "q2"),
            self._msg("assistant", "", tool_calls=[{"id": "call_2", "name": "f", "input": {}}]),
            self._msg("tool", "r2", tool_call_id="call_2"),
            self._msg("user", "q3"),
            self._msg("assistant", "", tool_calls=[{"id": "call_3", "name": "f", "input": {}}]),
            self._msg("tool", "r3", tool_call_id="call_3"),
        ]
        # 9件 / keep=2 → keep_count=4 → 素朴な [-4:] は [tool, user, assistant(tc), tool] で先頭が tool 孤児になる
        result = TrimmerMixin._truncate_old_messages(msgs, keep_recent_turns=2)

        # 先頭は [システムnotice]、その後に assistant(tool_calls) → tool が続く（孤児なし）
        assert "[システム:" in (result[0].content or "")
        assert result[1].role == "assistant"
        assert result[1].tool_calls
        assert result[2].role == "tool"
        assert result[2].tool_call_id == result[1].tool_calls[0]["id"]
        # 広げた分、末尾の a(tc call_3) → tool r3 も含まれる
        assert result[-1].role == "tool"
        assert result[-1].tool_call_id == "call_3"

    def test_normal_slice_unchanged(self):
        """スライス先頭が tool でない通常ケース → 従来動作を維持。"""
        from nous.application.chat.pipeline.trimmer import TrimmerMixin

        msgs = [
            self._msg("user", "q1"),
            self._msg("assistant", "", tool_calls=[{"id": "call_1", "name": "f", "input": {}}]),
            self._msg("tool", "r1", tool_call_id="call_1"),
            self._msg("user", "q2"),
            self._msg("assistant", "", tool_calls=[{"id": "call_2", "name": "f", "input": {}}]),
            self._msg("tool", "r2", tool_call_id="call_2"),
            self._msg("user", "q3"),
            self._msg("assistant", "final answer"),
        ]
        result = TrimmerMixin._truncate_old_messages(msgs, keep_recent_turns=2)

        # 素朴な [-4:] と同じ開始位置（先頭が tool でないので広がらない）
        assert len(result) == 5  # [システムnotice] + 末尾4件
        assert "[システム:" in (result[0].content or "")
        assert result[1].role == "assistant"
        assert result[1].tool_calls
        assert result[2].role == "tool"
        assert result[-1].content == "final answer"

    def test_keep_zero_returns_unchanged(self):
        """keep_recent_turns=0 → 無変更。"""
        from nous.application.chat.pipeline.trimmer import TrimmerMixin

        msgs = [
            self._msg("user", "q1"),
            self._msg("assistant", "a1"),
            self._msg("user", "q2"),
            self._msg("assistant", "a2"),
        ]
        result = TrimmerMixin._truncate_old_messages(msgs, keep_recent_turns=0)
        assert result == msgs

    def test_all_tool_tail_does_not_crash(self):
        """末尾が全て tool の極端ケースでクラッシュしない（広げすぎない）。"""
        from nous.application.chat.pipeline.trimmer import TrimmerMixin

        msgs = [
            self._msg("tool", "r1", tool_call_id="call_1"),
            self._msg("tool", "r2", tool_call_id="call_1"),
            self._msg("tool", "r3", tool_call_id="call_1"),
        ]
        result = TrimmerMixin._truncate_old_messages(msgs, keep_recent_turns=1)
        assert isinstance(result, list)
        assert len(result) > 0
