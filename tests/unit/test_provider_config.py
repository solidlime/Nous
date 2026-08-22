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
