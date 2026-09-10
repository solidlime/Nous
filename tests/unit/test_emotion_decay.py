"""Tests for emotion decay logic (configurable params)."""

from __future__ import annotations

import pytest

from nous.domain.persona.emotion_decay import compute_emotion_decay, resolve_half_life


class TestComputeEmotionDecay:
    """compute_emotion_decay の configurable パラメータテスト。"""

    def test_decay_default_params(self) -> None:
        """half_life 未指定はカテゴリテーブル（joy → short 14.4h）。"""
        emotion, intensity = compute_emotion_decay(intensity=0.8, elapsed_hours=24.0, emotion="joy")
        # 24h経過、half_life=14.4h (short), intensity=0.8 → effective_half_life=14.4*0.8=11.52
        # decay = 0.5^(24/11.52) = 0.5^2.0833 ≈ 0.2359
        # new = 0.0 + (0.8 - 0.0) * 0.2359 ≈ 0.1887
        assert emotion == "joy"
        assert intensity == pytest.approx(0.1887, abs=1e-3)

    def test_decay_with_custom_half_life(self) -> None:
        """half_life=12h で標準より早く減衰することを確認。"""
        _, intensity_24 = compute_emotion_decay(intensity=0.8, elapsed_hours=24.0, emotion="joy")
        _, intensity_12 = compute_emotion_decay(intensity=0.8, elapsed_hours=24.0, emotion="joy", half_life_hours=12.0)
        assert intensity_12 < intensity_24, f"Shorter half_life should decay faster: {intensity_12} < {intensity_24}"
        # effective_half_life = 12 * 0.8 = 9.6
        # decay = 0.5^(24/9.6) = 0.5^2.5 ≈ 0.1768
        # new = 0.8 * 0.1768 ≈ 0.1414
        assert intensity_12 == pytest.approx(0.1414, abs=1e-3)

    def test_decay_with_custom_threshold(self) -> None:
        """threshold を大きくすると、減衰変化が小さい場合に早期に変化なしと判定。"""
        emotion, intensity = compute_emotion_decay(intensity=0.8, elapsed_hours=1.0, emotion="joy", threshold=0.5)
        # 1h経過では half_life=14.4 (joy: short) だと intensity は 0.8→0.7533 で差 ~0.047 < 0.5
        # threshold=0.5 なので変化なし（強度は 0.0 にはならない、decay関数が丸める）
        # compute_exponential_decay の threshold は target との差を見る。
        # target=0.0, new=0.7533, |0.7533-0.0|=0.7533 > 0.5 → return round(value, 4)=0.7533
        assert emotion == "joy"
        assert intensity == pytest.approx(0.7533, abs=1e-3)

    def test_decay_with_neutral_threshold(self) -> None:
        """neutral_threshold 未満の強度は neutral になる。"""
        emotion, intensity = compute_emotion_decay(
            intensity=0.05,
            elapsed_hours=48.0,
            emotion="joy",
            half_life_hours=6.0,
            neutral_threshold=0.1,
        )
        # 48h / effective_half_life(6*0.3=1.8) = 26.67 half-lifes → ほぼ0
        assert emotion == "neutral"
        assert intensity == 0.0

    def test_zero_elapsed_returns_emotion_zero(self) -> None:
        """elapsed_hours <= 0 の場合、(emotion, 0.0) を返す。"""
        emotion, intensity = compute_emotion_decay(intensity=0.8, elapsed_hours=0.0, emotion="joy")
        assert emotion == "joy"
        assert intensity == 0.0

        emotion, intensity = compute_emotion_decay(intensity=0.8, elapsed_hours=-1.0, emotion="joy")
        assert emotion == "joy"
        assert intensity == 0.0

    def test_zero_intensity_returns_emotion_zero(self) -> None:
        """intensity <= 0.0 の場合、(emotion, 0.0) を返す。"""
        emotion, intensity = compute_emotion_decay(intensity=0.0, elapsed_hours=24.0, emotion="joy")
        assert emotion == "joy"
        assert intensity == 0.0

    def test_custom_params_via_kwargs(self) -> None:
        """全パラメータを明示指定できる。"""
        emotion, intensity = compute_emotion_decay(
            emotion="anger",
            intensity=0.9,
            elapsed_hours=12.0,
            half_life_hours=6.0,
            threshold=0.001,
            neutral_threshold=0.05,
        )
        # effective_half_life = 6 * max(0.3, 0.9) = 5.4
        # decay = 0.5^(12/5.4) = 0.5^2.222 ≈ 0.214
        # new = 0.0 + 0.9 * 0.214 = 0.1926
        # 0.1926 > neutral_threshold(0.05) → emotion stays
        assert emotion == "anger"
        assert intensity == pytest.approx(0.1926, abs=1e-3)

    @pytest.mark.parametrize(
        ("emotion", "label"),
        [
            ("joy", "joy"),
            ("sadness", "sadness"),
            ("anger", "anger"),
            ("fear", "fear"),
            ("disgust", "disgust"),
            ("surprise", "surprise"),
            ("love", "love"),
            ("trust", "trust"),
            ("anxiety", "anxiety"),
            ("curiosity", "curiosity"),
            ("neutral", "neutral"),
        ],
    )
    def test_emotion_labels_preserved_through_decay(self, emotion: str, label: str) -> None:
        """感情ラベルが減衰後も維持される（neutral に落ちなければ）。"""
        e, i = compute_emotion_decay(
            intensity=0.6,
            elapsed_hours=4.0,
            emotion=emotion,
        )
        assert e == label, f"Emotion '{emotion}' changed to '{e}'"
        assert i > 0.0


