"""Unit tests for nous.api.mcp.middleware — persona resolution."""

from __future__ import annotations

import pytest

from nous.api.mcp.middleware import (
    PersonaMiddleware,
    PersonaRequiredError,
    _persona_var,
    get_current_persona,
    resolve_persona_from_headers,
    resolve_persona_from_token,
)

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


async def _noop_send(msg: dict) -> None:  # noqa: ARG001
    """No-op ASGI send callable."""


# =========================================================================
# A. resolve_persona_from_headers()
# =========================================================================


class TestResolvePersonaFromHeaders:
    def test_bearer_token_highest_priority(self):
        """Bearerトークンが最優先"""
        result = resolve_persona_from_headers(
            authorization="Bearer alice",
            x_persona="bob",
        )
        assert result == "alice"

    def test_x_persona_over_env(self, monkeypatch):
        """X-Personaが環境変数より優先"""
        monkeypatch.setenv("PERSONA", "env_persona")
        result = resolve_persona_from_headers(x_persona="header_persona")
        assert result == "header_persona"

    def test_env_fallback(self, monkeypatch):
        """ヘッダーなしで環境変数フォールバック"""
        monkeypatch.setenv("PERSONA", "env_persona")
        result = resolve_persona_from_headers()
        assert result == "env_persona"

    def test_default_persona_env(self, monkeypatch):
        """PERSONAなし、NOUS_DEFAULT_PERSONA使用"""
        monkeypatch.delenv("PERSONA", raising=False)
        monkeypatch.setenv("NOUS_DEFAULT_PERSONA", "fallback")
        result = resolve_persona_from_headers()
        assert result == "fallback"

    def test_ultimate_default(self, monkeypatch):
        """全てなしで None 返却"""
        monkeypatch.delenv("PERSONA", raising=False)
        monkeypatch.delenv("NOUS_DEFAULT_PERSONA", raising=False)
        result = resolve_persona_from_headers()
        assert result is None

    def test_bearer_whitespace_stripped(self):
        """Bearerトークンの空白はstrip"""
        result = resolve_persona_from_headers(authorization="Bearer  alice  ")
        assert result == "alice"

    def test_empty_bearer_falls_through(self, monkeypatch):
        """Bearer直後が空なら次に落ちる"""
        monkeypatch.delenv("PERSONA", raising=False)
        monkeypatch.delenv("NOUS_DEFAULT_PERSONA", raising=False)
        result = resolve_persona_from_headers(
            authorization="Bearer   ",
            x_persona="bob",
        )
        assert result == "bob"

    def test_empty_x_persona_falls_through(self, monkeypatch):
        """X-Personaが空文字列なら次に落ちる"""
        monkeypatch.setenv("PERSONA", "env_persona")
        result = resolve_persona_from_headers(x_persona="  ")
        assert result == "env_persona"


# =========================================================================
# B. get_current_persona()
# =========================================================================


class TestGetCurrentPersona:
    def test_returns_contextvar_value(self):
        """contextvarにセットされた値を返す"""
        token = _persona_var.set("ctx_persona")
        try:
            assert get_current_persona() == "ctx_persona"
        finally:
            _persona_var.reset(token)

    def test_fallback_to_env(self, monkeypatch):
        """contextvar未セット時は環境変数"""
        monkeypatch.setenv("PERSONA", "env_persona")
        assert get_current_persona() == "env_persona"

    def test_fallback_raises_when_no_persona(self, monkeypatch):
        """contextvar未セット、環境変数もなし → PersonaRequiredError"""
        monkeypatch.delenv("PERSONA", raising=False)
        monkeypatch.delenv("NOUS_DEFAULT_PERSONA", raising=False)
        with pytest.raises(PersonaRequiredError):
            get_current_persona()


# =========================================================================
# C. resolve_persona_from_token() 後方互換
# =========================================================================


class TestResolvePersonaFromToken:
    def test_with_bearer(self):
        result = resolve_persona_from_token("Bearer alice")
        assert result == "alice"

    def test_without_bearer(self, monkeypatch):
        monkeypatch.setenv("PERSONA", "env_persona")
        result = resolve_persona_from_token(None)
        assert result == "env_persona"


# =========================================================================
# D. PersonaMiddleware (ASGI level)
# =========================================================================


