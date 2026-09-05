from __future__ import annotations

import contextvars
import os
import re
import secrets
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from starlette.types import ASGIApp, Receive, Scope, Send

# Per-request persona resolved from HTTP headers.
_persona_var: contextvars.ContextVar[str | None] = contextvars.ContextVar("_persona_var", default=None)

_PERSONA_PATTERN = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")


def _env_persona() -> str | None:
    """Resolve persona from environment variables."""
    return os.environ.get("PERSONA") or os.environ.get("NOUS_DEFAULT_PERSONA") or None


class PersonaAuthError(Exception):
    """Raised when the ``NOUS_API_KEY`` check fails. Maps to HTTP 401."""

    status_code = 401


def _resolve_api_key(api_key: str | None) -> str:
    """Return the effective API key.

    Explicit *api_key* wins; otherwise resolve via
    ``RuntimeConfigManager.get_effective_value("general", "api_key")``
    (override > ``NOUS_API_KEY`` env > ``Settings.api_key``). ``get_settings``
    is ``lru_cache``-d so it must not be read directly here.
    """
    if api_key is not None:
        return api_key.strip() if api_key else ""
    try:
        from nous.config.runtime_config import RuntimeConfigManager

        value, _ = RuntimeConfigManager().get_effective_value("general", "api_key")
    except Exception:
        value = None
    if value is None:
        return (os.environ.get("NOUS_API_KEY") or "").strip()
    return str(value).strip() if value else ""


def _keys_equal(provided: str, expected: str) -> bool:
    """Constant-time key comparison (``False`` on non-ASCII input)."""
    try:
        return secrets.compare_digest(provided, expected)
    except TypeError:
        return False


def verify_bearer(authorization: str | None, effective_key: str) -> bool:
    """Return True when *authorization* is exactly ``Bearer <effective_key>``."""
    if not authorization or not effective_key:
        return False
    scheme, _, token = authorization.strip().partition(" ")
    return scheme == "Bearer" and bool(token) and _keys_equal(token, effective_key)


def _valid_persona(value: object) -> str | None:
    """Return stripped *value* when it matches ``_PERSONA_PATTERN``, else None."""
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    if stripped and _PERSONA_PATTERN.match(stripped):
        return stripped
    return None


def resolve_persona(
    path_param: str | None,
    authorization: str | None,
    x_persona: str | None,
    *,
    default: str | None = None,
    api_key: str | None = None,
) -> str:
    """Resolve the request persona with unified priority.

    Priority: ``path_param`` > ``Bearer`` > ``X-Persona`` > ``default`` > env
    (``PERSONA`` / ``NOUS_DEFAULT_PERSONA``).

    Auth model (oracle Q1 contract):

    - ``NOUS_API_KEY=""`` (default) is a documented dev pass-through: the
      ``Bearer`` token is treated as the persona name (pattern-validated).
    - When ``NOUS_API_KEY`` (or *api_key*) is non-empty, strict mode applies:
      ``Authorization: Bearer <api_key>`` must match exactly, otherwise
      :class:`PersonaAuthError` (HTTP 401) is raised. The Bearer value is
      *only* a credential then — the persona comes from ``path_param`` /
      ``X-Persona`` / ``default`` / env.

    Path params are always pattern-validated; an invalid ``path_param``
    raises :class:`ValueError` (closes the unvalidated pass-through hole).
    Raises :class:`PersonaRequiredError` when no persona can be resolved.
    """
    effective_key = _resolve_api_key(api_key)
    if effective_key:
        if not verify_bearer(authorization, effective_key):
            raise PersonaAuthError("Invalid or missing API key")
        if path_param is not None and str(path_param).strip():
            checked = _valid_persona(path_param)
            if checked is None:
                raise ValueError(f"Invalid persona in path: {path_param!r}")
            return checked
        for candidate in (x_persona, default):
            checked = _valid_persona(candidate) if candidate is not None else None
            if checked is None and candidate is not None and isinstance(candidate, str) and candidate.strip():
                raise ValueError(f"Invalid persona header value: {candidate!r}")
            if checked:
                return checked
        env = _env_persona()
        if env and env.strip():
            return env
        raise PersonaRequiredError(
            "No persona configured. Create a persona via the WebUI or set the PERSONA environment variable."
        )

    # Dev pass-through (NOUS_API_KEY empty): Bearer doubles as persona name.
    if path_param is not None and str(path_param).strip():
        checked = _valid_persona(path_param)
        if checked is None:
            raise ValueError(f"Invalid persona in path: {path_param!r}")
        return checked
    if authorization and authorization.startswith("Bearer "):
        token = authorization[7:].strip()
        if token and _PERSONA_PATTERN.match(token):
            return token
    if x_persona:
        stripped = x_persona.strip()
        if stripped and _PERSONA_PATTERN.match(stripped):
            return stripped
    if default is not None:
        return default
    env = _env_persona()
    if env is not None:
        return env
    raise PersonaRequiredError(
        "No persona configured. Create a persona via the WebUI or set the PERSONA environment variable."
    )


