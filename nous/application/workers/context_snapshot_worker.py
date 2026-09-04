"""Background worker that keeps the MemoryContextSnapshot up to date."""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING

from nous.infrastructure.logging.structured import get_logger

if TYPE_CHECKING:
    from nous.config.settings import Settings

logger = get_logger(__name__)


class ContextSnapshotWorker:
    """Periodically rebuilds MemoryContextSnapshot for all active personas.

    LLM-free, so always safe to run.
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._running = False
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()

    def start(self) -> None:
        """Start the background snapshot rebuild thread.

        Gated by the global infra kill switch (settings.memorag.enabled) only.
        Per-persona on/off (ChatConfig.memorag_enabled) is checked per persona
        in _rebuild_persona.
        """
        if not self._settings.memorag.enabled:
            logger.info("ContextSnapshotWorker: MemoRAG disabled (settings), skipping start")
            return
        self._stop_event.clear()
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        interval_hours = self._settings.memorag.snapshot_interval_hours
        threshold = self._settings.memorag.rebuild_threshold  # stays at Settings level
        logger.info(
            "ContextSnapshotWorker started (interval=%.1fh, threshold=%d)",
            interval_hours,
            threshold,
        )

    def stop(self, timeout: float = 5.0) -> None:
        self._running = False
        self._stop_event.set()
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=timeout)
        logger.info("ContextSnapshotWorker stopped")

    def _run(self) -> None:
        interval = self._settings.memorag.snapshot_interval_hours * 3600
        while not self._stop_event.wait(interval):
            self._rebuild_all()

    def _rebuild_all(self) -> None:
        from nous.application.use_cases import AppContextRegistry

        try:
            personas = list(AppContextRegistry._contexts.keys())
        except Exception:
            logger.exception("ContextSnapshotWorker: failed to list personas")
            return

        threshold = self._settings.memorag.rebuild_threshold
        for persona in personas:
            try:
                self._rebuild_persona(persona, threshold)
            except Exception:
                logger.exception("ContextSnapshotWorker: error for persona=%s", persona)

    def _rebuild_persona(self, persona: str, threshold: int) -> None:
        from nous.application.use_cases import AppContextRegistry
        from nous.config.settings import get_settings
        from nous.domain.chat_config import ChatConfigFileRepository
        from nous.domain.search.context_snapshot import MemoryContextSnapshot

        ctx = AppContextRegistry.get(persona)

        # Per-persona switch: ChatConfig wins over the global default.
        # Same source as the chat path (config.json via ChatConfigFileRepository —
        # the WebUI toggle writes here; SQLite chat_settings is never written
        # in production).  Read once per 24h cycle, so file I/O cost is nil.
        settings_memorag = self._settings.memorag
        top_n = settings_memorag.snapshot_top_memories
        try:
            persona_config = ChatConfigFileRepository(get_settings().data_root).get(persona)
            if not persona_config.memorag_enabled:
                logger.debug("ContextSnapshotWorker: MemoRAG disabled for %s, skipping", persona)
                return
            top_n = persona_config.memorag_top_k or top_n
        except Exception:
            logger.debug("ContextSnapshotWorker: ChatConfig load failed for %s, using defaults", persona)

        count_result = ctx.memory_repo.count()
        current_count = count_result.value if count_result.is_ok else 0

        existing = MemoryContextSnapshot.load(ctx.memory_repo)
        if existing and not existing.is_stale(current_count, threshold=threshold):
            logger.debug("ContextSnapshotWorker: snapshot for %s is fresh, skipping", persona)
            return

        snapshot = MemoryContextSnapshot.build(ctx.memory_repo, top_n=top_n)
        snapshot.save(ctx.memory_repo)
        logger.info("ContextSnapshotWorker: rebuilt snapshot for %s (%d memories)", persona, current_count)
