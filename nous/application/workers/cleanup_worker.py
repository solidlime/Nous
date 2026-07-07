from __future__ import annotations

import asyncio
import threading
import time
from typing import TYPE_CHECKING

from nous.infrastructure.logging.structured import get_logger

if TYPE_CHECKING:
    from nous.application.use_cases import AppContext

logger = get_logger(__name__)


class CleanupWorker:
    """Duplicate detection and cleanup worker."""

    def __init__(self, context: AppContext, interval_seconds: int = 86400) -> None:
        self.context = context
        self.interval = interval_seconds
        self._running = False
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._running = False

    def _run(self) -> None:
        while self._running:
            self._cleanup_cycle()
            time.sleep(self.interval)

    def _cleanup_cycle(self) -> None:
        """Find and flag near-duplicate memories."""
        try:
            asyncio.run(self._cleanup_cycle_async())
        except RuntimeError:
            # Already in event loop — run in a thread pool
            import concurrent.futures

            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as _pool:
                _pool.submit(asyncio.run, self._cleanup_cycle_async()).result()

    async def _cleanup_cycle_async(self) -> None:
        """Async implementation of cleanup cycle."""
        vs = self.context.vector_store
        if vs is None:
            return

        result = self.context.memory_repo.find_all()
        if not result.is_ok:
            return

        memories = result.value
        seen_keys: set[str] = set()
        for memory in memories:
            if memory.key in seen_keys:
                continue
            search_result = await vs.search(self.context.persona, memory.content, limit=5)
            if not search_result.is_ok:
                continue
            for key, score in search_result.value:
                if key != memory.key and score > 0.95:
                    logger.info(
                        "Potential duplicate detected: %s <-> %s (score=%.3f)",
                        memory.key,
                        key,
                        score,
                    )
                    seen_keys.add(key)
