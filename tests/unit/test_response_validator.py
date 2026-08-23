"""Tests for response_validator.py"""

import pytest

from nous.application.chat.response_validator import (
    _check_garbled_text,
    _split_sentences,
    validate_response,
)


class TestValidateResponse:
    """Public API tests for validate_response()."""

    def test_empty_response(self):
        """Empty string should return a single warning."""
        warnings = validate_response("")
        assert warnings == ["Response is empty or whitespace-only"]

    def test_whitespace_only(self):
        """Whitespace-only string should be treated as empty."""
        warnings = validate_response("   ")
        assert warnings == ["Response is empty or whitespace-only"]

    def test_clean_response(self):
        """Normal Japanese response should return no warnings."""
        warnings = validate_response("こんにちは。今日はいい天気ですね。")
        assert warnings == []

    def test_ai_self_id_detected(self):
        """'As an AI' pattern should be detected."""
        warnings = validate_response("As an AI, I think you should...")
        assert len(warnings) == 1
        assert "AI self-identification" in warnings[0]

    @pytest.mark.parametrize(
        "text",
        [
            "I am an AI assistant",
            "I'm an AI assistant",
            "as an AI, I can help",
            "As a language model, I cannot do that",
            "I am not a human",
            "I am not human",
        ],
    )
    def test_ai_self_id_variants(self, text):
        """Multiple AI self-identification pattern variants."""
        warnings = validate_response(text)
        assert len(warnings) == 1
        assert "AI self-identification" in warnings[0]

    def test_repetition_detected(self):
        """Same sentence repeated 5 times should trigger repetition warning."""
        sentence = "これは繰り返しのテスト文です。"
        text = sentence * 5
        warnings = validate_response(text)
        assert any("repeated" in w for w in warnings)

    def test_no_false_positive_on_normal_text(self):
        """Normal varied conversation should not trigger false positives."""
        text = "今日は本当にいい天気ですね。散歩に行きませんか？公園でお花が咲いていましたよ。"
        warnings = validate_response(text)
        assert warnings == []

    def test_garbled_text_detected(self):
        """Text with N'Ko characters (garbled) should trigger garbled warning."""
        # N'Ko character U+07CA is in the suspicious range
        text = "正常なテキストです。\u07ca\u07cb\u07cc\u07cd\u07ceが混ざっています。"
        warnings = validate_response(text)
        assert any("Garbled" in w for w in warnings)


class TestInternalFunctions:
    """Tests for internal helper functions."""

    def test_split_sentences(self):
        """Sentence splitting should handle Japanese and English delimiters."""
        result = _split_sentences("文A。文B！文C?")
        assert len(result) >= 3

    def test_check_garbled_text_clean(self):
        """Clean text should return None."""
        assert _check_garbled_text("正常なテキストです。") is None

    def test_check_garbled_text_dirty(self):
        """Garbled text should return a warning string."""
        # 100 N'Ko chars = 100% suspicious ratio > 5% threshold
        result = _check_garbled_text("\u07ca" * 100)
        assert result is not None
        assert "Garbled" in result
