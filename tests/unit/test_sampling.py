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
            ("anger", 0.7 + 0.15 * 0.1),  # 0.715
            ("sadness", 0.7 + (-0.10) * 0.1),  # 0.690
            ("joy", 0.7 + 0.05 * 0.1),  # 0.705
            ("excitement", 0.7 + 0.20 * 0.1),  # 0.720
            ("neutral", 0.7 + 0.0 * 0.1),  # 0.700
            ("curiosity", 0.7 + 0.05 * 0.1),  # 0.705
            ("fear", 0.7 + (-0.05) * 0.1),  # 0.695
            ("disgust", 0.7 + (-0.08) * 0.1),  # 0.692
            ("surprise", 0.7 + 0.10 * 0.1),  # 0.710
            ("grief", 0.7 + (-0.15) * 0.1),  # 0.685
            ("love", 0.7 + 0.08 * 0.1),  # 0.708
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