class TestPersonaMiddleware:
    """ASGIミドルウェアの統合テスト"""

    async def test_bearer_header(self):
        """Authorization Bearerヘッダーでペルソナ解決"""
        captured_persona = None

        async def app(scope, receive, send):  # noqa: ARG001
            nonlocal captured_persona
            captured_persona = get_current_persona()
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b""})

        middleware = PersonaMiddleware(app)
        scope = {
            "type": "http",
            "headers": [(b"authorization", b"Bearer alice")],
        }
        await middleware(scope, None, lambda msg: _noop_send(msg))
        assert captured_persona == "alice"

    async def test_x_persona_header(self):
        """X-Personaヘッダーでペルソナ解決"""
        captured_persona = None

        async def app(scope, receive, send):  # noqa: ARG001
            nonlocal captured_persona
            captured_persona = get_current_persona()
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b""})

        middleware = PersonaMiddleware(app)
        scope = {
            "type": "http",
            "headers": [(b"x-persona", b"bob")],
        }
        await middleware(scope, None, lambda msg: _noop_send(msg))
        assert captured_persona == "bob"

    async def test_bearer_over_x_persona(self):
        """BearerがX-Personaより優先"""
        captured_persona = None

        async def app(scope, receive, send):  # noqa: ARG001
            nonlocal captured_persona
            captured_persona = get_current_persona()
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b""})

        middleware = PersonaMiddleware(app)
        scope = {
            "type": "http",
            "headers": [
                (b"authorization", b"Bearer alice"),
                (b"x-persona", b"bob"),
            ],
        }
        await middleware(scope, None, lambda msg: _noop_send(msg))
        assert captured_persona == "alice"

    async def test_no_headers_fallback(self, monkeypatch):
        """ヘッダーなしで環境変数フォールバック"""
        monkeypatch.setenv("PERSONA", "env_persona")
        captured_persona = None

        async def app(scope, receive, send):  # noqa: ARG001
            nonlocal captured_persona
            captured_persona = get_current_persona()
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b""})

        middleware = PersonaMiddleware(app)
        scope = {"type": "http", "headers": []}
        await middleware(scope, None, lambda msg: _noop_send(msg))
        assert captured_persona == "env_persona"

    async def test_contextvar_reset_after_request(self):
        """リクエスト後にcontextvarがリセットされる"""

        async def app(scope, receive, send):  # noqa: ARG001
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b""})

        middleware = PersonaMiddleware(app)
        scope = {
            "type": "http",
            "headers": [(b"x-persona", b"temp_persona")],
        }
        await middleware(scope, None, lambda msg: _noop_send(msg))
        assert _persona_var.get() is None

    async def test_non_http_scope_passthrough(self):
        """非HTTPスコープはパススルー"""
        called = False

        async def app(scope, receive, send):  # noqa: ARG001
            nonlocal called
            called = True

        middleware = PersonaMiddleware(app)
        scope = {"type": "websocket"}
        await middleware(scope, None, None)
        assert called is True


# =========================================================================
# D2. PersonaMiddleware + ?token= query param (SSE / EventSource)
# =========================================================================


class TestQueryTokenAuth:
    """SSE (EventSource) can't send headers — ?token= acts as Bearer-equivalent."""

    @pytest.fixture()
    def _strict_key(self, monkeypatch, tmp_path):
        from nous.config.runtime_config import RuntimeConfigManager
        from nous.config.settings import Settings

        RuntimeConfigManager.reset()
        monkeypatch.delenv("NOUS_API_KEY", raising=False)
        monkeypatch.setattr(
            "nous.config.runtime_config.get_settings",
            lambda: Settings(data_root=str(tmp_path)),
        )
        RuntimeConfigManager().update("general", "api_key", "x" * 16)
        yield
        RuntimeConfigManager.reset()

    @staticmethod
    def _capture_app(captured: dict) -> object:
        async def app(scope, receive, send):  # noqa: ARG001
            captured["persona"] = get_current_persona()
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b""})

        return app

    @staticmethod
    async def _run(app, scope) -> list[dict]:
        messages: list[dict] = []

        async def send(msg: dict) -> None:
            messages.append(msg)

        await PersonaMiddleware(app)(scope, None, send)  # type: ignore[arg-type]
        return messages

    async def test_valid_query_token_passes(self, _strict_key):
        """api_key 設定下で ?token= が正当なら通過（X-Persona で persona 解決）"""
        captured: dict = {}
        scope = {
            "type": "http",
            "headers": [(b"x-persona", b"alice")],
            "query_string": b"token=" + b"x" * 16,
        }
        messages = await self._run(self._capture_app(captured), scope)
        assert captured["persona"] == "alice"
        assert messages[0]["status"] == 200

    async def test_invalid_query_token_401(self, _strict_key):
        """不正 token は 401 のまま"""
        captured: dict = {}
        scope = {
            "type": "http",
            "headers": [],
            "query_string": b"token=wrong",
        }
        messages = await self._run(self._capture_app(captured), scope)
        assert "persona" not in captured
        assert messages[0]["status"] == 401

    async def test_missing_token_401_in_strict_mode(self, _strict_key):
        """token 無し（ヘッダも無し）は strict mode で 401"""
        captured: dict = {}
        scope = {"type": "http", "headers": [], "query_string": b"persona=alice"}
        messages = await self._run(self._capture_app(captured), scope)
        assert "persona" not in captured
        assert messages[0]["status"] == 401

    async def test_header_wins_over_query_token(self, _strict_key):
        """Authorization ヘッダーがある時は ?token= を無視"""
        captured: dict = {}
        scope = {
            "type": "http",
            "headers": [(b"authorization", b"Bearer " + b"x" * 16), (b"x-persona", b"alice")],
            "query_string": b"token=wrong",
        }
        messages = await self._run(self._capture_app(captured), scope)
        assert captured["persona"] == "alice"
        assert messages[0]["status"] == 200

    async def test_dev_mode_query_token_ignored(self, monkeypatch):
        """dev pass-through（key 空）では token は無くても通る"""
        monkeypatch.delenv("NOUS_API_KEY", raising=False)
        captured: dict = {}
        scope = {"type": "http", "headers": [(b"x-persona", b"alice")], "query_string": b""}
        messages = await self._run(self._capture_app(captured), scope)
        assert captured["persona"] == "alice"
        assert messages[0]["status"] == 200


# =========================================================================
# E. _resolve_persona() in tools.py
# =========================================================================


class TestResolvePersonaInTools:
    def test_uses_get_current_persona(self):
        """tools._resolve_persona()がget_current_persona()を経由"""
        import nous.api.mcp.tools as tools_module

        token = _persona_var.set("tool_persona")
        try:
            result = tools_module._resolve_persona()
            assert result == "tool_persona"
        finally:
            _persona_var.reset(token)
