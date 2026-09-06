"""Unit tests for SecurityHeadersMiddleware (oracle Q3 contract)."""

from __future__ import annotations

import pytest
from starlette.responses import PlainTextResponse
from starlette.testclient import TestClient

from nous.api.http.middleware import SecurityHeadersMiddleware
from nous.main import MemoryFastMCP

pytestmark = pytest.mark.unit


def _client(**kwargs) -> TestClient:
    async def _app(scope, receive, send):
        assert scope["type"] == "http"
        await PlainTextResponse("ok")(scope, receive, send)

    return TestClient(SecurityHeadersMiddleware(_app), **kwargs)


class TestSecurityHeaders:
    EXPECTED = {
        "content-security-policy": "default-src 'self'; base-uri 'self'; object-src 'none'; frame-ancestors 'none'; script-src 'self' https://cdn.tailwindcss.com https://cdn.jsdelivr.net https://unpkg.com https://cdnjs.cloudflare.com; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com https://unpkg.com https://cdnjs.cloudflare.com; img-src 'self' data: blob:; font-src 'self' https://fonts.gstatic.com; connect-src 'self' https://fonts.googleapis.com https://fonts.gstatic.com; media-src 'self' data: blob:",
        "x-content-type-options": "nosniff",
        "x-frame-options": "DENY",
        "referrer-policy": "strict-origin-when-cross-origin",
        "permissions-policy": "camera=(), microphone=(), geolocation=()",
        "cross-origin-opener-policy": "same-origin",
    }

    def test_headers_present_over_http(self):
        resp = _client().get("/")
        assert resp.status_code == 200
        for name, value in self.EXPECTED.items():
            assert resp.headers.get(name) == value

    def test_no_hsts_over_http(self):
        resp = _client().get("/")
        assert "strict-transport-security" not in resp.headers

    def test_hsts_only_over_https(self):
        resp = _client(base_url="https://testserver").get("/")
        assert resp.status_code == 200
        assert resp.headers.get("strict-transport-security") == "max-age=31536000; includeSubDomains"
        for name, value in self.EXPECTED.items():
            assert resp.headers.get(name) == value

    def test_middleware_registered_in_app(self):
        import nous.main as main_mod
        from nous.config.settings import Settings

        original_getter = main_mod.get_settings
        main_mod.get_settings = lambda: Settings()  # type: ignore[method-assign]
        try:
            app = MemoryFastMCP("test").streamable_http_app()
            middleware_types = [m.cls for m in app.user_middleware]
            assert SecurityHeadersMiddleware in middleware_types
        finally:
            main_mod.get_settings = original_getter
