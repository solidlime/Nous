from __future__ import annotations

import json

from nous.domain.shared.time_utils import parse_iso


def _parse_or_none(value: str | None):
    """Parse ISO datetime or return None."""
    if not value:
        return None
    try:
        return parse_iso(value)
    except Exception:
        return None


def _parse_json_list(value: str | None) -> list[str]:
    """Safely parse a JSON-encoded list from a database field."""
    if not value:
        return []
    try:
        parsed = json.loads(value)
        return parsed if isinstance(parsed, list) else []
    except (json.JSONDecodeError, TypeError):
        return []
