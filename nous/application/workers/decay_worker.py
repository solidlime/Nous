from __future__ import annotations

import contextlib
import threading
import time
from typing import TYPE_CHECKING, Any

from nous.domain.shared.time_utils import get_now
from nous.infrastructure.logging.structured import get_logger

logger = get_logger(__name__)

if TYPE_CHECKING:
    from nous.application.chat.reflection import ReflectionEngine
    from nous.application.use_cases import AppContext
    from nous.domain.chat_config import ChatConfig
    from nous.infrastructure.llm.base import LLMProvider


class DecayWorker:
    """FSRS v6 power-law forgetting curve decay worker + periodic reflection."""

    REFLECTION_INTERVAL = (
        24  # trigger reflection every N decay cycles (was 50; changed to 24 for more frequent periodic reflection ⑫)
    )

    def __init__(
        self,
        context: AppContext,
        interval_seconds: int = 3600,
        reflection_engine: ReflectionEngine | None = None,
        llm_provider: LLMProvider | None = None,
        config: ChatConfig | None = None,
    ) -> None:
        self.context = context
        self.interval = interval_seconds
        self._reflection_engine = reflection_engine
        self._llm_provider = llm_provider
        self._config = config
        self._running = False
        self._thread: threading.Thread | None = None
        self._cycle_count = 0

    def start(self) -> None:
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._running = False

    def _run(self) -> None:
        while self._running:
            self._run_cycle()
            time.sleep(self.interval)

    def _run_cycle(self) -> None:
        """Run one full cycle: decay + optional reflection."""
        self._decay_cycle()
        self._cycle_count += 1

        if self._cycle_count % self.REFLECTION_INTERVAL == 0:
            self._maybe_run_reflection()

    def _decay_cycle(self) -> None:
        """Run one decay cycle: update all memory strengths."""
        result = self.context.memory_repo.get_all_strengths()
        if not result.is_ok:
            return

        now = get_now()
        strengths = result.value
        logger.debug("Decay cycle started, checking %d strengths", len(strengths))

        processed = 0
        updated = 0
        skipped = 0
        errors = 0
        for strength in strengths:
            processed += 1
            elapsed = (now - strength.last_decay).total_seconds() / 3600 if strength.last_decay else 24.0

            # LTM uses slower decay exponent
            decay_exp = 0.3 if strength.is_ltm else 0.5
            recall = strength.compute_recall(elapsed, decay_exponent=decay_exp)
            score = strength.compute_strength_score()
            new_strength_val = recall * score

            # STM → LTM automatic promotion (before min_strength check)
            if not strength.is_ltm and new_strength_val > 0.7 and strength.recall_count >= 3:
                strength.is_ltm = True

            # Archive condition (before min_strength check)
            if new_strength_val < 0.2 and strength.last_recall:
                # Unify timezone to avoid aware/naive mismatch
                _now = now.replace(tzinfo=None)
                _last = strength.last_recall.replace(tzinfo=None)
                inactive_days = (_now - _last).days
                if inactive_days > 30:
                    with contextlib.suppress(Exception):
                        self.context.memory_repo.update(
                            strength.memory_key,
                            lifecycle_status="archived",
                        )

            min_strength = (
                self._config.forgetting_min_strength if self._config else self.context.settings.forgetting.min_strength
            )
            if new_strength_val < min_strength:
                skipped += 1
                continue

            strength.strength = new_strength_val
            strength.last_decay = now
            save_result = self.context.memory_repo.save_strength(strength)
            if save_result.is_ok:
                updated += 1
            else:
                errors += 1

        logger.info(
            "Decay cycle done: %d processed / %d updated / %d skipped / %d errors",
            processed,
            updated,
            skipped,
            errors,
        )

    def _maybe_run_reflection(self) -> None:
        """Run reflection if engine and LLM provider are configured.

        Uses the language-agnostic ReflectionEngine when available;
        falls back to no-op if not configured.
        """
        if self._reflection_engine is None or self._llm_provider is None:
            return

        persona = getattr(self.context, "persona", None) or self.context.__class__.__name__
        try:
            import asyncio

            # Create a fresh event loop for the background thread if needed
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)

            results: list[dict[str, Any]] = loop.run_until_complete(
                self._reflection_engine.reflect(
                    persona=persona,
                    memory_service=self.context.memory_service,
                    llm=self._llm_provider,
                )
            )
            if results:
                from nous.infrastructure.logging.structured import get_logger

                get_logger(__name__).info(
                    "DecayWorker: reflection produced %d insights for %s",
                    len(results),
                    persona,
                )
        except Exception as exc:
            from nous.infrastructure.logging.structured import get_logger

            get_logger(__name__).warning("DecayWorker: reflection failed: %s", exc)
