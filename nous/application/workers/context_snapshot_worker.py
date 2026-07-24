"""Background worker that keeps the MemoryContextSnapshot up to date."""

from __future__ import annotations

import threading
import time
from typing import TYPE_CHECKING

from nous.infrastructure.logging.structured import get_logger

if TYPE_CHECKING:
    from nous.config.settings import Settings
    from nous.domain.chat_config import ChatConfig

logger = get_logger(__name__)


class ContextSnapshotWorker:
    """Periodically rebuilds MemoryContextSnapshot for all active personas.

    LLM-free, so always safe to run.
    """

    def __init__(self, settings: Settings, config: ChatConfig | None = None) -> None:
        self._settings = settings
        self._config = config
        self._running = False
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        """Start the background snapshot rebuild thread."""
        enabled = self._config.memorag_enabled if self._config else self._settings.memorag.enabled
        if not enabled:
            logger.info("ContextSnapshotWorker: MemoRAG disabled, skipping start")
            return
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        interval_hours = (
            self._config.memorag_snapshot_interval_hours
            if self._config
            else self._settings.memorag.snapshot_interval_hours
        )
        threshold = self._settings.memorag.rebuild_threshold  # stays at Settings level
        logger.info(
            "ContextSnapshotWorker started (interval=%.1fh, threshold=%d)",
            interval_hours,
            threshold,
        )

    def stop(self) -> None:
        self._running = False
        logger.info("ContextSnapshotWorker stopped")

    def _run(self) -> None:
        interval_hours = (
            self._config.memorag_snapshot_interval_hours
            if self._config
            else self._settings.memorag.snapshot_interval_hours
        )
        interval = interval_hours * 3600
        while self._running:
            time.sleep(interval)
            if self._running:
                self._rebuild_all()

    def _rebuild_all(self) -> None:
        from nous.application.use_cases import AppContextRegistry

        try:
            personas = list(AppContextRegistry._contexts.keys())
        except Exception:
            logger.exception("ContextSnapshotWorker: failed to list personas")
            return

        threshold = self._settings.memorag.rebuild_threshold
        top_n = (
            self._config.memorag_top_k
            if self._config
            else self._settings.memorag.snapshot_top_memories
        )
        for persona in personas:
            try:
                self._rebuild_persona(persona, threshold, top_n)
            except Exception:
                logger.exception("ContextSnapshotWorker: error for persona=%s", persona)

    def _rebuild_persona(self, persona: str, threshold: int, top_n: int) -> None:
        from nous.application.use_cases import AppContextRegistry
        from nous.domain.search.context_snapshot import MemoryContextSnapshot

        ctx = AppContextRegistry.get(persona)
        count_result = ctx.memory_repo.count()
        current_count = count_result.value if count_result.is_ok else 0

        existing = MemoryContextSnapshot.load(ctx.memory_repo)
        if existing and not existing.is_stale(current_count, threshold=threshold):
            logger.debug("ContextSnapshotWorker: snapshot for %s is fresh, skipping", persona)
            return

        snapshot = MemoryContextSnapshot.build(ctx.memory_repo, top_n=top_n)
        snapshot.save(ctx.memory_repo)
        logger.info("ContextSnapshotWorker: rebuilt snapshot for %s (%d memories)", persona, current_count)
