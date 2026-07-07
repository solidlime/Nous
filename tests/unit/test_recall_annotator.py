"""Tests for RecallAnnotator — language-agnostic memory recall metadata annotator."""

from nous.domain.memory.recall_annotator import RecallAnnotator


class TestRecallAnnotator:
    def setup_method(self) -> None:
        self.annotator = RecallAnnotator()

    def test_confident_fresh_memory(self) -> None:
        """High confidence + fresh → confident, recent, should_mention=True."""
        ann = self.annotator.annotate(confidence=0.95, age_days=0.1)
        assert ann.certainty == "confident"
        assert ann.time_hint == "recent"
        assert ann.should_mention is True

    def test_tentative_aged_memory(self) -> None:
        """Moderate confidence + aged → tentative."""
        ann = self.annotator.annotate(confidence=0.65, age_days=5.0)
        assert ann.certainty == "tentative"
        assert ann.should_mention is True

    def test_vague_low_confidence(self) -> None:
        """Low confidence → vague."""
        ann = self.annotator.annotate(confidence=0.35, age_days=2.0)
        assert ann.certainty == "vague"
        assert ann.should_mention is True

    def test_forgotten_very_low_confidence(self) -> None:
        """Very low confidence → forgotten, should_mention=False."""
        ann = self.annotator.annotate(confidence=0.1, age_days=1.0)
        assert ann.certainty == "forgotten"
        assert ann.should_mention is False

    def test_time_buckets(self) -> None:
        """Time buckets map correctly."""
        # recent: < 1 day
        ann = self.annotator.annotate(0.9, 0.5)
        assert ann.time_hint == "recent"

        # days_7: 1-7 days
        ann = self.annotator.annotate(0.9, 3.0)
        assert ann.time_hint == "days_7"

        # days_30: 7-30 days
        ann = self.annotator.annotate(0.9, 14.0)
        assert ann.time_hint == "days_30"

        # days_90: 30-90 days
        ann = self.annotator.annotate(0.9, 60.0)
        assert ann.time_hint == "days_90"

        # years: >= 90 days
        ann = self.annotator.annotate(0.9, 365.0)
        assert ann.time_hint == "years"

    def test_old_memory_drops_one_level(self) -> None:
        """Memory older than 90 days gets -0.1 certainty penalty."""
        # 0.85 confidence + 100 days → effective = 0.75 → tentative (not confident)
        ann = self.annotator.annotate(confidence=0.85, age_days=100.0)
        assert ann.certainty == "tentative"

        # But 0.95 confidence + 100 days → effective = 0.85 → still confident
        ann = self.annotator.annotate(confidence=0.95, age_days=100.0)
        assert ann.certainty == "confident"

    def test_invalid_source_defaults(self) -> None:
        """Invalid source_type defaults to 'user_stated'."""
        ann = self.annotator.annotate(0.9, 1.0, source_type="garbage")
        assert ann.source_hint == "user_stated"

    def test_valid_source_passthrough(self) -> None:
        """Valid source_type passes through."""
        ann = self.annotator.annotate(0.9, 1.0, source_type="reflected")
        assert ann.source_hint == "reflected"

        ann = self.annotator.annotate(0.9, 1.0, source_type="llm_inferred")
        assert ann.source_hint == "llm_inferred"

    def test_valid_kind_passthrough(self) -> None:
        """Valid kind passes through."""
        ann = self.annotator.annotate(0.9, 1.0, kind="episodic")
        assert ann.kind_hint == "episodic"

        ann = self.annotator.annotate(0.9, 1.0, kind="procedural")
        assert ann.kind_hint == "procedural"

    def test_invalid_kind_defaults(self) -> None:
        """Invalid kind defaults to 'semantic'."""
        ann = self.annotator.annotate(0.9, 1.0, kind="invalid_kind")
        assert ann.kind_hint == "semantic"

    def test_recall_annotation_is_frozen(self) -> None:
        """RecallAnnotation dataclass is frozen (immutable)."""
        import pytest

        ann = self.annotator.annotate(0.9, 1.0)
        with pytest.raises(AttributeError):
            ann.certainty = "vague"  # type: ignore[misc]
