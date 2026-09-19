"""Unit tests for recency-decay helpers re-exported via PrepareStep.

複合スコア（recency + importance + relevance + reflection penalty）の検証は
engine 側 RankPolicy に移設: ``tests/unit/test_search_rank_policy.py`` の
``TestCompositeScoreFormulaEngine`` を参照。
"""

from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta

# ---------------------------------------------------------------------------
# Import the helpers directly (no server / embedding model needed)
# emotion_decay は time_utils への re-export になったが、prepare 経由の
# 既存 import はそのまま動作する（TestComputeRecencyDecay 存続）。
# ---------------------------------------------------------------------------
from nous.application.chat.pipeline.prepare import (
    _RECENCY_LAMBDA,
    _compute_recency_decay,
)


class TestComputeRecencyDecay:
    """Tests for _compute_recency_decay()."""

    def test_zero_days_returns_one(self):
        """A memory created just now should have recency ≈ 1.0."""
        now = datetime.now(tz=UTC)
        result = _compute_recency_decay(now)
        assert abs(result - 1.0) < 0.01

    def test_one_day_returns_about_0606(self):
        """After 1 day: exp(-0.5 * 1) ≈ 0.6065."""
        one_day_ago = datetime.now(tz=UTC) - timedelta(days=1)
        result = _compute_recency_decay(one_day_ago)
        expected = math.exp(-_RECENCY_LAMBDA * 1.0)
        assert abs(result - expected) < 0.01

    def test_ten_days_returns_very_small(self):
        """After 10 days: exp(-0.5 * 10) ≈ 0.0067."""
        ten_days_ago = datetime.now(tz=UTC) - timedelta(days=10)
        result = _compute_recency_decay(ten_days_ago)
        expected = math.exp(-_RECENCY_LAMBDA * 10.0)
        assert abs(result - expected) < 0.001
        assert result < 0.02

    def test_none_created_at_returns_fallback(self):
        """None input returns a safe fallback value of 0.5."""
        result = _compute_recency_decay(None)
        assert result == 0.5

    def test_naive_datetime_treated_as_utc(self):
        """Naive datetimes (no tzinfo) should be handled without raising."""
        naive_now = datetime.utcnow()
        result = _compute_recency_decay(naive_now)
        # Should be close to 1.0 since it's "now"
        assert result > 0.9

    def test_monotonic_decrease(self):
        """Recency should strictly decrease as age increases."""
        now = datetime.now(tz=UTC)
        scores = [_compute_recency_decay(now - timedelta(days=d)) for d in [0, 1, 3, 7, 14]]
        for i in range(len(scores) - 1):
            assert scores[i] > scores[i + 1]
