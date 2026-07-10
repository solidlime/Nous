"""Shared body state extraction utility."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from nous.domain.persona.entities import PersonaState

_METRIC_KEYS = ("fatigue", "warmth", "arousal", "heart_rate", "pain")


def extract_body_metrics(state: PersonaState) -> dict[str, float | None]:
    """Extract numeric body metric values from a PersonaState.

    Returns {fatigue, warmth, arousal, heart_rate, pain} with None for unset values.
    """
    return {k: getattr(state, k, None) for k in _METRIC_KEYS}