class TestResolveHalfLife:
    def test_each_category(self) -> None:
        assert resolve_half_life("fear", None) == 9.6  # brief
        assert resolve_half_life("relief", None) == 9.6  # brief
        assert resolve_half_life("joy", None) == 14.4  # short
        assert resolve_half_life("anger", None) == 14.4  # short
        assert resolve_half_life("contentment", None) == 24.0  # medium
        assert resolve_half_life("love", None) == 24.0  # medium
        assert resolve_half_life("sadness", None) == 48.0  # long
        assert resolve_half_life("loneliness", None) == 48.0  # long

    def test_neutral_and_unknown_fall_back_to_24(self) -> None:
        assert resolve_half_life("neutral", None) == 24.0
        assert resolve_half_life("unknown_emotion", None) == 24.0

    def test_knob_overrides_category(self) -> None:
        assert resolve_half_life("fear", 24.0) == 24.0
        assert resolve_half_life("sadness", 12.0) == 12.0
        assert resolve_half_life("neutral", 36.0) == 36.0


class TestBehaviorChange:
    def test_fear_decays_faster_than_before(self) -> None:
        """fear: 24h→9.6h で実効半減期が短くなる。"""
        _, intensity = compute_emotion_decay(intensity=0.8, elapsed_hours=24.0, emotion="fear")
        # effective_half_life = 9.6*0.8 = 7.68 → decay = 0.5^(24/7.68) = 0.5^3.125 ≈ 0.1146
        assert intensity == pytest.approx(0.0917, abs=1e-3)

    def test_sadness_decays_slower_than_before(self) -> None:
        """sadness: 24h→48h で実効半減期が長くなる。"""
        _, intensity = compute_emotion_decay(intensity=0.8, elapsed_hours=24.0, emotion="sadness")
        # effective_half_life = 48*0.8 = 38.4 → decay = 0.5^(24/38.4) ≈ 0.6484
        assert intensity == pytest.approx(0.5187, abs=1e-3)

    def test_apply_if_needed_passes_none_through_to_table(self) -> None:
        """apply_emotion_decay_if_needed は None を compute に素通ししカテゴリテーブルが効く。"""
        _, fear = compute_emotion_decay(intensity=0.8, elapsed_hours=24.0, emotion="fear")
        _, sadness = compute_emotion_decay(intensity=0.8, elapsed_hours=24.0, emotion="sadness")
        assert fear < 0.15
        assert sadness > 0.45
        assert fear < sadness
