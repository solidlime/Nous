"""Tests for LLM factory: 全 provider 名を OpenAICompatProvider に統一."""

from nous.infrastructure.llm.factory import get_provider
from nous.infrastructure.llm.openai_compat import OpenAICompatProvider


class TestFactoryUnifiedOpenAICompat:
    def test_anthropic_maps_to_compat_base_url(self):
        """旧 provider=anthropic → OpenAI互換エンドポイント経由の Claude."""
        p = get_provider("anthropic", api_key="k", model="claude-opus-4-5")
        assert isinstance(p, OpenAICompatProvider)
        assert p.base_url == "https://api.anthropic.com/v1/"

    def test_google_maps_to_gemini_compat_base_url(self):
        p = get_provider("google", api_key="k", model="gemini-2.5-flash")
        assert isinstance(p, OpenAICompatProvider)
        assert p.base_url == "https://generativelanguage.googleapis.com/v1beta/openai/"

    def test_openrouter_default(self):
        p = get_provider("openrouter", api_key="k", model="m")
        assert isinstance(p, OpenAICompatProvider)
        assert p.base_url == "https://openrouter.ai/api/v1"

    def test_openai_default(self):
        p = get_provider("openai", api_key="k", model="gpt-4o")
        assert isinstance(p, OpenAICompatProvider)
        assert p.base_url == "https://api.openai.com/v1"

    def test_opencode_go_default(self):
        p = get_provider("opencode_go", api_key="k", model="deepseek-v4-pro")
        assert isinstance(p, OpenAICompatProvider)
        assert p.base_url == "https://opencode.ai/zen/go/v1"

    def test_unknown_provider_falls_back_to_openai(self):
        """未知 provider → エラーにせず OpenAI デフォルトで動作継続."""
        p = get_provider("unknown_provider", api_key="k", model="m")
        assert isinstance(p, OpenAICompatProvider)
        assert p.base_url == "https://api.openai.com/v1"

    def test_explicit_base_url_wins(self):
        """明示 base_url は移行マップより優先."""
        p = get_provider("anthropic", api_key="k", model="m", base_url="https://api.commandcode.ai/provider/v1")
        assert p.base_url == "https://api.commandcode.ai/provider/v1"


class TestOpenCodeGoSessionHeaders:
    """OpenCode Go (base_url に opencode.ai/zen/go を含む) は会話ごとの安定セッション
    ID を x-opencode-session で要求する (無しは 400 MissingSessionID)。
    他のプロバイダには絶対に付けない。
    """

    def test_go_base_url_gets_session_and_user_agent(self):
        p = get_provider("openai", api_key="k", model="m", base_url="https://opencode.ai/zen/go/v1/aaa/bbb")
        headers = p._client.default_headers
        assert headers["x-opencode-session"]
        assert headers["User-Agent"].startswith("nous/")

    def test_non_go_base_url_has_no_session_header(self):
        p = get_provider("openrouter", api_key="k", model="m", base_url="https://openrouter.ai/api/v1")
        headers = p._client.default_headers
        assert "x-opencode-session" not in headers
        assert not str(headers.get("User-Agent", "")).startswith("nous/")

    def test_explicit_session_id_is_used_verbatim(self):
        p = get_provider(
            "openai", api_key="k", model="m", base_url="https://opencode.ai/zen/go/v1", session_id="sess-42"
        )
        assert p._client.default_headers["x-opencode-session"] == "sess-42"

    def test_fallback_session_stable_within_process(self):
        p1 = get_provider("opencode_go", api_key="k", model="m")
        p2 = get_provider("opencode_go", api_key="k", model="m")
        h1, h2 = p1._client.default_headers, p2._client.default_headers
        assert h1["x-opencode-session"] == h2["x-opencode-session"]
        assert h1["User-Agent"] == "nous/3.5.0"
