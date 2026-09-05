"""Unit tests for CORS middleware configuration.

Verifies that CORSMiddleware is added to the Starlette ASGI app and
that ``Access-Control-Allow-Origin`` headers are returned correctly.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from starlette.middleware.cors import CORSMiddleware
from starlette.responses import Response
from starlette.testclient import TestClient

from nous.config.settings import CorsConfig, Settings
from nous.main import MemoryFastMCP

if TYPE_CHECKING:
    from starlette.requests import Request

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_app(settings: Settings | None = None) -> TestClient:
    """Build a minimal MemoryFastMCP with the given settings and return a TestClient."""
    if settings is None:
        settings = Settings(cors=CorsConfig(allowed_origins=["*"]))

    mcp = MemoryFastMCP("test")

    @mcp.custom_route("/test-cors", methods=["GET", "OPTIONS"])
    async def test_cors(request: Request) -> Response:  # noqa: ARG001
        return Response("ok", media_type="text/plain")

    # Monkey-patch get_settings so the CORS config comes from our fixture
    import nous.main as main_mod

    original_getter = main_mod.get_settings
    main_mod.get_settings = lambda: settings  # type: ignore[method-assign]
    try:
        app = mcp.streamable_http_app()
        return TestClient(app)
    finally:
        main_mod.get_settings = original_getter


# =========================================================================
# A. CORSMiddleware is present in the middleware stack
# =========================================================================


class TestCORSMiddlewarePresence:
    def test_middleware_is_registered(self):
        """MemoryFastMCP.streamable_http_app() のStarlette appにCORSMiddlewareが含まれる"""
        settings = Settings(cors=CorsConfig(allowed_origins=["*"]))
        mcp = MemoryFastMCP("test")

        import nous.main as main_mod

        original_getter = main_mod.get_settings
        main_mod.get_settings = lambda: settings  # type: ignore[method-assign]
        try:
            app = mcp.streamable_http_app()
            middleware_types = [m.cls for m in app.user_middleware]
            assert CORSMiddleware in middleware_types
        finally:
            main_mod.get_settings = original_getter


# =========================================================================
# B. OPTIONS preflight が通る
# =========================================================================

# Starlette CORSMiddleware behavior notes:
# - With allow_origins=["*"], Starlette>=1 returns ACAO '*' (no origin reflection).
# - With allow_origins=["*"] and no Origin header, no ACAO is added.
# - With allow_origins=["*"] and allow_headers=["*"], ACAH reflects
#   the requested headers, or is omitted if none were requested.


class TestCorsPreflight:
    def test_options_preflight_wildcard_origin(self):
        """OPTIONS：allow_origins=["*"] でリクエストOriginをエコーバック"""
        client = _make_app()
        resp = client.options("/test-cors", headers={"Origin": "http://example.com"})
        assert resp.status_code == 200
        # Starlette>=1 returns '*' for wildcard origins (no reflection)
        assert resp.headers.get("access-control-allow-origin") == "*"

    def test_options_preflight_specific_origin(self):
        """許可リストに含まれるoriginが通る"""
        settings = Settings(cors=CorsConfig(allowed_origins=["http://myapp.example.com"]))
        client = _make_app(settings)
        resp = client.options("/test-cors", headers={"Origin": "http://myapp.example.com"})
        assert resp.status_code == 200
        assert resp.headers.get("access-control-allow-origin") == "http://myapp.example.com"

    def test_options_preflight_rejected_origin(self):
        """許可リストにないoriginはブロック（ACAOなし）"""
        settings = Settings(cors=CorsConfig(allowed_origins=["http://trusted.example.com"]))
        client = _make_app(settings)
        resp = client.options("/test-cors", headers={"Origin": "http://evil.example.com"})
        assert resp.status_code == 200  # OPTIONS returns 200 but no ACAO
        assert resp.headers.get("access-control-allow-origin") is None

    def test_options_preflight_multiple_origins(self):
        """複数originsのいずれかが通る"""
        settings = Settings(cors=CorsConfig(allowed_origins=["http://a.com", "http://b.com"]))
        client = _make_app(settings)
        resp = client.options("/test-cors", headers={"Origin": "http://b.com"})
        assert resp.status_code == 200
        assert resp.headers.get("access-control-allow-origin") == "http://b.com"

    def test_options_preflight_allow_credentials(self):
        """OPTIONSがAccess-Control-Allow-Credentialsを含む（明示origins + credentials=True）"""
        settings = Settings(cors=CorsConfig(allowed_origins=["http://example.com"], allow_credentials=True))
        client = _make_app(settings)
        resp = client.options("/test-cors", headers={"Origin": "http://example.com"})
        assert resp.headers.get("access-control-allow-credentials") == "true"

    def test_options_preflight_allowed_methods(self):
        """OPTIONSがAccess-Control-Allow-Methodsを含む"""
        client = _make_app()
        resp = client.options(
            "/test-cors",
            headers={
                "Origin": "http://example.com",
                "Access-Control-Request-Method": "GET",
            },
        )
        assert resp.headers.get("access-control-allow-methods") is not None


# =========================================================================
# C. GET レスポンスに CORS ヘッダが含まれる
# =========================================================================


class TestCorsOnGet:
    def test_get_has_acao_header(self):
        """GET：allow_origins=["*"] でリクエストOriginをエコーバック"""
        client = _make_app()
        resp = client.get("/test-cors", headers={"Origin": "http://example.com"})
        assert resp.status_code == 200
        # Starlette>=1 returns '*' for wildcard origins (no reflection)
        assert resp.headers.get("access-control-allow-origin") == "*"

    def test_get_no_origin_no_cors(self):
        """Originヘッダなし → ACAOは付かない"""
        client = _make_app()
        resp = client.get("/test-cors")
        assert resp.status_code == 200
        # Starlette CORSMiddleware doesn't add ACAO when no Origin header
        assert resp.headers.get("access-control-allow-origin") is None

    def test_get_specific_origin(self):
        """許可された特定originが通る"""
        settings = Settings(cors=CorsConfig(allowed_origins=["http://localhost:3000"]))
        client = _make_app(settings)
        resp = client.get("/test-cors", headers={"Origin": "http://localhost:3000"})
        assert resp.status_code == 200
        assert resp.headers.get("access-control-allow-origin") == "http://localhost:3000"

    def test_get_rejected_origin(self):
        """許可されていないoriginはACAOなし"""
        settings = Settings(cors=CorsConfig(allowed_origins=["http://localhost:3000"]))
        client = _make_app(settings)
        resp = client.get("/test-cors", headers={"Origin": "http://evil.com"})
        assert resp.status_code == 200
        assert resp.headers.get("access-control-allow-origin") is None

    def test_get_returns_allow_credentials(self):
        """GETがAccess-Control-Allow-Credentialsを含む（明示origins + credentials=True）"""
        settings = Settings(cors=CorsConfig(allowed_origins=["http://example.com"], allow_credentials=True))
        client = _make_app(settings)
        resp = client.get("/test-cors", headers={"Origin": "http://example.com"})
        assert resp.headers.get("access-control-allow-credentials") == "true"


# =========================================================================
# D. CorsConfig model の env var マッピング
# =========================================================================


class TestCorsConfigFromEnv:
    def test_allowed_origins_from_comma_separated(self, monkeypatch):
        """NOUS_CORS_ALLOWED_ORIGINS カンマ区切りがlistに変換される"""
        monkeypatch.setenv("NOUS_CORS_ALLOWED_ORIGINS", "http://a.com,http://b.com")
        settings = Settings()
        assert settings.cors.allowed_origins == ["http://a.com", "http://b.com"]

    def test_allowed_origins_from_json(self, monkeypatch):
        """NOUS_CORS_ALLOWED_ORIGINS JSON配列もパースできる"""
        monkeypatch.setenv("NOUS_CORS_ALLOWED_ORIGINS", '["http://x.com","http://y.com"]')
        settings = Settings()
        assert settings.cors.allowed_origins == ["http://x.com", "http://y.com"]

    def test_allowed_origins_nested_json(self, monkeypatch):
        """NOUS_CORS__ALLOWED_ORIGINS (nested) はJSON形式必須"""
        monkeypatch.setenv("NOUS_CORS__ALLOWED_ORIGINS", '["http://z.com"]')
        settings = Settings()
        assert settings.cors.allowed_origins == ["http://z.com"]

    def test_cors_env_not_set_uses_default(self, monkeypatch):
        """NOUS_CORS_ALLOWED_ORIGINS 未設定 → 明示localhostデフォルト"""
        monkeypatch.delenv("NOUS_CORS_ALLOWED_ORIGINS", raising=False)
        settings = Settings()
        assert settings.cors.allowed_origins == [
            "http://localhost:3000",
            "http://127.0.0.1:3000",
            "http://localhost:5173",
            "http://127.0.0.1:5173",
        ]

    def test_default_is_explicit_localhost(self):
        """未設定時のデフォルトは明示localhost origins（ワイルドカード禁止）"""
        settings = Settings()
        assert settings.cors.allowed_origins == [
            "http://localhost:3000",
            "http://127.0.0.1:3000",
            "http://localhost:5173",
            "http://127.0.0.1:5173",
        ]
        assert "*" not in settings.cors.allowed_origins

    def test_allow_credentials_default_true(self):
        """allow_credentials デフォルト True は明示originsと両立し維持される"""
        settings = Settings()
        assert settings.cors.allow_credentials is True

    def test_explicit_origins_keep_allow_credentials(self):
        """明示 origins なら allow_credentials=True は維持される"""
        settings = Settings(cors=CorsConfig(allowed_origins=["http://a.com"], allow_credentials=True))
        assert settings.cors.allow_credentials is True

    def test_wildcard_forces_credentials_off_with_warning(self, caplog):
        """ワイルドカード origins 時は allow_credentials 強制 False + 警告ログ"""
        import logging

        with caplog.at_level(logging.WARNING):
            settings = Settings(cors=CorsConfig(allowed_origins=["*"], allow_credentials=True))
        assert settings.cors.allow_credentials is False
        assert "allow_credentials" in caplog.text

    def test_allow_methods_default_explicit(self):
        """allow_methods のデフォルトは明示メソッドリスト"""
        settings = Settings()
        assert settings.cors.allow_methods == ["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"]

    def test_allow_headers_default_explicit(self):
        """allow_headers のデフォルトは明示ヘッダリスト"""
        settings = Settings()
        assert settings.cors.allow_headers == ["Authorization", "Content-Type", "X-Persona"]

    def test_default_origins_allow_localhost_dev(self):
        """デフォルト設定で localhost:3000 からのGETにACAOが付く"""
        client = _make_app(Settings())
        resp = client.get("/test-cors", headers={"Origin": "http://localhost:3000"})
        assert resp.status_code == 200
        assert resp.headers.get("access-control-allow-origin") == "http://localhost:3000"
