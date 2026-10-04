"""B-3: estimate_tokens 純関数のテスト."""

from __future__ import annotations

import pytest

from nous.domain.profile.tokens import (
    DEFAULT_PROFILE_MAX_TOKENS,
    TOKEN_WEIGHTS,
    estimate_tokens,
)


class TestEstimateTokens:
    def test_empty_string_is_zero(self):
        assert estimate_tokens("") == 0

    def test_ascii_uses_low_weight(self):
        # 100 ASCII 文字 × 0.28 = 28 → ×1.05 = 29.4 → 30
        assert estimate_tokens("a" * 100) == 30
        # 実測 BPE 相当（英単語は ~4 文字/トークン）の桁に収まる
        assert estimate_tokens("hello world") == 4

    def test_cjk_uses_weight_one(self):
        # 10 文字 × 1.0 = 10 → ×1.05 = 10.5 → 11
        assert estimate_tokens("あ" * 10) == 11
        assert estimate_tokens("漢字テスト") == 6

    def test_other_script_uses_mid_weight(self):
        # アクセント記号・アラビア文字等: ×0.5
        assert estimate_tokens("é" * 10) == 6
        assert estimate_tokens("مرحبا") == 3

    def test_mixed_japanese_english(self):
        text = "私は Alice です。Hello!"
        # CJK '私は' 'です' '。' = 5.0 / ASCII "Alice Hello!" 12×0.28 = 3.36
        # その他(空白) 2×0.5 = 1.0 → 計 9.36 → ×1.05 = 9.83 → 10
        assert estimate_tokens(text) == 10

    def test_monotonic(self):
        assert estimate_tokens("あ" * 100) > estimate_tokens("あ" * 50) > 0

    def test_max_boundary(self):
        # 上限ちょうど: 2857 CJK 文字 = 2857 × 1.05 = 2999.85 → 3000
        at_limit = estimate_tokens("あ" * 2857)
        assert at_limit <= DEFAULT_PROFILE_MAX_TOKENS
        # 1 文字増やすと超過
        assert estimate_tokens("あ" * 2858) > DEFAULT_PROFILE_MAX_TOKENS

    @pytest.mark.parametrize("text", ["\n", " ", "\t", "。", "a"])
    def test_short_inputs_round_up_not_down(self, text):
        assert estimate_tokens(text) >= 1


class TestTokenWeights:
    def test_module_constants_are_swappable(self):
        """実測後に定数差し替えで校正できる形であること（§1-4）."""
        assert TOKEN_WEIGHTS["cjk"] == 1.0
        assert TOKEN_WEIGHTS["ascii"] == 0.28
        assert TOKEN_WEIGHTS["other"] == 0.5
        assert TOKEN_WEIGHTS["safety"] == 1.05
        assert DEFAULT_PROFILE_MAX_TOKENS == 3000
