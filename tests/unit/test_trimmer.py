"""TrimmerMixin._build_truncation_highlights / _truncate_old_messages のテスト。

仕様: docs/superpowers/specs/2026-09-06-prompt-assembly-redesign-design.md §4.2
- ハイライトは user/assistant 両方・`[N] role: snippet` 形式
- 先頭3 + 末尾3、snippet 80 字、改行は空白に置換
- fake assistant note（[システム: …] 偽装文）は廃止。ハイライトは戻り値で伝播
"""

from __future__ import annotations

from nous.application.chat.pipeline.trimmer import TrimmerMixin
from nous.infrastructure.llm.base import LLMMessage


def _msg(role: str, content: str) -> LLMMessage:
    return LLMMessage(role=role, content=content)


class TestBuildTruncationHighlights:
    def test_roles_explicit_for_both_roles(self):
        msgs = [
            _msg("user", "最初の質問"),
            _msg("assistant", "最初の回答"),
            _msg("user", "次の質問"),
            _msg("assistant", "次の回答"),
        ]
        highlights = TrimmerMixin._build_truncation_highlights(msgs, 4, keep_recent=1)
        assert "[0] user: 最初の質問" in highlights
        assert "[1] assistant: 最初の回答" in highlights
        assert "[2] user: 次の質問" in highlights
        assert "[3] assistant: 次の回答" in highlights

    def test_first3_and_last3_only(self):
        msgs = []
        for i in range(12):
            msgs.append(_msg("user" if i % 2 == 0 else "assistant", f"内容{i}"))
        highlights = TrimmerMixin._build_truncation_highlights(msgs, 12, keep_recent=1)
        for kept in (0, 1, 2, 9, 10, 11):
            assert f"[{kept}]" in highlights
        for dropped in (3, 4, 5, 6, 7, 8):
            assert f"[{dropped}]" not in highlights

    def test_six_or_fewer_all_kept(self):
        msgs = [_msg("user", f"u{i}") for i in range(6)]
        highlights = TrimmerMixin._build_truncation_highlights(msgs, 6, keep_recent=1)
        for i in range(6):
            assert f"[{i}] user: u{i}" in highlights

    def test_snippet_capped_at_80_chars(self):
        long_text = "あ" * 200
        msgs = [_msg("user", long_text)]
        highlights = TrimmerMixin._build_truncation_highlights(msgs, 1, keep_recent=1)
        line = [ln for ln in highlights.splitlines() if ln.startswith("[0]")][0]
        snippet = line.split(": ", 1)[1]
        assert len(snippet) == 80

    def test_newlines_replaced_with_space(self):
        msgs = [_msg("user", "一行目\n二行目")]
        highlights = TrimmerMixin._build_truncation_highlights(msgs, 1, keep_recent=1)
        assert "一行目 二行目" in highlights

    def test_tool_messages_excluded(self):
        from nous.infrastructure.llm.base import LLMMessage

        msgs = [
            _msg("user", "質問"),
            LLMMessage(role="tool", content="ツール結果", tool_call_id="call_1"),
            _msg("assistant", "回答"),
        ]
        highlights = TrimmerMixin._build_truncation_highlights(msgs, 3, keep_recent=1)
        assert "tool" not in highlights
        assert "ツール結果" not in highlights

    def test_truncation_time_included(self):
        msgs = [_msg("user", "質問")]
        highlights = TrimmerMixin._build_truncation_highlights(msgs, 1, keep_recent=1)
        assert "切り詰め" in highlights

    def test_empty_removed_returns_empty(self):
        assert TrimmerMixin._build_truncation_highlights([], 0, keep_recent=1) == ""

    def test_no_fake_note_in_highlights(self):
        msgs = [_msg("user", "質問"), _msg("assistant", "回答")]
        highlights = TrimmerMixin._build_truncation_highlights(msgs, 2, keep_recent=1)
        assert "[システム:" not in highlights


class TestTruncateOldMessagesReturn:
    def test_no_fake_note_messages_and_highlights_returned(self):
        msgs: list[LLMMessage] = []
        for i in range(3):
            msgs.append(_msg("user", f"q{i}"))
            msgs.append(_msg("assistant", f"a{i}"))
        result, highlights, removed = TrimmerMixin._truncate_old_messages(msgs, keep_recent_turns=1)
        # fake note 廃止: メッセージは直近2件のみ
        assert len(result) == 2
        assert not any("[システム:" in (m.content or "") for m in result)
        # ハイライトはメッセージに混ぜず戻り値で伝播
        assert highlights
        assert "[0] user: q0" in highlights
        # Stage 3 の入力に使う removed slice も返す
        assert removed == msgs[:4]

    def test_keep_zero_returns_unchanged(self):
        msgs = [_msg("user", "q1"), _msg("assistant", "a1"), _msg("user", "q2"), _msg("assistant", "a2")]
        result, highlights, removed = TrimmerMixin._truncate_old_messages(msgs, keep_recent_turns=0)
        assert result is msgs
        assert highlights == ""
        assert removed == []

    def test_within_keep_count_no_truncation(self):
        msgs = [_msg("user", "q1"), _msg("assistant", "a1")]
        result, highlights, removed = TrimmerMixin._truncate_old_messages(msgs, keep_recent_turns=5)
        assert result is msgs
        assert highlights == ""
        assert removed == []
