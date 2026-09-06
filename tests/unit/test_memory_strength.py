"""FSRS v6 power-law compute_recall() tests."""

import math
from datetime import datetime

import pytest

from nous.domain.memory.entities import MemoryStrength


class TestFSRSRecall:
    """FSRS v6 power-law compute_recall() unit tests."""

    def test_fresh_memory_r_approx_one(self):
        """t=0 → R ≈ 1.0 (brand new memory)."""
        ms = MemoryStrength(memory_key="test", stability=1.0)
        assert ms.compute_recall(0.0) == pytest.approx(1.0, abs=1e-6)

    def test_one_stability_period_r_approx_0_224(self):
        """t = stability*24h, S=1 → R ≈ 0.224 (canonical FSRS)."""
        ms = MemoryStrength(memory_key="test", stability=1.0)
        r = ms.compute_recall(24.0)  # 1 day = 1 stability period
        expected = 20 ** (-0.5)
        assert r == pytest.approx(expected, abs=1e-6)

    def test_ten_periods_significant_decay(self):
        """t = 10*stability*24h → R < 0.1."""
        ms = MemoryStrength(memory_key="test", stability=1.0)
        r = ms.compute_recall(10 * 24.0)
        assert r < 0.1

    def test_zero_stability_returns_zero(self):
        """stability=0 → R = 0.0."""
        ms = MemoryStrength(memory_key="test", stability=0.0)
        assert ms.compute_recall(24.0) == 0.0

        ms2 = MemoryStrength(memory_key="test", stability=-1.0)
        assert ms2.compute_recall(24.0) == 0.0

    def test_exponent_one_steeper_decay(self):
        """decay_exponent=1.0 → steeper decay than 0.5."""
        ms = MemoryStrength(memory_key="test", stability=1.0)
        r_default = ms.compute_recall(24.0)  # exponent=0.5
        r_steeper = ms.compute_recall(24.0, decay_exponent=1.0)
        assert r_steeper < r_default

    def test_exponent_two_even_steeper(self):
        """decay_exponent=2.0 → even steeper."""
        ms = MemoryStrength(memory_key="test", stability=1.0)
        r_1 = ms.compute_recall(24.0, decay_exponent=1.0)
        r_2 = ms.compute_recall(24.0, decay_exponent=2.0)
        assert r_2 < r_1

    def test_exponent_small_slower_decay(self):
        """decay_exponent=0.1 → slower decay."""
        ms = MemoryStrength(memory_key="test", stability=1.0)
        r_default = ms.compute_recall(24.0)  # exponent=0.5
        r_slow = ms.compute_recall(24.0, decay_exponent=0.1)
        assert r_slow > r_default

    def test_max_stability_long_term_survival(self):
        """S=365 (max), t=1 year → R > 0.05 (long-term survival)."""
        ms = MemoryStrength(memory_key="test", stability=365.0)
        r = ms.compute_recall(365 * 24.0)  # 1 year
        assert r > 0.05

    def test_crossover_with_ebbinghaus(self):
        """FSRS decays faster at short times but slower at long times (heavier tail)."""
        ms = MemoryStrength(memory_key="test", stability=1.0)

        # Short time (1 min): FSRS < Ebbinghaus (faster initial decay due to factor=19)
        r_fsrs = ms.compute_recall(1.0 / 60.0)  # 1 minute
        r_ebbinghaus = math.exp(-(1.0 / 60.0) / (1.0 * 24))
        assert r_fsrs < r_ebbinghaus, f"FSRS should be lower at 1min: {r_fsrs} vs {r_ebbinghaus}"

        # Long time (100 days): FSRS > Ebbinghaus (power-law tail, Ebbinghaus near-zero)
        r_fsrs = ms.compute_recall(100 * 24.0)
        r_ebbinghaus = math.exp(-(100 * 24.0) / (1.0 * 24))
        assert r_fsrs > r_ebbinghaus, f"FSRS should be higher at 100 days: {r_fsrs} vs {r_ebbinghaus}"

    def test_elapsed_zero_returns_one(self):
        """elapsed_hours=0 → R ≈ 1.0 (backward compat)."""
        ms = MemoryStrength(memory_key="test", stability=5.0)
        assert ms.compute_recall(0.0) == pytest.approx(1.0, abs=1e-6)


class TestMemoryStrengthLTM:
    """is_ltm flag and LTM-related behaviour."""

    def test_is_ltm_default_false(self):
        """新規 MemoryStrength の is_ltm は False."""
        ms = MemoryStrength(memory_key="test")
        assert ms.is_ltm is False

    def test_is_ltm_uses_slower_decay(self):
        """is_ltm=True → decay_exponent=0.3 でより緩やかな減衰."""
        ms = MemoryStrength(memory_key="test", stability=1.0, is_ltm=True)
        r_fast = ms.compute_recall(24.0, decay_exponent=0.5)
        r_slow = ms.compute_recall(24.0, decay_exponent=0.3)
        assert r_slow > r_fast, f"LTM should decay slower: {r_slow} vs {r_fast}"

    def test_boost_on_recall_preserves_is_ltm(self):
        """boost_on_recall は is_ltm を変更しない."""
        ms = MemoryStrength(memory_key="test", is_ltm=True)
        ms.boost_on_recall()
        assert ms.is_ltm is True

        ms2 = MemoryStrength(memory_key="test", is_ltm=False)
        ms2.boost_on_recall()
        assert ms2.is_ltm is False


