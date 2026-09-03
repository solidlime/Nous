"""Unit tests for Plugin API authentication.

Verifies that the ``POST /api/events/ingest`` endpoint enforces
the ``PluginConfig`` security policy:
- Default (disabled) → 403
- Enabled without api_key → 500
- Enabled + wrong/missing key → 401
- Enabled + valid key → 200
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from starlette.testclient import TestClient

from nous.config.settings import PluginConfig, Settings
from nous.main import MemoryFastMCP

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_settings(plugin: PluginConfig | None = None) -> Settings:
    """Create Settings with the given PluginConfig (or default)."""
    s = Settings(plugin=plugin or PluginConfig())
    s.cors.allowed_origins = ["*"]
    return s


def _make_app(settings: Settings | None = None) -> TestClient:
    """Build a minimal app with events routes and return a TestClient."""
    if settings is None:
        settings = _make_settings()

    from nous.api.http.routers.events import register_events_routes

    mcp = MemoryFastMCP("test")

    register_events_routes(mcp)

    # Patch get_settings so the app creation uses our fixture
    import nous.main as main_mod

    original_getter = main_mod.get_settings
    main_mod.get_settings = lambda: settings  # type: ignore[method-assign]
    try:
        app = mcp.streamable_http_app()
        return TestClient(app)
    finally:
        main_mod.get_settings = original_getter


def _mock_context(persona: str, settings: Settings) -> MagicMock:
    """Build a mock AppContext with the given settings."""
    ctx = MagicMock()
    ctx.settings = settings
    ctx.connection.get_memory_db.return_value = MagicMock()
    ctx.event_bus = MagicMock()
    return ctx


def _valid_body(persona: str = "herta-test") -> dict:
    return {
        "session_id": "sess_001",
        "persona": persona,
        "events": [
            {"type": "tool_call", "summary": "test event"},
        ],
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestPluginAuthCommon:
    """Shared fixture: mock _safe_get_context to return a context with
    the given PluginConfig so we can test auth logic without needing
    the full AppContextRegistry."""

    @pytest.fixture
    def settings(self) -> Settings:
        """Override in subclasses with desired PluginConfig."""
        return _make_settings()

    @pytest.fixture
    def client(self, settings: Settings) -> TestClient:
        return _make_app(settings)

    def _post(self, client: TestClient, headers: dict | None = None):
        with patch(
            "nous.api.http.routers.events._safe_get_context",
            return_value=_mock_context("herta-test", client._settings),  # noqa
        ):
            return client.post(
                "/api/events/ingest",
                json=_valid_body(),
                headers=headers or {},
            )


class TestPluginAuthDisabled:
    """Plugin API disabled by default — all requests rejected."""

    def test_default_disabled_returns_403(self):
        """Default PluginConfig (enabled=False) → 403."""
        # Use a mock context with default (disabled) settings
        settings = _make_settings()
        client = _make_app(settings)
        with patch(
            "nous.api.http.routers.events._safe_get_context",
            return_value=_mock_context("herta-test", settings),
        ):
            resp = client.post("/api/events/ingest", json=_valid_body())
        assert resp.status_code == 403
        body = resp.json()
        assert "disabled" in body.get("error", "").lower()


class TestPluginAuthEnabledNoKey:
    """Enabled but no api_key → misconfiguration error."""

    PLUGIN = PluginConfig(enabled=True, api_key="")

    def test_enabled_no_key_returns_500(self):
        """PluginConfig(enabled=True, api_key="") → 500."""
        settings = _make_settings(plugin=self.PLUGIN)
        client = _make_app(settings)
        with patch(
            "nous.api.http.routers.events._safe_get_context",
            return_value=_mock_context("herta-test", settings),
        ):
            resp = client.post("/api/events/ingest", json=_valid_body())
        assert resp.status_code == 500
        body = resp.json()
        assert "misconfigured" in body.get("error", "").lower()


class TestPluginAuthValidKey:
    """Plugin enabled with valid key — auth required."""

    PLUGIN = PluginConfig(enabled=True, api_key="secr3t-k3y")

    @pytest.fixture
    def settings_with_plugin(self) -> Settings:
        return _make_settings(plugin=self.PLUGIN)

    def _do_request(self, headers: dict | None = None):
        settings = _make_settings(plugin=self.PLUGIN)
        client = _make_app(settings)
        with patch(
            "nous.api.http.routers.events._safe_get_context",
            return_value=_mock_context("herta-test", settings),
        ):
            return client.post("/api/events/ingest", json=_valid_body(), headers=headers or {})

    def test_missing_auth_header_returns_401(self):
        """No Authorization header → 401."""
        resp = self._do_request()
        assert resp.status_code == 401
        body = resp.json()
        assert "authorization" in body.get("error", "").lower()

    def test_wrong_key_returns_401(self):
        """Wrong Bearer token → 401."""
        resp = self._do_request(headers={"Authorization": "Bearer wrong-key"})
        assert resp.status_code == 401
        body = resp.json()
        assert "invalid" in body.get("error", "").lower()

    def test_correct_key_returns_200(self):
        """Valid Bearer token → 200 (if persona context exists)."""
        resp = self._do_request(headers={"Authorization": "Bearer secr3t-k3y"})
        assert resp.status_code == 200
        body = resp.json()
        assert body.get("status") == "ok"

    def test_non_bearer_auth_returns_401(self):
        """Authorization header without Bearer scheme → 401."""
        resp = self._do_request(headers={"Authorization": "Basic dXNlcjpwYXNz"})
        assert resp.status_code == 401


class TestPluginAuthSettings:
    """PluginConfig model defaults and env integration."""

    def test_plugin_config_defaults(self):
        """PluginConfig default: enabled=False, api_key=""."""
        cfg = PluginConfig()
        assert cfg.enabled is False
        assert cfg.api_key == ""

    def test_settings_plugin_defaults(self):
        """Settings().plugin defaults to disabled."""
        s = Settings()
        assert s.plugin.enabled is False
        assert s.plugin.api_key == ""
