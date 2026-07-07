"""Language-agnostic spontaneous recall frequency limiter."""


class RecallGovernor:
    """Limits spontaneous memory recall frequency to avoid repetitive LLM output.

    Tracked per conversation session.
    """

    MAX_SPONTANEOUS = 3
    MIN_TURN_GAP = 2

    def __init__(self) -> None:
        self._count = 0
        self._last_turn = -self.MIN_TURN_GAP

    def may_recall(self, current_turn: int, is_user_speaking: bool) -> bool:
        """Check whether spontaneous recall is allowed at this turn."""
        if self._count >= self.MAX_SPONTANEOUS:
            return False
        if current_turn - self._last_turn < self.MIN_TURN_GAP:
            return False
        return not is_user_speaking

    def record_recall(self, turn: int) -> None:
        """Record a recall event at the given turn number."""
        self._count += 1
        self._last_turn = turn

    def reset(self) -> None:
        """Reset all state (e.g. on session start)."""
        self._count = 0
        self._last_turn = -self.MIN_TURN_GAP
