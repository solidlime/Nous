"""Tests for SpreadingActivation — Collins & Loftus 1975 propagation."""

from __future__ import annotations

import pytest

from nous.domain.memory.memory_link import MemoryLink
from nous.domain.search.spreading_activation import SpreadingActivation


def _link(src: str, tgt: str, weight: float = 0.5) -> MemoryLink:
    return MemoryLink(source_key=src, target_key=tgt, weight=weight)


class TestSpreadingActivation:
    def test_two_hop_propagation(self) -> None:
        """Activation spreads from seed → hop1 → hop2."""
        links = [
            _link("a", "b", weight=0.8),
            _link("b", "c", weight=0.8),
        ]
        # decay=0.5 prevents old activation from dominating accumulation
        sa = SpreadingActivation(hops=2, decay=0.5, retention=0.0, threshold=0.0)
        result = sa.propagate(["a"], links)
        # hop1: a(1.0)→b(0.8), decay→a=0.5,b=0.8
        # hop2: a(0.5)→b(0.4), b(0.8)→c(0.64), decay+spread→b=0.8,c=0.64
        assert "a" not in result  # seed excluded
        assert result.get("b", 0.0) == pytest.approx(0.8, abs=1e-6)
        assert result.get("c", 0.0) == pytest.approx(0.64, abs=1e-6)

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
        """Activation is divided by outgoing degree."""
        links = [
            _link("a", "b", weight=1.0),
            _link("a", "c", weight=1.0),  # degree 2
        ]
        sa = SpreadingActivation(hops=1, decay=1.0, retention=0.0, threshold=0.0)
        result = sa.propagate(["a"], links)
        # Each target gets 1.0 * 1.0 / 2 = 0.5
        assert result.get("b", 0.0) == pytest.approx(0.5)
        assert result.get("c", 0.0) == pytest.approx(0.5)

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

    def test_decay_factor_applied(self) -> None:
        """Decay factor reduces activation each hop."""
        links = [_link("a", "b", weight=1.0)]
        sa = SpreadingActivation(hops=1, decay=0.3, retention=0.0, threshold=0.0)
        result = sa.propagate(["a"], links)
        assert result["b"] == pytest.approx(1.0)

    def test_multiple_seeds_fan_in(self) -> None:
        """Multiple seeds activating the same target combine additively."""
        links = [
            _link("a", "c", weight=0.5),
            _link("b", "c", weight=0.5),
        ]
        sa = SpreadingActivation(hops=1, decay=1.0, retention=0.0, threshold=0.0)
        result = sa.propagate(["a", "b"], links)
        # Both a and b contribute to c: 0.5 + 0.5 = 1.0
        assert result["c"] == pytest.approx(1.0)
