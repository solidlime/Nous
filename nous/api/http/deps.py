from __future__ import annotations

from dataclasses import asdict
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

from nous.api.mcp.middleware import _PERSONA_PATTERN, resolve_persona_from_headers  # noqa: F401
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
    speech_style: str | None = None


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


def _resolve_persona_from_request(request: Request, *, default: str | None = None) -> str:
    """Resolve persona from path params, HTTP headers, or environment.

    Priority: path parameter > Bearer token > X-Persona header > *default* > env var.
    """
    persona = request.path_params.get("persona")
    if persona:
        return persona

    return resolve_persona_from_headers(
        authorization=request.headers.get("authorization"),
        x_persona=request.headers.get("x-persona"),
        default=default,
    )
