"""PPR-lite diffusion retrieval (F3) tests.

- 2-hop 到達＋減衰フォールオフ
- ハブ偏重が旧SA比で緩和
- seed 除外・空リンクで空辞書・決定的同一結果
"""

from __future__ import annotations

from nous.domain.memory.memory_link import MemoryLink
from nous.domain.search.spreading_activation import SpreadingActivation


def _link(src: str, dst: str, weight: float = 0.5) -> MemoryLink:
    return MemoryLink(source_key=src, target_key=dst, weight=weight)


def _old_sa(seed_keys: list[str], links: list[MemoryLink], hops: int = 2) -> dict[str, float]:
    """Reference: pre-PPR spreading activation (decay=0.5, retention=0.3)."""
    activation: dict[str, float] = {k: 1.0 for k in seed_keys}
    for _ in range(hops):
        next_act: dict[str, float] = {}
        for src, curr in activation.items():
            if curr <= 0.01:
                continue
            outgoing = [link for link in links if link.source_key == src]
            degree = max(len(outgoing), 1)
            for link in outgoing:
                next_act[link.target_key] = next_act.get(link.target_key, 0.0) + (curr * 0.7 * link.weight) / degree
            next_act[src] = next_act.get(src, 0.0) + curr * 0.3
        all_keys = set(activation) | set(next_act)
        activation = {k: activation.get(k, 0.0) * 0.5 + next_act.get(k, 0.0) for k in all_keys}
    return {k: v for k, v in activation.items() if k not in seed_keys}


class TestPPRRetrieval:
    def test_two_hop_reach_with_falloff(self) -> None:
        links = [_link("s", "a", 1.0), _link("a", "b", 1.0)]
        result = SpreadingActivation().propagate(["s"], links)
        assert "s" not in result
        assert result["a"] > result["b"] > 0

    def test_hub_bias_relaxed_vs_sa(self) -> None:
        """ハブ偏重: 旧SAはハブに質量を膨張させるが、PPRは分布を保つ"""
        links = [_link("s1", "H", 1.0), _link("s2", "H", 1.0)]
        links += [_link("H", f"leaf_{i}", 0.5) for i in range(20)]
        ppr = SpreadingActivation().propagate(["s1", "s2"], links)
        sa = _old_sa(["s1", "s2"], links)
        assert sum(ppr.values()) <= 1.0 + 1e-9
        assert ppr["H"] <= 1.0 < sa["H"]

    def test_seed_excluded(self) -> None:
        links = [_link("s1", "n", 1.0), _link("s2", "n", 1.0)]
        result = SpreadingActivation().propagate(["s1", "s2"], links)
        assert "s1" not in result and "s2" not in result
        assert result["n"] > 0

    def test_empty_links_empty_dict(self) -> None:
        assert SpreadingActivation().propagate(["s"], []) == {}
        assert SpreadingActivation().propagate([], [_link("a", "b")]) == {}

    def test_deterministic(self) -> None:
        links = [_link("s", "H", 1.0), _link("s", "t", 0.5), _link("H", "u", 0.5), _link("t", "u", 0.5)]
        first = SpreadingActivation().propagate(["s"], links)
        second = SpreadingActivation().propagate(["s"], links)
        assert first == second

    def test_llm_seed_filter_off_by_default(self) -> None:
        """LLM seed フィルタは既定OFF（遅延回避）。ON＋filter時のみ適用"""
        links = [_link("s1", "n", 1.0), _link("s2", "z", 1.0)]
        drop_s2 = lambda seeds: [s for s in seeds if s != "s2"]  # noqa: E731
        default = SpreadingActivation(seed_filter=drop_s2).propagate(["s1", "s2"], links)
        assert default == SpreadingActivation().propagate(["s1", "s2"], links)
        assert "z" in default
        filtered = SpreadingActivation(llm_seed_filter=True, seed_filter=drop_s2).propagate(["s1", "s2"], links)
        assert filtered != default
        assert "z" not in filtered
