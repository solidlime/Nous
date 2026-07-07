"""Language-agnostic memory recall metadata annotator."""
from dataclasses import dataclass
from typing import Literal, cast

Certainty = Literal["confident", "tentative", "vague", "forgotten"]
TimeHint = Literal["recent", "days_7", "days_30", "days_90", "years"]
SourceHint = Literal["user_stated", "llm_inferred", "reflected", "consolidated", "tool_output"]
KindHint = Literal["episodic", "semantic", "procedural", "prospective"]


@dataclass(frozen=True)
class RecallAnnotation:
    """Language/persona-agnostic memory recall metadata.
    LLM uses these hints to generate natural recall expressions in its persona's voice."""

    certainty: Certainty
    time_hint: TimeHint
    source_hint: SourceHint
    kind_hint: KindHint
    should_mention: bool


class RecallAnnotator:
    CERTAINTY_THRESHOLDS = [
        (0.8, "confident"),
        (0.5, "tentative"),
        (0.2, "vague"),
        (float("-inf"), "forgotten"),
    ]
    TIME_BUCKETS = [
        (1, "recent"),
        (7, "days_7"),
        (30, "days_30"),
        (90, "days_90"),
        (float("inf"), "years"),
    ]

    def annotate(
        self,
        confidence: float,
        age_days: float,
        source_type: str = "user_stated",
        kind: str = "semantic",
    ) -> RecallAnnotation:
        return RecallAnnotation(
            certainty=self._compute_certainty(confidence, age_days),
            time_hint=self._compute_time_hint(age_days),
            source_hint=self._normalize_source(source_type),
            kind_hint=self._normalize_kind(kind),
            should_mention=self._should_mention(confidence, age_days),
        )

    def _compute_certainty(self, confidence: float, age_days: float) -> Certainty:
        effective = confidence - (0.1 if age_days > 90 else 0.0)
        for threshold, label in self.CERTAINTY_THRESHOLDS:
            if effective >= threshold:
                return cast("Certainty", label)
        return "forgotten"

    def _compute_time_hint(self, age_days: float) -> TimeHint:
        for boundary, label in self.TIME_BUCKETS:
            if age_days < boundary:
                return cast("TimeHint", label)
        return "years"

    def _normalize_source(self, raw: str) -> SourceHint:
        valid = {"user_stated", "user_implied", "llm_inferred", "tool_output", "consolidated", "reflected"}
        return cast("SourceHint", raw if raw in valid else "user_stated")

    def _normalize_kind(self, raw: str) -> KindHint:
        valid = {"episodic", "semantic", "procedural", "prospective"}
        return cast("KindHint", raw if raw in valid else "semantic")

    def _should_mention(self, confidence: float, age_days: float) -> bool:
        return self._compute_certainty(confidence, age_days) != "forgotten"
