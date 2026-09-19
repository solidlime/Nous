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
        """valence=0.8 → score > valence=0.0（他条件同一・audit H5: salience は valence 経由）."""
        now = datetime(2026, 6, 29, 12, 0, 0)
        base = MemoryStrength(
            memory_key="a",
            link_count=0,
            valence=0.0,
            recall_count=5,
            last_recall=now,
        )
        boosted = MemoryStrength(
            memory_key="b",
            link_count=0,
            valence=0.8,
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
    """audit H5 (v4.0): 感情は永続 stability を変えない。

    旧仕様（gain = min(1 + gain_k * intensity, 1.5) による stability 増幅）は
    削除済み。感情は valence（ランキング時 salience）にのみ効く。
    """

    def test_emotion_does_not_change_stability(self):
        """いかなる感情強度でも stability は不変（H5 の核心契約）。"""
        full = MemoryStrength(memory_key="full", stability=2.0)
        full.boost_on_recall(emotion_intensity=1.0)
        assert full.stability == pytest.approx(2.0)

        mid = MemoryStrength(memory_key="mid", stability=2.0)
        mid.boost_on_recall(emotion_intensity=0.5)
        assert mid.stability == pytest.approx(2.0)

        neutral = MemoryStrength(memory_key="neutral", stability=2.0)
        neutral.boost_on_recall(emotion_intensity=0.0)
        assert neutral.stability == pytest.approx(2.0)

        legacy = MemoryStrength(memory_key="legacy", stability=2.0)
        legacy.boost_on_recall()
        assert legacy.stability == pytest.approx(2.0)

    def test_recall_metadata_still_updated(self):
        """recall_count / strength / last_recall は従来どおり更新される。"""
        s = MemoryStrength(memory_key="s", stability=2.0)
        s.boost_on_recall(emotion_intensity=0.8)
        assert s.recall_count == 1
        assert s.strength == 1.0
        assert s.last_recall is not None
        assert s.valence == 0.0  # valence は query_service 側で記録される

    def test_valence_feeds_score_not_stability(self):
        """valence（想起時の感情強度）はスコアの salience 因子にのみ効く。"""
        base = MemoryStrength(memory_key="a")
        base.valence = 0.0
        plain = base.compute_strength_score(importance=0.5)
        emo = MemoryStrength(memory_key="b")
        emo.valence = 1.0
        boosted = emo.compute_strength_score(importance=0.5)
        assert boosted > plain
        # cap: max +0.10
        assert boosted - plain <= 0.10 + 1e-9
