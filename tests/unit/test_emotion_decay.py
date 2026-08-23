"""Tests for emotion decay logic (configurable params)."""

from __future__ import annotations

import pytest

from nous.domain.persona.emotion_decay import compute_emotion_decay


class TestComputeEmotionDecay:
    """compute_emotion_decay の configurable パラメータテスト。"""

    def test_decay_default_params(self) -> None:
        """パラメータ未指定で既存動作と同じデフォルト値を使用する。"""
        emotion, intensity = compute_emotion_decay(intensity=0.8, elapsed_hours=24.0, emotion="joy")
        # 24h経過、half_life=24h, intensity=0.8 → effective_half_life=24*0.8=19.2
        # decay = 0.5^(24/19.2) = 0.5^1.25 ≈ 0.4204
        # new = 0.0 + (0.8 - 0.0) * 0.4204 ≈ 0.3364
        assert emotion == "joy"
        assert intensity == pytest.approx(0.3364, abs=1e-3)

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
        # 1h経過では half_life=24 だと intensity は 0.8→0.7716 で差 ~0.028 < 0.5
        # threshold=0.5 なので変化なし（強度は 0.0 にはならない、decay関数が丸める）
        # compute_exponential_decay の threshold は target との差を見る。
        # target=0.0, new=0.7716, |0.7716-0.0|=0.7716 > 0.5 → return round(value, 4)=0.7716
        assert emotion == "joy"
        assert intensity == pytest.approx(0.7716, abs=1e-3)

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
