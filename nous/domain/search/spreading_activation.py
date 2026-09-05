"""Collins & Loftus 1975 + PPR-lite diffusion through memory network."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable

    from nous.domain.memory.memory_link import MemoryLink


class SpreadingActivation:
    """Personalized PageRank diffusion over a memory link network.

    Starting from seed memory keys, activation diffuses along associative
    links with random restart to the seed distribution ``p_0``::

        p_{t+1} = (1 − α) · W · p_t + α · p_0

    ``W`` is column-stochastic: each source's outgoing mass is split by
    out-strength (degree split weighted by link weight). Dangling nodes
    (no outgoing links) teleport their mass back to the seed distribution
    ``p_0`` — dead ends anchor rather than inflate. Iteration runs
    up to ``max_iters`` with L1 ``tol`` convergence check (deterministic:
    nodes are visited in sorted order).

    ``hops`` / ``decay`` / ``retention`` are pre-PPR legacy params kept
    for API compatibility (no effect on PPR diffusion). ``threshold``
    filters the output. Result excludes seed keys.

    LLM seed filtering is OFF by default (latency): ``seed_filter`` runs
    only when ``llm_seed_filter`` is True.
    """

    def __init__(
        self,
        hops: int = 2,
        decay: float = 0.5,
        retention: float = 0.3,
        threshold: float = 0.01,
        reset_prob: float = 0.15,
        max_iters: int = 20,
        tol: float = 1e-4,
        llm_seed_filter: bool = False,
        seed_filter: Callable[[list[str]], list[str]] | None = None,
    ) -> None:
        self.hops = hops
        self.decay = decay
        self.retention = retention
        self.threshold = threshold
        self.reset_prob = reset_prob
        self.max_iters = max_iters
        self.tol = tol
        self.llm_seed_filter = llm_seed_filter
        self.seed_filter = seed_filter

    def propagate(self, seed_keys: list[str], links: list[MemoryLink]) -> dict[str, float]:
        """Run PPR diffusion and return {target_key: activation_score}."""
        seeds = list(dict.fromkeys(seed_keys))
        if self.llm_seed_filter and self.seed_filter is not None:
            seeds = list(dict.fromkeys(self.seed_filter(seeds)))
        if not seeds:
            return {}

        # Column-stochastic W: out-strength normalized, dangling → self-loop
        out_strength: dict[str, float] = {}
        for link in links:
            out_strength[link.source_key] = out_strength.get(link.source_key, 0.0) + link.weight
        nodes = sorted({k for link in links for k in (link.source_key, link.target_key)} | set(seeds))
        p0 = {k: (1.0 / len(seeds) if k in seeds else 0.0) for k in nodes}
        curr = dict(p0)
        restart = self.reset_prob

        for _ in range(max(1, self.max_iters)):
            nxt = {k: restart * p0[k] for k in nodes}
            dangling_mass = 0.0
            for link in links:
                mass = curr.get(link.source_key, 0.0)
                if mass <= 0.0:
                    continue
                denom = out_strength.get(link.source_key, 0.0)
                if denom > 0.0:
                    nxt[link.target_key] = nxt.get(link.target_key, 0.0) + (1.0 - restart) * mass * link.weight / denom
            for k in nodes:
                if out_strength.get(k, 0.0) <= 0.0:
                    dangling_mass += curr.get(k, 0.0)
            if dangling_mass > 0.0:
                for k in nodes:
                    if p0[k] > 0.0:
                        nxt[k] = nxt.get(k, 0.0) + (1.0 - restart) * dangling_mass * p0[k]
            if sum(abs(nxt[k] - curr[k]) for k in nodes) < self.tol:
                curr = nxt
                break
            curr = nxt

        seed_set = set(seeds)
        return {k: v for k, v in curr.items() if k not in seed_set and v > self.threshold}
