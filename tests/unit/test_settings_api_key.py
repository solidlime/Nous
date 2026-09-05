"""Unit tests for WebUI API-key management (oracle Q9 contract)."""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from nous.api.http.routers.admin import register_admin_routes
from nous.api.mcp.middleware import PersonaAuthError, resolve_persona
from nous.config.runtime_config import SETTINGS_META, RuntimeConfigManager

pytestmark = pytest.mark.unit

LONG_KEY = "x" * 16
OTHER_KEY = "y" * 16


@pytest.fixture(autouse=True)
def _reset_singleton():
    RuntimeConfigManager.reset()
    yield
    RuntimeConfigManager.reset()


@pytest.fixture()
def tmp_data_dir(tmp_path, monkeypatch):
    """Isolate overrides file + API-key env for each test."""
    from nous.config.settings import Settings

    monkeypatch.delenv("NOUS_API_KEY", raising=False)
    mock_settings = Settings(data_root=str(tmp_path))
    with patch("nous.config.runtime_config.get_settings", return_value=mock_settings):
        yield tmp_path


@pytest.fixture()
def handlers():
    """Capture admin route handlers without booting the app."""
    captured: dict = {}

    class FakeMcp:
        def custom_route(self, path, methods):
            def deco(fn):
                for method in methods:
                    captured[(path, method)] = fn
                return fn

            return deco

    register_admin_routes(FakeMcp())
    return captured


class _FakeRequest:
    def __init__(self, body=None, authorization=None):
        self._body = body or {}
        self.headers = {"authorization": authorization} if authorization else {}

    async def json(self):
        return self._body


def _put(handlers, body, authorization=None):
    return handlers[("/api/settings", "PUT")](_FakeRequest(body, authorization))


def _body(resp):
    return json.loads(resp.body)


def _set_key(value):
    RuntimeConfigManager().update("general", "api_key", value)


def _effective():
    return RuntimeConfigManager().get_effective_value("general", "api_key")[0]


class TestSettingsMeta:
    def test_api_key_meta(self, tmp_data_dir):
        meta = SETTINGS_META["general"]["api_key"]
        assert meta["hot_reload"] is True
        assert meta["masked"] is True


class TestBootstrap:
    async def test_bootstrap_sets_key_without_auth(self, tmp_data_dir, handlers):
        resp = await _put(handlers, {"category": "general", "key": "api_key", "value": LONG_KEY})
        assert resp.status_code == 200
        assert _effective() == LONG_KEY

    async def test_short_value_rejected(self, tmp_data_dir, handlers):
        resp = await _put(handlers, {"category": "general", "key": "api_key", "value": "short"})
        assert resp.status_code == 400
        assert _effective() != "short"


class TestChangeAndClear:
    async def test_change_without_old_key_is_401(self, tmp_data_dir, handlers):
        _set_key(LONG_KEY)
        resp = await _put(handlers, {"category": "general", "key": "api_key", "value": OTHER_KEY})
        assert resp.status_code == 401
        resp = await _put(
            handlers,
            {"category": "general", "key": "api_key", "value": OTHER_KEY},
            authorization="Bearer wrong-key-zzzzzz",
        )
        assert resp.status_code == 401
        assert _effective() == LONG_KEY

    async def test_change_with_old_key_ok(self, tmp_data_dir, handlers):
        _set_key(LONG_KEY)
        resp = await _put(
            handlers,
            {"category": "general", "key": "api_key", "value": OTHER_KEY},
            authorization=f"Bearer {LONG_KEY}",
        )
        assert resp.status_code == 200
        assert _effective() == OTHER_KEY

    async def test_short_value_with_auth_is_400(self, tmp_data_dir, handlers):
        _set_key(LONG_KEY)
        resp = await _put(
            handlers,
            {"category": "general", "key": "api_key", "value": "short"},
            authorization=f"Bearer {LONG_KEY}",
        )
        assert resp.status_code == 400
        assert _effective() == LONG_KEY

    async def test_clear_restores_bootstrap(self, tmp_data_dir, handlers):
        _set_key(LONG_KEY)
        resp = await _put(
            handlers,
            {"category": "general", "key": "api_key", "value": ""},
            authorization=f"Bearer {LONG_KEY}",
        )
        assert resp.status_code == 200
        assert not _effective()
        # Bootstrap works again without auth.
        resp = await _put(handlers, {"category": "general", "key": "api_key", "value": OTHER_KEY})
        assert resp.status_code == 200
        assert _effective() == OTHER_KEY

    async def test_other_keys_ungated(self, tmp_data_dir, handlers):
        resp = await _put(handlers, {"category": "general", "key": "timezone", "value": "UTC"})
        assert resp.status_code == 200


class TestGetMasked:
    async def test_get_never_returns_plaintext(self, tmp_data_dir, handlers):
        _set_key(LONG_KEY)
        resp = await handlers[("/api/settings", "GET")](_FakeRequest())
        assert resp.status_code == 200
        payload = _body(resp)
        assert payload["settings"]["general"]["api_key"]["value"] == "***"
        assert LONG_KEY not in resp.body.decode()


class TestMiddlewareUsesRuntimeValue:
    def test_override_key_enforced_without_env(self, tmp_data_dir):
        _set_key(LONG_KEY)
        assert resolve_persona(None, f"Bearer {LONG_KEY}", "p") == "p"
        with pytest.raises(PersonaAuthError):
            resolve_persona(None, "Bearer wrong-key-zzzzzz", "p")

    def test_env_key_still_works(self, tmp_data_dir, monkeypatch):
        monkeypatch.setenv("NOUS_API_KEY", LONG_KEY)
        assert resolve_persona(None, f"Bearer {LONG_KEY}", "p") == "p"
        with pytest.raises(PersonaAuthError):
            resolve_persona(None, "Bearer wrong-key-zzzzzz", "p")
