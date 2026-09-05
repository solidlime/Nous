"""Tests for SpreadingActivation — PPR-lite diffusion."""

from __future__ import annotations

import pytest

from nous.domain.memory.memory_link import MemoryLink
from nous.domain.search.spreading_activation import SpreadingActivation


def _link(src: str, tgt: str, weight: float = 0.5) -> MemoryLink:
    return MemoryLink(source_key=src, target_key=tgt, weight=weight)


class TestSpreadingActivation:
    def test_two_hop_propagation(self) -> None:
        """Activation diffuses seed → hop1 → hop2 with falloff (PPR stationary)."""
        links = [
            _link("a", "b", weight=0.8),
            _link("b", "c", weight=0.8),
        ]
        sa = SpreadingActivation(threshold=0.0, max_iters=500)
        result = sa.propagate(["a"], links)
        # p* : a=0.3887, b=0.3304, c=0.2808 (α=0.15, dangling teleports to seed)
        assert "a" not in result  # seed excluded
        assert result.get("b", 0.0) == pytest.approx(0.3304, abs=1e-3)
        assert result.get("c", 0.0) == pytest.approx(0.2808, abs=1e-3)
        assert result["b"] > result["c"] > 0

    def test_activation_below_threshold_ignored(self) -> None:
        """Nodes below threshold do not propagate further."""
        links = [
            _link("a", "b", weight=0.5),
            _link("b", "c", weight=0.9),
        ]
        sa = SpreadingActivation(hops=2, decay=1.0, retention=0.0, threshold=0.5)
        result = sa.propagate(["a"], links)
        # a → b = 0.5 (not below threshold), b → c = 0.5*0.9 = 0.45 (below 0.5)
        assert "c" not in result

    def test_degree_normalization(self) -> None:
        """Out-strength split: equal weights divide evenly (PPR column-stochastic)."""
        links = [
            _link("a", "b", weight=1.0),
            _link("a", "c", weight=1.0),  # degree 2
        ]
        sa = SpreadingActivation(threshold=0.0, max_iters=500)
        result = sa.propagate(["a"], links)
        # Symmetric split: b == c ≈ 0.2297
        assert result.get("b", 0.0) == pytest.approx(0.2297, abs=1e-3)
        assert result["b"] == result["c"]

    def test_seed_keys_not_in_result(self) -> None:
        """Seed keys are excluded from the returned activation map."""
        links = [_link("a", "b", weight=0.8)]
        sa = SpreadingActivation(hops=1)
        result = sa.propagate(["a"], links)
        assert "a" not in result
        assert "b" in result

    def test_no_links_returns_empty(self) -> None:
        """No links → no propagation beyond seeds."""
        sa = SpreadingActivation(hops=2)
        result = sa.propagate(["a"], [])
        assert result == {}

    def test_retention_keeps_source_alive(self) -> None:
        """Source retains a fraction of activation for next hop."""
        links = [
            _link("a", "b", weight=0.5),
            _link("b", "c", weight=0.5),
        ]
        sa = SpreadingActivation(hops=2, decay=1.0, retention=0.5, threshold=0.0)
        result = sa.propagate(["a"], links)
        assert result.get("b", 0.0) > 0
        assert result.get("c", 0.0) > 0

    def test_reset_prob_anchors_at_seeds(self) -> None:
        """Higher reset_prob keeps mass closer to seeds (replaces hop decay)."""
        links = [_link("a", "b", weight=1.0)]
        low = SpreadingActivation(threshold=0.0, max_iters=500, reset_prob=0.15).propagate(["a"], links)
        high = SpreadingActivation(threshold=0.0, max_iters=500, reset_prob=0.5).propagate(["a"], links)
        assert low["b"] == pytest.approx(0.4595, abs=1e-3)
        assert high["b"] == pytest.approx(1.0 / 3.0, abs=1e-3)
        assert high["b"] < low["b"]

    def test_multiple_seeds_fan_in_conserved(self) -> None:
        """Fan-in combines without inflation: mass conserved (PPR, no >1.0 blowup)."""
        links = [
            _link("a", "c", weight=0.5),
            _link("b", "c", weight=0.5),
        ]
        sa = SpreadingActivation(threshold=0.0, max_iters=500)
        result = sa.propagate(["a", "b"], links)
        # Both seeds feed c, yet total mass stays a distribution
        assert result["c"] == pytest.approx(0.4595, abs=1e-3)
        assert result["c"] <= 1.0
