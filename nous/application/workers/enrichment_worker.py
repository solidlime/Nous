from __future__ import annotations

import asyncio
import threading
from datetime import datetime
from typing import TYPE_CHECKING, Any

from nous.domain.memory import wiring_events
from nous.domain.memory.enrich_service import MemoryEnrichService
from nous.domain.shared.time_utils import get_now
from nous.infrastructure.logging.structured import get_logger

if TYPE_CHECKING:
    from nous.application.use_cases import AppContext
    from nous.domain.chat_config import ChatConfig
    from nous.domain.memory.entities import Memory

logger = get_logger(__name__)

_NOVELTY_SEARCH_LIMIT = 10  # same breadth as ContradictionDetector.find_potential_contradictions


class EnrichmentWorker:
    """REM-equivalent background worker: novelty gate + LLM memory enrichment.

    Same lifecycle pattern as DecayWorker (threading.Thread + Event.wait).

    - Cursor contract: only memories created after the previous cycle are
      processed (idempotent; bounds LLM cost).
    - Batch limit: LLM enrichment capped at ``brain_enrich_batch_limit``
      memories per cycle.
    - Novelty gate: vector-search only (no LLM). Empty search results count
      as novel (max_cosine := 0.0). Boost fires at most once per memory.
    """

    def __init__(self, context: AppContext, config: ChatConfig | None = None) -> None:
        self.context = context
        self._config = config
        self.interval = self._num("brain_enrich_interval_seconds", 60.0)
        self._batch_limit = max(1, int(self._num("brain_enrich_batch_limit", 5.0)))
        self._sim_threshold = self._num("brain_novelty_sim_threshold", 0.75)
        self._importance_threshold = self._num("brain_novelty_importance_threshold", 0.6)
        self._stability_multiplier = self._num("brain_novelty_stability_multiplier", 2.0)
        self._cursor: datetime = get_now().replace(tzinfo=None)
        # Memories processed by this worker instance (ties with the cursor's
        # created_at can exist; the set guarantees once-only processing).
        # Cleared on restart together with the cursor=now reset.
        self._processed_keys: set[str] = set()
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()

    # ------------------------------------------------------------------
    # Config resolution (getattr-based; non-numeric → contract default)
    # ------------------------------------------------------------------

    def _num(self, name: str, default: float) -> float:
        val = getattr(self._config, name, None)
        if isinstance(val, bool) or not isinstance(val, (int, float)):
            return default
        return float(val)

    # ------------------------------------------------------------------
    # Lifecycle (DecayWorker pattern)
    # ------------------------------------------------------------------

    def start(self) -> None:
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        self._stop_event.set()
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=timeout)

    def _run(self) -> None:
        while not self._stop_event.is_set():
            self._run_cycle()
            self._stop_event.wait(self.interval)

    # ------------------------------------------------------------------
    # Cycle
    # ------------------------------------------------------------------

    def _run_cycle(self) -> None:
        candidates = self._memories_since_cursor()
        if not candidates:
            return
        batch = candidates[: self._batch_limit]
        # Mark as processed up-front: gates/enrichment are best-effort, and a
        # failure must not turn into an infinite retry loop.
        for memory in batch:
            self._processed_keys.add(memory.key)
        for memory in batch:
            self._novelty_gate(memory)
        self._enrich_batch(batch)
        self._advance_cursor(batch)

    def _memories_since_cursor(self) -> list[Memory]:
        """Active memories at/after the cursor and not yet processed (sorted)."""
        found: list[tuple[datetime, Memory]] = []
        try:
            result = self.context.memory_repo.find_all()
            if getattr(result, "is_ok", False):
                values = getattr(result, "value", None)
                if isinstance(values, list):
                    for m in values:
                        created = getattr(m, "created_at", None)
                        if not isinstance(created, datetime):
                            continue
                        if created.tzinfo is not None:
                            created = created.replace(tzinfo=None)
                        if (
                            created >= self._cursor
                            and m.key not in self._processed_keys
                            and getattr(m, "lifecycle_status", "active") == "active"
                        ):
                            found.append((created, m))
        except Exception:
            logger.debug("EnrichmentWorker: find_all failed", exc_info=True)
        found.sort(key=lambda pair: pair[0])
        return [m for _, m in found]

    def _advance_cursor(self, batch: list[Memory]) -> None:
        """Advance the cursor to the last processed memory's created_at.

        Overflow (memories beyond the batch limit) keeps created_at >= cursor
        and stays outside ``_processed_keys``, so the next cycle picks it up.
        """
        latest = max((self._naive(m.created_at) for m in batch), default=None)
        if latest is not None:
            self._cursor = max(self._cursor, latest)

    @staticmethod
    def _naive(value: datetime) -> datetime:
        return value.replace(tzinfo=None) if value.tzinfo is not None else value

    # ------------------------------------------------------------------
    # Novelty gate (vector search only — no LLM)
    # ------------------------------------------------------------------

    def _novelty_gate(self, memory: Memory) -> None:
        """Dopamine-style novelty gate (Lisman & Grace 2005).

        When the best vector similarity to existing memories is below
        ``brain_novelty_sim_threshold`` and importance passes the salience
        threshold, stability is multiplied once by
        ``brain_novelty_stability_multiplier`` and a ``novelty_gate`` pulse
        is emitted. The cursor contract guarantees once-per-memory.
        """
        try:
            importance = float(getattr(memory, "importance", 0.5))
        except (TypeError, ValueError):
            importance = 0.5
        if importance < self._importance_threshold:
            return

        max_cosine = self._max_cosine(memory)
        if max_cosine >= self._sim_threshold:
            return

        try:
            result = self.context.memory_repo.get_strength(memory.key)
            if not getattr(result, "is_ok", False):
                return
            strength = getattr(result, "value", None)
            if strength is None:
                return
            strength.stability = min(strength.stability * self._stability_multiplier, 365.0)
            if not getattr(self.context.memory_repo.save_strength(strength), "is_ok", False):
                return
        except Exception:
            logger.debug("EnrichmentWorker: novelty boost failed for %s", memory.key, exc_info=True)
            return

        # Success-only emit (wiring convention)
        try:
            wiring_events.emit(
                "novelty_gate",
                source=memory.key,
                weight=strength.stability,
                meta={
                    "persona": wiring_events.repo_persona(self.context.memory_repo),
                    "memory_key": memory.key,
                    "max_cosine": max_cosine,
                },
            )
        except Exception:
            logger.debug("wiring emit failed", exc_info=True)

    def _max_cosine(self, memory: Memory) -> float:
        """Best cosine similarity to existing memories (0.0 when none)."""
        store = getattr(self.context, "vector_store", None)
        if store is None:
            return 0.0
        try:
            result = self._run_async(store.search(self.context.persona, memory.content, limit=_NOVELTY_SEARCH_LIMIT))
        except Exception:
            return 0.0
        if not getattr(result, "is_ok", False):
            return 0.0
        best = 0.0
        for key, score in getattr(result, "value", None) or []:
            if key == memory.key:
                continue
            try:
                best = max(best, float(score))
            except (TypeError, ValueError):
                continue
        return best

    # ------------------------------------------------------------------
    # LLM enrichment (capped per cycle)
    # ------------------------------------------------------------------

    def _enrich_batch(self, memories: list[Memory]) -> None:
        """Run MemoryEnrichService.enrich_memory on up to ``batch_limit`` memories."""
        service = MemoryEnrichService(
            getattr(self.context, "_enricher", None),
            getattr(self.context, "entity_service", None),
            self.context.memory_repo,
        )
        for memory in memories[: self._batch_limit]:
            try:
                self._run_async(
                    service.enrich_memory(
                        memory,
                        memory.content,
                        None,
                        memory.key,
                        float(getattr(memory, "importance", 0.5)),
                    )
                )
            except Exception:
                logger.debug("EnrichmentWorker: enrich failed for %s", memory.key, exc_info=True)

    # ------------------------------------------------------------------
    # Async bridge (worker thread has no running loop)
    # ------------------------------------------------------------------

    def _run_async(self, coro: Any) -> Any:
        loop = asyncio.new_event_loop()
        try:
            asyncio.set_event_loop(loop)
            return loop.run_until_complete(coro)
        finally:
            asyncio.set_event_loop(None)
            loop.close()
