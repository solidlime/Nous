"""Collins & Loftus 1975 + SYNAPSE 2026: spreading activation through memory network."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from nous.domain.memory.memory_link import MemoryLink


class SpreadingActivation:
    """Spreading activation over a memory link network.

    Starting from seed memory keys, activation propagates along associative
    links for ``hops`` iterations.  Each hop:
      * Activation decays by ``decay`` factor.
      * Source retains ``retention`` fraction of its activation.
      * Spread is divided by degree (outgoing link count).

    Result excludes seed keys — only activated neighbours are returned.
    """

    def __init__(
        self,
        hops: int = 2,
        decay: float = 0.5,
        retention: float = 0.3,
        threshold: float = 0.01,
    ) -> None:
        self.hops = hops
        self.decay = decay
        self.retention = retention
        self.threshold = threshold

    def propagate(self, seed_keys: list[str], links: list[MemoryLink]) -> dict[str, float]:
        """Run spreading activation and return {target_key: activation_score}."""
        activation: dict[str, float] = {k: 1.0 for k in seed_keys}

        for _ in range(self.hops):
            next_act: dict[str, float] = {}

            for src, curr in activation.items():
                if curr <= self.threshold:
                    continue

                outgoing = [link for link in links if link.source_key == src]
                degree = max(len(outgoing), 1)

                for link in outgoing:
                    spread = (curr * (1 - self.retention) * link.weight) / degree
                    next_act[link.target_key] = next_act.get(link.target_key, 0.0) + spread

                # Retention: source keeps a fraction of its activation
                next_act[src] = next_act.get(src, 0.0) + curr * self.retention

            # Combine with decay
            all_keys = set(activation) | set(next_act)
            activation = {
                k: activation.get(k, 0.0) * self.decay + next_act.get(k, 0.0)
                for k in all_keys
            }

        # Remove seed keys from result — only return activated neighbours
        return {k: v for k, v in activation.items() if k not in seed_keys}
