"""Tests for importance labels and critical goal protection."""

from nous.domain.value_objects import importance_to_label


class TestImportanceToLabel:
    """Boundary tests for importance_to_label conversion."""

    def test_critical_at_1_0(self):
        """importance=1.0 → critical."""
        assert importance_to_label(1.0) == "critical"

    def test_critical_at_0_9(self):
        """importance=0.9 → critical (lower bound)."""
        assert importance_to_label(0.9) == "critical"

    def test_high_below_critical(self):
        """importance=0.899 → high (just below critical)."""
        assert importance_to_label(0.899) == "high"

    def test_high_at_0_7(self):
        """importance=0.7 → high (lower bound)."""
        assert importance_to_label(0.7) == "high"

    def test_normal_below_high(self):
        """importance=0.699 → normal (just below high)."""
        assert importance_to_label(0.699) == "normal"

    def test_normal_at_0_4(self):
        """importance=0.4 → normal (lower bound)."""
        assert importance_to_label(0.4) == "normal"

    def test_low_below_normal(self):
        """importance=0.399 → low (just below normal)."""
        assert importance_to_label(0.399) == "low"

    def test_low_at_0_0(self):
        """importance=0.0 → low (lower bound)."""
        assert importance_to_label(0.0) == "low"

    def test_low_negative(self):
        """Negative importance → low (clamped elsewhere, but should handle gracefully)."""
        assert importance_to_label(-0.1) == "low"



