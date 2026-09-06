"""Unit tests for persona resolution + API-key auth (oracle Q1 contract)."""

from __future__ import annotations

import pytest
from starlette.exceptions import HTTPException
from starlette.requests import Request

from nous.api.http.deps import _resolve_persona_from_request
from nous.api.mcp.middleware import (
    PersonaAuthError,
    PersonaRequiredError,
    resolve_persona,
)

pytestmark = pytest.mark.unit


def _request(
    *,
    path_persona: str | None = None,
    authorization: str | None = None,
    x_persona: str | None = None,
) -> Request:
    headers: list[tuple[bytes, bytes]] = []
    if authorization is not None:
        headers.append((b"authorization", authorization.encode("latin-1")))
    if x_persona is not None:
        headers.append((b"x-persona", x_persona.encode("latin-1")))
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/",
        "headers": headers,
        "query_string": b"",
        "path_params": {"persona": path_persona} if path_persona is not None else {},
    }
    return Request(scope)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    monkeypatch.delenv("NOUS_API_KEY", raising=False)
    monkeypatch.delenv("PERSONA", raising=False)
    monkeypatch.delenv("NOUS_DEFAULT_PERSONA", raising=False)


# =========================================================================
# Dev pass-through (NOUS_API_KEY empty)
# =========================================================================


class TestDevPassthrough:
    def test_path_beats_bearer(self):
        assert resolve_persona("pathp", "Bearer bd", "xp") == "pathp"

    def test_bearer_beats_x_persona(self):
        assert resolve_persona(None, "Bearer bdp", "xp") == "bdp"

    def test_x_persona_beats_default(self):
        assert resolve_persona(None, None, "xp", default="dflt") == "xp"

    def test_default_beats_env(self, monkeypatch):
        monkeypatch.setenv("PERSONA", "envp")
        assert resolve_persona(None, None, None, default="dflt") == "dflt"

    def test_env_fallback(self, monkeypatch):
        monkeypatch.setenv("PERSONA", "envp")
        assert resolve_persona(None, None, None) == "envp"

    def test_nothing_raises(self):
        with pytest.raises(PersonaRequiredError):
            resolve_persona(None, None, None)

    def test_invalid_path_raises_value_error(self):
        with pytest.raises(ValueError):
            resolve_persona("../evil!", None, None)

    def test_invalid_bearer_falls_through_to_x_persona(self):
        assert resolve_persona(None, "Bearer ../evil!", "xp") == "xp"

    def test_invalid_x_persona_falls_through_to_default(self):
        assert resolve_persona(None, None, "not valid!!", default="dflt") == "dflt"


# =========================================================================
# Strict mode (NOUS_API_KEY non-empty)
# =========================================================================


class TestStrictMode:
    def test_matching_key_with_x_persona(self):
        assert resolve_persona(None, "Bearer s3cret", "xp", api_key="s3cret") == "xp"

    def test_bearer_is_credential_not_persona(self, monkeypatch):
        """Bearer==key の値はpersonaにならない。persona未指定なら env/default へ。"""
        monkeypatch.setenv("PERSONA", "envp")
        assert resolve_persona(None, "Bearer s3cret", None, api_key="s3cret") == "envp"

    def test_mismatched_key_401(self):
        with pytest.raises(PersonaAuthError):
            resolve_persona(None, "Bearer wrong", "xp", api_key="s3cret")

    def test_missing_key_401(self):
        with pytest.raises(PersonaAuthError):
            resolve_persona(None, None, "xp", api_key="s3cret")

    def test_key_from_env(self, monkeypatch):
        monkeypatch.setenv("NOUS_API_KEY", "envkey")
        assert resolve_persona(None, "Bearer envkey", "xp") == "xp"
        with pytest.raises(PersonaAuthError):
            resolve_persona(None, "Bearer nope", "xp")

    def test_path_still_validated(self):
        with pytest.raises(ValueError):
            resolve_persona("../evil!", "Bearer s3cret", None, api_key="s3cret")
        assert resolve_persona("pathp", "Bearer s3cret", "xp", api_key="s3cret") == "pathp"


# =========================================================================
# deps.py mapping (401 / 400)
# =========================================================================


class TestDepsMapping:
    def test_bearer_mismatch_is_401(self):
        req = _request(authorization="Bearer wrong", x_persona="xp")
        with pytest.raises(HTTPException) as exc_info:
            _resolve_persona_from_request(req, api_key="s3cret")
        assert exc_info.value.status_code == 401

    def test_invalid_path_is_400(self):
        req = _request(path_persona="../evil!")
        with pytest.raises(HTTPException) as exc_info:
            _resolve_persona_from_request(req)
        assert exc_info.value.status_code == 400

    def test_no_persona_is_401(self):
        with pytest.raises(HTTPException) as exc_info:
            _resolve_persona_from_request(_request())
        assert exc_info.value.status_code == 401

    def test_dev_path_ok(self):
        req = _request(path_persona="pathp")
        assert _resolve_persona_from_request(req) == "pathp"