class TestChainEmotionBoost:
    """Chain-aware + emotion boost integration tests."""

    def test_chain_boost_increases_score(self):
        """link_count=10 → score > link_count=0（他条件同一）."""
        now = datetime(2026, 6, 29, 12, 0, 0)
        base = MemoryStrength(
            memory_key="a",
            link_count=0,
            recall_count=5,
            last_recall=now,
        )
        boosted = MemoryStrength(
            memory_key="b",
            link_count=10,
            recall_count=5,
            last_recall=now,
        )
        assert boosted.compute_strength_score(now=now) > base.compute_strength_score(now=now)

    def test_emotion_boost_increases_score(self):
        """emotion_peak=0.8 → score > emotion_peak=0.0（他条件同一）."""
        now = datetime(2026, 6, 29, 12, 0, 0)
        base = MemoryStrength(
            memory_key="a",
            link_count=0,
            emotion_peak=0.0,
            recall_count=5,
            last_recall=now,
        )
        boosted = MemoryStrength(
            memory_key="b",
            link_count=0,
            emotion_peak=0.8,
            recall_count=5,
            last_recall=now,
        )
        assert boosted.compute_strength_score(now=now) > base.compute_strength_score(now=now)

    def test_chain_boost_capped(self):
        """link_count=100 でも boost は +0.10 を超えない."""
        now = datetime(2026, 6, 29, 12, 0, 0)
        low = MemoryStrength(
            memory_key="a",
            link_count=0,
            recall_count=5,
            last_recall=now,
        )
        high = MemoryStrength(
            memory_key="b",
            link_count=100,
            recall_count=5,
            last_recall=now,
        )
        diff = high.compute_strength_score(now=now) - low.compute_strength_score(now=now)
        assert diff <= 0.10 + 1e-9

    def test_emotion_boost_capped(self):
        """emotion_peak=1.0 でも boost は +0.10 を超えない."""
        now = datetime(2026, 6, 29, 12, 0, 0)
        low = MemoryStrength(
            memory_key="a",
            link_count=0,
            emotion_peak=0.0,
            recall_count=5,
            last_recall=now,
        )
        high = MemoryStrength(
            memory_key="b",
            link_count=0,
            emotion_peak=1.0,
            recall_count=5,
            last_recall=now,
        )
        diff = high.compute_strength_score(now=now) - low.compute_strength_score(now=now)
        assert diff <= 0.10 + 1e-9

    def test_compute_strength_score_mixed_tz_no_crash(self):
        """aware な last_recall/last_utility と naive な now の混在で例外を出さない（decay worker 経路の回帰）。"""
        from datetime import UTC

        aware = datetime(2026, 6, 29, 12, 0, 0, tzinfo=UTC)
        ms = MemoryStrength(
            memory_key="tz-mix",
            recall_count=5,
            last_recall=aware,
            last_utility=aware,
        )
        # now を渡さない = entities 内で datetime.now()（naive）が使われる経路
        score = ms.compute_strength_score()
        assert 0.0 <= score <= 1.0

        # 両方向: aware な now を明示的に渡しても落ちない
        score2 = ms.compute_strength_score(now=datetime(2026, 6, 30, 12, 0, 0, tzinfo=UTC))
        assert 0.0 <= score2 <= 1.0


class TestEmotionGainCap:
    """感情修飾 recall gain（脳シミュレーション拡張）.

    gain = min(1 + gain_k * emotion_intensity, 1.5)（cap 必須）.
    注: 計画書の「emotion_intensity=0 で従来どおり 1.5 倍上限に一致」は起草時の
    誤記（無引数呼び出しの誤り）と記録済み——無引数（emotion_intensity=None,
    レガシー呼び出し側）は従来どおり 1.5 倍を維持し、明示的な感情強度は式に従う。
    """

    def test_emotion_gain_capped(self):
        """i=1.0 で cap 1.5 に一致、i=0.5 は式どおり、明示 i=0.0 は gain 1.0."""
        full = MemoryStrength(memory_key="full", stability=2.0)
        full.boost_on_recall(emotion_intensity=1.0)
        assert full.stability == pytest.approx(2.0 * 1.5)

        # 単調性: 弱い感情は cap 未満の gain（1 + 0.5 * 0.5 = 1.25）
        mid = MemoryStrength(memory_key="mid", stability=2.0)
        mid.boost_on_recall(emotion_intensity=0.5)
        assert mid.stability == pytest.approx(2.0 * 1.25)
        assert mid.stability < full.stability

        # 明示的な中立（0.0）は式どおり gain 1.0
        neutral = MemoryStrength(memory_key="neutral", stability=2.0)
        neutral.boost_on_recall(emotion_intensity=0.0)
        assert neutral.stability == pytest.approx(2.0 * 1.0)

        # 無引数（レガシー呼び出し）は従来どおり 1.5 倍
        legacy = MemoryStrength(memory_key="legacy", stability=2.0)
        legacy.boost_on_recall()
        assert legacy.stability == pytest.approx(2.0 * 1.5)

        # cap: stability は 365 を超えない
        big = MemoryStrength(memory_key="big", stability=300.0)
        big.boost_on_recall(emotion_intensity=1.0)
        assert big.stability == pytest.approx(min(300.0 * 1.5, 365.0))
