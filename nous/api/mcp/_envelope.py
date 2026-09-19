"""Common tool-result envelope — audit C1 (single contract across surfaces).

Every MCP tool returns a JSON envelope string::

    {"ok": true,  "data": <payload>, "error": null}
    {"ok": false, "data": null, "error": {"code": <str>, "message": <str>}}

Error codes are a closed, machine-readable enumeration so callers can branch
on ``error.code`` instead of parsing prose. The legacy plain-text contract
(``"Error: ..."`` / ``str(dict)``) is retired on the MCP surface; the wrapper
in ``tools.py`` converts legacy results so no plain text escapes unwrapped.
"""

from __future__ import annotations

import json
from enum import StrEnum
from typing import Any


class ToolErrorCode(StrEnum):
    """Machine-readable error codes (audit C1)."""

    NOT_FOUND = "NOT_FOUND"
    VALIDATION_ERROR = "VALIDATION_ERROR"
    DUPLICATE = "DUPLICATE"
    AMBIGUOUS_MATCH = "AMBIGUOUS_MATCH"
    CONFLICT = "CONFLICT"
    INTERNAL = "INTERNAL"


def tool_ok(data: Any, **meta: Any) -> str:
    """Success envelope; extra kwargs are merged into the top level."""
    payload: dict[str, Any] = {"ok": True, "data": data, "error": None}
    payload.update(meta)
    return json.dumps(payload, ensure_ascii=False, default=str)


def tool_error(code: ToolErrorCode | str, message: str, **meta: Any) -> str:
    """Failure envelope with a machine-readable code."""
    payload: dict[str, Any] = {
        "ok": False,
        "data": None,
        "error": {"code": str(code), "message": message},
    }
    payload.update(meta)
    return json.dumps(payload, ensure_ascii=False, default=str)


def parse_envelope(text: Any) -> dict[str, Any] | None:
    """Return the envelope dict if *text* is a JSON envelope, else None."""
    if isinstance(text, dict):
        return text if ("ok" in text and "error" in text) else None
    if isinstance(text, str):
        try:
            payload = json.loads(text)
        except ValueError:
            return None
        if isinstance(payload, dict) and "ok" in payload and "error" in payload:
            return payload
    return None
