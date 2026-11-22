"""SummarizerMixin._summarize_old_turns のテスト（差分要約・件数上限・refs・失敗時 None）。"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from nous.application.chat.pipeline.summarizer import SummarizerMixin
from nous.infrastructure.llm.base import LLMMessage


class _Step(SummarizerMixin):
    pass


def _config(**overrides):
    from nous.domain.config.chat_config import ChatConfig

    defaults = {"persona": "test", "provider": "openrouter", "model": "openai/gpt-4o", "api_key": "sk-test"}
    defaults.update(overrides)
    return ChatConfig(**defaults)


def _msgs(count: int) -> list[LLMMessage]:
    out: list[LLMMessage] = []
    for i in range(count):
        out.append(LLMMessage(role="user", content=f"質問{i}"))
        out.append(LLMMessage(role="assistant", content=f"回答{i}"))
    return out


def _capture_prompt(config, removed, refs=None):
    """プロバイダ呼び出しを差し替えて、送られた要約プロンプトを取り出す。"""
    captured: dict = {}

    async def _fake_collect(provider, messages, system, tools, temperature, max_tokens):
        captured["prompt"] = messages[0].content
        return "要約結果"

    with (
        patch("nous.infrastructure.llm.factory.get_provider", return_value=MagicMock()),
        patch("nous.infrastructure.llm.text_utils.collect_text", new=_fake_collect),
    ):
        result = _run(config, removed, refs)
    return captured.get("prompt", ""), result


def _run(config, removed, refs):
    import asyncio

    return asyncio.run(_Step()._summarize_old_turns(config=config, removed=removed, refs=refs))


class TestSummarizeOldTurns:
    def test_caps_input_at_60_messages(self):
        prompt, _ = _capture_prompt(_config(), _msgs(80))
        # 80 ペア = 160 メッセージ → 末尾 60 件（30 ペアの 30..79 側）のみ載る
        assert "質問79" in prompt
        assert "質問0" not in prompt
        assert "質問50" in prompt

    def test_includes_refs_section(self):
        prompt, _ = _capture_prompt(_config(), _msgs(2), refs=["/data/a.txt", "/logs/b.log"])
        assert "削除済み会話が参照していた添付: /data/a.txt, /logs/b.log" in prompt

    def test_no_refs_section_without_refs(self):
        prompt, _ = _capture_prompt(_config(), _msgs(2))
        assert "参照していた添付" not in prompt

    def test_prompt_includes_target_chars(self):
        prompt, _ = _capture_prompt(_config(), _msgs(2))
        assert "300" in prompt

    def test_skips_tool_messages(self):
        removed = [
            LLMMessage(role="user", content="質問"),
            LLMMessage(role="tool", content="tool 生データ", tool_call_id="c1"),
            LLMMessage(role="assistant", content="回答"),
        ]
        prompt, _ = _capture_prompt(_config(), removed)
        assert "tool 生データ" not in prompt

    def test_returns_none_for_empty_input(self):
        assert _run(_config(), [], None) is None

    def test_returns_none_without_user_content(self):
        removed = [LLMMessage(role="assistant", content="独り言")]
        assert _run(_config(), removed, None) is None

    def test_returns_none_when_provider_init_fails(self):
        with patch("nous.infrastructure.llm.factory.get_provider", side_effect=RuntimeError("no provider")):
            assert _run(_config(), _msgs(1), None) is None

    def test_returns_none_when_llm_call_fails(self):
        async def _boom(*a, **kw):
            raise RuntimeError("upstream 500")

        with (
            patch("nous.infrastructure.llm.factory.get_provider", return_value=MagicMock()),
            patch("nous.infrastructure.llm.text_utils.collect_text", new=_boom),
        ):
            # 例外は握りつぶして None を返す（呼び出し側がフォールバック文面を出す）
            assert _run(_config(), _msgs(1), None) is None


class TestShouldSummarize:
    def test_false_when_disabled(self):
        removed = _msgs(2)
        assert not _Step()._should_summarize(removed, _config(context_use_llm_summary=False))

    def test_false_when_provider_not_configured(self):
        removed = _msgs(2)
        assert not _Step()._should_summarize(removed, _config(api_key=""))

    def test_false_when_no_user_content(self):
        removed = [LLMMessage(role="assistant", content="独り言")]
        assert not _Step()._should_summarize(removed, _config())

    def test_true_when_conditions_met(self):
        assert _Step()._should_summarize(_msgs(2), _config())
