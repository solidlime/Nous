from __future__ import annotations

from dataclasses import asdict
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field
from starlette.exceptions import HTTPException

from nous.api.mcp.middleware import (
    _PERSONA_PATTERN,  # noqa: F401  (re-exported for routers)
    PersonaAuthError,
    PersonaRequiredError,
    _valid_persona,
    bearer_from_query,
    resolve_persona,
    resolve_persona_from_headers,  # noqa: F401  (backward-compat re-export)
)
from nous.application.use_cases import AppContextRegistry
from nous.infrastructure.logging.structured import get_logger

if TYPE_CHECKING:
    from starlette.requests import Request

logger = get_logger(__name__)


class CreateMemoryRequest(BaseModel):
    model_config = {"populate_by_name": True}
    content: str
    importance: float = 0.5
    emotion: str = Field(default="neutral", alias="emotion_type")
    emotion_intensity: float = 0.0
    tags: list[str] | None = None
    privacy_level: str = "internal"
    source_context: str | None = None
    defer_vector: bool = False


class UpdateMemoryRequest(BaseModel):
    model_config = {"populate_by_name": True}
    content: str | None = None
    importance: float | None = None
    emotion: str | None = Field(default=None, alias="emotion_type")
    emotion_intensity: float | None = None
    tags: list[str] | None = None
    privacy_level: str | None = None


class UpdateContextRequest(BaseModel):
    emotion: str | None = None
    emotion_intensity: float | None = None
    physical_state: str | None = None
    mental_state: str | None = None
    environment: str | None = None
    relationship_status: str | None = None
    user_info: dict | None = None
    persona_info: dict | None = None
    fatigue: float | None = None
    warmth: float | None = None
    arousal: float | None = None


def _safe_get_context(persona: str):
    """Get AppContext for persona, returning None if init fails."""
    try:
        return AppContextRegistry.get(persona)
    except Exception as exc:
        logger.warning("Failed to get context for persona '%s': %s", persona, exc)
        return None


def _memory_to_dict(m) -> dict:
    """Convert a Memory dataclass to a JSON-safe dict."""
    d = asdict(m)
    for k in (
        "created_at",
        "updated_at",
        "last_accessed",
        "last_decay",
        "last_recall",
        "state_snapped_at",
        "last_consumed_at",
        "valid_from",
        "valid_until",
    ):
        if k in d and d[k] is not None:
            d[k] = d[k].isoformat()
    return d


def _strength_to_dict(s) -> dict:
    """Convert a MemoryStrength dataclass to a JSON-safe dict."""
    d = asdict(s)
    for k in ("last_decay", "last_recall", "last_utility"):
        if k in d and d[k] is not None:
            d[k] = d[k].isoformat()
    return d


def _resolve_persona_from_request(request: Request, *, default: str | None = None, api_key: str | None = None) -> str:
    """Resolve persona from path params, HTTP headers, query params, or environment.

    Priority: path parameter > Bearer token > X-Persona header > ``?persona=``
    query param > *default* > env var. Fully delegates to
    :func:`nous.api.mcp.middleware.resolve_persona`.

    SSE (EventSource) cannot send headers, so two query-param channels exist:

    - ``?persona=<name>``: lowest-priority persona source (pattern-validated).
      Used by the dashboard's ``/api/memory/wiring/stream?persona=...``.
    - ``?token=<api_key>``: Bearer-equivalent credential, honored only when no
      ``Authorization`` header is present (see
      :func:`nous.api.mcp.middleware.bearer_from_query`).

    Raises:
        HTTPException(401): API-key mismatch (strict mode) or no persona found.
        HTTPException(400): invalid ``persona`` path parameter.
    """
    query_params = request.query_params
    authorization = request.headers.get("authorization")
    if not authorization:
        query_token = bearer_from_query(str(query_params))
        if query_token:
            authorization = f"Bearer {query_token}"
    path_param = request.path_params.get("persona")
    if path_param is None:
        query_persona = _valid_persona(query_params.get("persona"))
        if query_persona is not None:
            default = default or query_persona
    try:
        return resolve_persona(
            path_param,
            authorization,
            request.headers.get("x-persona"),
            default=default,
            api_key=api_key,
        )
    except PersonaAuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc) or "Invalid API key") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except PersonaRequiredError as exc:
        raise HTTPException(status_code=401, detail=str(exc) or "Persona required") from exc
