"""Tests for cache_utils.build_openai_system_messages."""

from nous.infrastructure.llm.cache_utils import build_openai_system_messages


class TestBuildOpenaiSystemMessages:
    def test_empty_system_returns_no_message(self):
        """空 content の system は 400 を招くためメッセージ自体を省略する."""
        assert build_openai_system_messages("") == []

    def test_whitespace_system_returns_no_message(self):
        assert build_openai_system_messages("   \n\t ") == []

    def test_plain_system(self):
        msgs = build_openai_system_messages("You are Herta.")
        assert msgs == [{"role": "system", "content": "You are Herta."}]

    def test_boundary_marker_splits_with_cache_control(self):
        system = "static part<!-- __STATIC_END__ -->dynamic part"
        msgs = build_openai_system_messages(system)
        assert len(msgs) == 1
        content = msgs[0]["content"]
        assert content[0]["cache_control"] == {"type": "ephemeral"}
        assert content[0]["text"] == "static part"
        assert content[1]["text"] == "dynamic part"


def test_empty_dynamic_still_uses_parts_form():
    """marker があるが動的部が空 → parts 形式＋cache_control を維持（Part B）。

    marker の有無が形式の合図。marker あり＝静的分割の意思があるので、
    動的部が空でも文字列単一形式へ退化させない。
    """
    msgs = build_openai_system_messages("static only<!-- __STATIC_END__ -->")
    assert len(msgs) == 1
    content = msgs[0]["content"]
    assert isinstance(content, list)
    assert len(content) == 1
    assert content[0]["cache_control"] == {"type": "ephemeral"}
    assert content[0]["text"] == "static only"


def test_marker_absent_stays_plain_string():
    """marker 不在 = 分割の意思なし → 従来の文字列単一形式。"""
    msgs = build_openai_system_messages("You are Herta.")
    assert msgs == [{"role": "system", "content": "You are Herta."}]
