"""Language-agnostic reflection schema for Park et al. 2023 reflection pipeline."""

from dataclasses import dataclass


@dataclass(frozen=True)
class ReflectionQuestion:
    id: str
    intent: str  # Language-agnostic intent key
    output_key: str


REFLECTION_SCHEMA = [
    ReflectionQuestion(
        id="patterns",
        intent="identify patterns, trends, or recurring themes across recent episodic memories",
        output_key="insight",
    ),
    ReflectionQuestion(
        id="user_traits",
        intent="identify stable user traits, preferences, or notable changes",
        output_key="insight",
    ),
    ReflectionQuestion(
        id="implications",
        intent="derive implications or predictions for future conversations",
        output_key="insight",
    ),
]

OUTPUT_FORMAT = {
    "type": "json_array",
    "items": {
        "insight": "string (the synthesized insight in persona's natural language)",
        "evidence_keys": "array of memory keys that support this insight",
        "confidence": "float 0.0-1.0",
    },
}
