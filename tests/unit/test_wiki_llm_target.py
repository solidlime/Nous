"""wiki の LLM 接続先解決（kanban #66）。

WikiConfig に鍵が無いとき、ペルソナのチャット設定（チャットタブの値）を流用する。
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from nous.application.wiki.llm_target import resolve_llm
from nous.application.workers.wiki_worker import WikiWorker
from nous.config.settings import WikiConfig


def _settings(**wiki) -> MagicMock:
    s = MagicMock()
    s.wiki = WikiConfig(**wiki)
    s.openrouter_api_key = ""
    s.anthropic_api_key = ""
    s.openai_api_key = ""
    s.google_api_key = ""
    s.opencode_go_api_key = ""
    return s


def _chat(**kw) -> SimpleNamespace:
    base = {"provider": "opencode_go", "model": "Fixer", "api_key": "sk-chat", "base_url": "http://nas:4000/v1"}
    return SimpleNamespace(**{**base, **kw})


class TestResolveLlm:
    def test_wiki_explicit_key_wins(self) -> None:
        """NOUS_WIKI__API_KEY があるなら wiki 専用設定を優先する。"""
        s = _settings(provider="openrouter", api_key="sk-wiki", model="m-wiki", base_url="http://wiki")
        assert resolve_llm(s.wiki, s, _chat()) == ("openrouter", "m-wiki", "sk-wiki", "http://wiki")

    def test_falls_back_to_chat_config(self) -> None:
        """wiki に鍵が無ければチャット設定（チャットタブ）をそのまま使う。"""
        s = _settings()
        assert resolve_llm(s.wiki, s, _chat()) == ("opencode_go", "Fixer", "sk-chat", "http://nas:4000/v1")

    def test_chat_without_key_is_not_used(self) -> None:
        """チャット側にも鍵が無ければ空の鍵（呼び出し側が失敗にする）。"""
        s = _settings()
        provider, model, api_key, _ = resolve_llm(s.wiki, s, _chat(api_key=None))
        assert api_key == ""
        assert (provider, model) == ("openrouter", s.wiki.model)

    def test_chat_config_facade_fields_are_used(self) -> None:
        """本物の ChatConfig（サブ設定を属性委譲する facade）からも取れること。"""
        from nous.domain.config.chat_config import ChatConfig

        s = _settings()
        c = ChatConfig(
            persona="x", provider="opencode_go", model="Fixer", api_key="sk-x", base_url="http://nas:4000/v1"
        )
        assert resolve_llm(s.wiki, s, c) == ("opencode_go", "Fixer", "sk-x", "http://nas:4000/v1")

    def test_chat_model_and_base_url_empty_keep_wiki_defaults(self) -> None:
        """チャット設定で model/base_url が空なら wiki の既定値で補う。"""
        s = _settings()
        provider, model, api_key, base_url = resolve_llm(s.wiki, s, _chat(model="", base_url=""))
        assert (provider, model, api_key, base_url) == ("opencode_go", s.wiki.model, "sk-chat", "")


class TestWorkerUsesChatConfig:
    def test_ask_text_uses_chat_config_when_wiki_key_missing(self) -> None:
        """WikiWorker._ask_text はチャット設定の接続先で provider を作る。"""
        s = _settings()
        worker = WikiWorker(s)
        worker._chat_config = _chat()  # type: ignore[attr-defined]
        captured: dict = {}

        class _Provider:
            pass

        def _fake_get_provider(provider: str, api_key: str, model: str, base_url: str = "") -> _Provider:
            captured.update(provider=provider, api_key=api_key, model=model, base_url=base_url)
            return _Provider()

        async def _fake_collect_text(*args, **kwargs) -> str:
            return "ok"

        with (
            patch("nous.infrastructure.llm.factory.get_provider", _fake_get_provider),
            patch("nous.infrastructure.llm.text_utils.collect_text", _fake_collect_text),
        ):
            assert worker._ask_text("prompt") == "ok"

        assert captured == {
            "provider": "opencode_go",
            "api_key": "sk-chat",
            "model": "Fixer",
            "base_url": "http://nas:4000/v1",
        }