def resolve_persona_from_headers(
    authorization: str | None = None,
    x_persona: str | None = None,
    *,
    default: str | None = None,
) -> str | None:
    """Resolve persona from HTTP headers with environment fallback.

    Priority: Bearer token > X-Persona header > *default* > environment variable.
    """
    if authorization and authorization.startswith("Bearer "):
        token = authorization[7:].strip()
        if token and _PERSONA_PATTERN.match(token):
            return token
    if x_persona:
        stripped = x_persona.strip()
        if stripped and _PERSONA_PATTERN.match(stripped):
            return stripped
    if default is not None:
        return default
    return _env_persona()


# Backward-compatible alias
def resolve_persona_from_token(authorization: str | None = None) -> str | None:
    """Resolve persona from Bearer token or environment."""
    return resolve_persona_from_headers(authorization=authorization)


def get_current_persona() -> str:
    """Get the persona for the current request.

    Returns the value set by :class:`PersonaMiddleware` (via *contextvars*),
    falling back to environment variables when running outside an HTTP
    request (e.g. stdio transport).

    Raises:
        PersonaRequiredError: When no persona can be resolved.
    """
    val = _persona_var.get()
    # Avoid treating empty string as valid persona
    if val and val.strip():
        return val
    env = _env_persona()
    if env and env.strip():
        return env
    raise PersonaRequiredError(
        "No persona configured. Create a persona via the WebUI or set the PERSONA environment variable."
    )


class PersonaMiddleware:
    """ASGI middleware: extracts persona from HTTP headers into a contextvar.

    Priority: path param > ``Authorization: Bearer`` > ``X-Persona`` >
              environment variables ``PERSONA`` / ``NOUS_DEFAULT_PERSONA``.
    When ``NOUS_API_KEY`` is non-empty, a mismatched Bearer short-circuits
    with HTTP 401 (credential-only mode, persona from path/X-Persona only).
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http":
            authorization: str | None = None
            x_persona: str | None = None

            for name, value in scope.get("headers", []):
                lower_name = name if isinstance(name, bytes) else name.encode()
                if lower_name == b"authorization":
                    authorization = value.decode("latin-1") if isinstance(value, bytes) else value
                elif lower_name == b"x-persona":
                    x_persona = value.decode("latin-1") if isinstance(value, bytes) else value

            _params = scope.get("path_params")
            path_param = _params.get("persona") if isinstance(_params, dict) else None
            try:
                persona: str | None = resolve_persona(path_param, authorization, x_persona)
            except PersonaAuthError:
                body = b'{"detail":"Invalid API key"}'
                await send(
                    {
                        "type": "http.response.start",
                        "status": 401,
                        "headers": [
                            (b"content-type", b"application/json"),
                            (b"content-length", str(len(body)).encode("latin-1")),
                        ],
                    }
                )
                await send({"type": "http.response.body", "body": body})
                return
            except (PersonaRequiredError, ValueError):
                # No/invalid persona pre-routing: leave unset, deps.py
                # re-resolves post-routing and raises the proper 400/401.
                persona = None
            token = _persona_var.set(persona)
            try:
                await self.app(scope, receive, send)
            finally:
                _persona_var.reset(token)
        else:
            await self.app(scope, receive, send)


class PersonaRequiredError(Exception):
    """Raised when a persona is required but none is configured."""

    pass
