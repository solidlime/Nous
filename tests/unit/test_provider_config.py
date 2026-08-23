"""Tests for ProviderConfig reasoning fields (R1)."""

from __future__ import annotations

import pytest

from nous.domain.provider_config import ProviderConfig


class TestProviderConfigReasoning:
    def test_defaults(self):
        """reasoning_enabled は False, reasoning_effort は "medium" がデフォルト."""
        cfg = ProviderConfig()
        assert cfg.reasoning_enabled is False
        assert cfg.reasoning_effort == "medium"

    def test_reasoning_enabled_can_be_set(self):
        cfg = ProviderConfig(reasoning_enabled=True)
        assert cfg.reasoning_enabled is True

    @pytest.mark.parametrize("effort", ["low", "medium", "high", "max"])
    def test_valid_efforts_accepted(self, effort: str):
        cfg = ProviderConfig(reasoning_effort=effort)
        assert cfg.reasoning_effort == effort

    def test_invalid_effort_clamped_to_medium(self):
        """許容値以外の reasoning_effort は既定 "medium" へ clamp（raise しない）."""
        cfg = ProviderConfig(reasoning_effort="ultra")
        assert cfg.reasoning_effort == "medium"

    def test_to_safe_dict_includes_reasoning(self):
        """to_safe_dict に新フィールドが含まれる."""
        cfg = ProviderConfig(reasoning_enabled=True, reasoning_effort="high")
        d = cfg.to_safe_dict()
        assert d["reasoning_enabled"] is True
        assert d["reasoning_effort"] == "high"


class TestProviderConfigTemperature:
    def test_temperature_rounded_to_two_decimals(self):
        """3桁以上の temperature は小数点2桁に丸められる.

        Python の round は banker's rounding + float 表現の影響を受ける:
        round(0.725, 2) == 0.72（0.725 は実際には 0.72499... として格納される）。
        """
        cfg = ProviderConfig(temperature=0.725)
        assert cfg.temperature == 0.72

    def test_temperature_clamp_still_applies_after_round(self):
        cfg = ProviderConfig(temperature=5.0)
        assert cfg.temperature == 2.0
        cfg2 = ProviderConfig(temperature=-1.0)
        assert cfg2.temperature == 0.0

    @pytest.mark.parametrize("value", [0.7, 0.725, 1.23456, 0.123456789])
    def test_temperature_always_at_most_two_decimals(self, value: float):
        cfg = ProviderConfig(temperature=value)
        assert cfg.temperature == round(cfg.temperature, 2)


class TestProviderConfigTopP:
    def test_top_p_rounded_to_two_decimals(self):
        """3桁以上の top_p は小数点2桁に丸められる."""
        cfg = ProviderConfig(top_p=0.955)
        assert cfg.top_p == 0.95

    def test_top_p_none_stays_none(self):
        assert ProviderConfig(top_p=None).top_p is None

    @pytest.mark.parametrize("value", [0.9, 0.955, 0.123456])
    def test_top_p_always_at_most_two_decimals(self, value: float):
        cfg = ProviderConfig(top_p=value)
        assert cfg.top_p is not None
        assert cfg.top_p == round(cfg.top_p, 2)
