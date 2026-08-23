"""Tests for EmotionDrivenSampler domain class."""

from __future__ import annotations

import pytest

from nous.domain.sampling import _EMOTION_MODIFIERS, TEMPERATURE_MAX, TEMPERATURE_MIN, EmotionDrivenSampler
from nous.domain.value_objects import _EMOTION_KEYWORD_MAP


class TestEmotionDrivenSampler:
    """EmotionDrivenSampler.compute の網羅的テスト。"""

    # — baseline: intensity=0.5, scale=0.2, base_temp=0.7 —
    #   effective_modifier = modifier * 0.5 * 0.2 = modifier * 0.1

    @pytest.mark.parametrize(
        ("emotion", "expected"),
        [
            # 小数点2桁に丸められた値（プロバイダが3桁以上の温度を拒否するため）
            ("anger", 0.71),  # raw 0.715 → banker's rounding
            ("sadness", 0.69),
            ("joy", 0.7),  # raw 0.705 → banker's rounding
            ("excitement", 0.72),
            ("neutral", 0.7),
            ("curiosity", 0.7),  # raw 0.705 → banker's rounding
            ("fear", 0.69),  # raw 0.695 → banker's rounding
            ("disgust", 0.69),
            ("surprise", 0.71),
            ("grief", 0.68),  # raw 0.684999... → banker's rounding
            ("love", 0.71),
        ],
    )
    def test_all_emotions_baseline(self, emotion: str, expected: float) -> None:
        result = EmotionDrivenSampler.compute(
            base_temp=0.7,
            emotion=emotion,
            intensity=0.5,
            scale=0.2,
        )
        assert result == pytest.approx(expected, abs=1e-12)

    @pytest.mark.parametrize(
        ("base_temp", "emotion", "intensity", "scale"),
        [
            (base, emotion, intensity, scale)
            for base in (0.3, 0.7, 1.2)
            for emotion in ("anger", "joy", "grief", "love")
            for intensity in (0.3, 0.5, 1.0)
            for scale in (0.2, 0.5, 1.0)
        ],
    )
    def test_result_always_at_most_two_decimals(
        self, base_temp: float, emotion: str, intensity: float, scale: float
    ) -> None:
        """動的温度計算結果は常に小数点2桁以下（float 丸め誤差を含め）。"""
        result = EmotionDrivenSampler.compute(base_temp, emotion, intensity, scale)
        assert result == round(result, 2)

    def test_intensity_zero_returns_base_temp(self) -> None:
        """intensity=0.0 → effective_temp == base_temp."""
        result = EmotionDrivenSampler.compute(
            base_temp=0.7,
            emotion="anger",
            intensity=0.0,
            scale=0.2,
        )
        assert result == 0.7

    def test_intensity_one_max_effect(self) -> None:
        """intensity=1.0 → modifier * 1.0 * scale がそのまま効く."""
        result = EmotionDrivenSampler.compute(
            base_temp=0.7,
            emotion="excitement",
            intensity=1.0,
            scale=0.2,
        )
        # effective_modifier = 0.20 * 1.0 * 0.2 = 0.04
        # effective_temp = 0.7 + 0.04 = 0.74
        assert result == pytest.approx(0.74, abs=1e-12)

    def test_clamp_high(self) -> None:
        """高温側クランプ: 1.8 を超えない."""
        result = EmotionDrivenSampler.compute(
            base_temp=0.7,
            emotion="anger",
            intensity=1.0,
            scale=1.0,
        )
        # effective_modifier = 0.15 * 1.0 * 1.0 = 0.15 → 0.85 (クランプされない)
        # 境界を突破するには base_temp を高くする
        result = EmotionDrivenSampler.compute(
            base_temp=1.7,
            emotion="excitement",
            intensity=1.0,
            scale=1.0,
        )
        # effective_modifier = 0.20 * 1.0 * 1.0 = 0.20 → 1.90 → clamp to 1.8
        assert result == pytest.approx(TEMPERATURE_MAX, abs=1e-12)

    def test_clamp_low(self) -> None:
        """低温側クランプ: 0.1 を下回らない."""
        result = EmotionDrivenSampler.compute(
            base_temp=0.1,
            emotion="grief",
            intensity=1.0,
            scale=1.0,
        )
        # effective_modifier = -0.15 * 1.0 * 1.0 = -0.15 → -0.05 → clamp to 0.1
        assert result == pytest.approx(TEMPERATURE_MIN, abs=1e-12)

    def test_unknown_emotion_default_modifier(self) -> None:
        """未知の感情は modifier 0.0."""
        result = EmotionDrivenSampler.compute(
            base_temp=0.7,
            emotion="nonexistent",
            intensity=0.5,
            scale=0.2,
        )
        assert result == 0.7

    def test_scale_zero_returns_base_temp(self) -> None:
        """scale=0.0 → 全ての感情で base_temp を返す."""
        for emotion in ("anger", "joy", "sadness", "grief", "unknown"):
            result = EmotionDrivenSampler.compute(
                base_temp=0.7,
                emotion=emotion,
                intensity=0.8,
                scale=0.0,
            )
            assert result == 0.7

    def test_case_insensitivity(self) -> None:
        """感情ラベルは大文字小文字を区別しない."""
        result_lower = EmotionDrivenSampler.compute(
            base_temp=0.7,
            emotion="anger",
            intensity=0.5,
            scale=0.2,
        )
        result_upper = EmotionDrivenSampler.compute(
            base_temp=0.7,
            emotion="ANGER",
            intensity=0.5,
            scale=0.2,
        )
        result_mixed = EmotionDrivenSampler.compute(
            base_temp=0.7,
            emotion="AnGer",
            intensity=0.5,
            scale=0.2,
        )
        assert result_lower == result_upper == result_mixed

    def test_stateless_pure_function(self) -> None:
        """同じ入力 → 同じ出力 (純粋関数性の確認)."""
        a = EmotionDrivenSampler.compute(0.7, "surprise", 0.3, 0.2)
        b = EmotionDrivenSampler.compute(0.7, "surprise", 0.3, 0.2)
        assert a == b

    def test_all_emotions_have_modifier(self) -> None:
        """_EMOTION_KEYWORD_MAP の全キーが _EMOTION_MODIFIERS に存在する。"""
        missing = [e for e in _EMOTION_KEYWORD_MAP if e not in _EMOTION_MODIFIERS]
        assert not missing, f"Missing modifiers for: {missing}"
        # Compute returns valid temperature for all emotions
        for emotion in _EMOTION_KEYWORD_MAP:
            temp = EmotionDrivenSampler.compute(0.7, emotion, 0.5, 0.2)
            assert TEMPERATURE_MIN <= temp <= TEMPERATURE_MAX, f"Temperature {temp} out of range for {emotion}"
