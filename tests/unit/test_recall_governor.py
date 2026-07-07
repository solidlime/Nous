"""Tests for RecallGovernor — language-agnostic spontaneous recall frequency limiter."""

from nous.domain.memory.recall_governor import RecallGovernor


class TestRecallGovernor:
    def setup_method(self) -> None:
        self.gov = RecallGovernor()

    def test_allows_first_recall(self) -> None:
        """First recall is always allowed (assistant turn)."""
        assert self.gov.may_recall(current_turn=0, is_user_speaking=False) is True

    def test_blocks_consecutive_recalls(self) -> None:
        """Consecutive recalls within MIN_TURN_GAP are blocked."""
        self.gov.record_recall(turn=0)
        # Same turn — blocked
        assert self.gov.may_recall(current_turn=0, is_user_speaking=False) is False
        # Next turn — blocked (gap < 2)
        assert self.gov.may_recall(current_turn=1, is_user_speaking=False) is False

    def test_allows_after_gap(self) -> None:
        """Recall is allowed after MIN_TURN_GAP turns."""
        self.gov.record_recall(turn=0)
        assert self.gov.may_recall(current_turn=0, is_user_speaking=False) is False
        assert self.gov.may_recall(current_turn=1, is_user_speaking=False) is False
        # Turn 2: gap = 2 ≥ MIN_TURN_GAP → allowed
        assert self.gov.may_recall(current_turn=2, is_user_speaking=False) is True

    def test_blocks_when_user_speaking(self) -> None:
        """User turns never trigger spontaneous recall."""
        assert self.gov.may_recall(current_turn=0, is_user_speaking=True) is False

    def test_respects_max_limit(self) -> None:
        """MAX_SPONTANEOUS (3) is respected."""
        for i in range(3):
            turn = i * 3  # ensure gap is sufficient
            assert self.gov.may_recall(current_turn=turn, is_user_speaking=False) is True
            self.gov.record_recall(turn=turn)

        # 4th recall — blocked
        assert self.gov.may_recall(current_turn=9, is_user_speaking=False) is False

    def test_reset_clears_state(self) -> None:
        """Reset() clears count and last_turn."""
        self.gov.record_recall(turn=0)
        self.gov.record_recall(turn=3)
        self.gov.record_recall(turn=6)
        assert self.gov.may_recall(current_turn=9, is_user_speaking=False) is False

        self.gov.reset()
        assert self.gov.may_recall(current_turn=0, is_user_speaking=False) is True

    def test_initial_state(self) -> None:
        """Fresh governor has count=0 and last_turn=-MIN_TURN_GAP."""
        assert self.gov._count == 0
        assert self.gov._last_turn == -self.gov.MIN_TURN_GAP
