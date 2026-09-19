from __future__ import annotations

import contextlib
import threading
from typing import TYPE_CHECKING, Any

from nous.domain.memory import wiring_events
from nous.domain.memory.entities import importance_scaled_exponent
from nous.domain.memory.session_event import SessionEvent
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
        self._stop_event = threading.Event()
        self._cycle_count = 0
        # 周期リフレクション間隔（DecayWorker サイクル数）。config の
        # reflection_interval_cycles が設定されていればそれに従い、
        # 無ければクラス定数 (24) にフォールバック。
        raw_interval = getattr(self._config, "reflection_interval_cycles", None) if self._config is not None else None
        if isinstance(raw_interval, int) and not isinstance(raw_interval, bool) and raw_interval >= 1:
            self._reflection_interval = raw_interval
        else:
            self._reflection_interval = self.REFLECTION_INTERVAL

    def start(self) -> None:
        self._stop_event.clear()
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        logger.info("DecayWorker started (interval=%ss)", self.interval)

    def stop(self, timeout: float = 5.0) -> None:
        self._running = False
        self._stop_event.set()
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=timeout)

    def _run(self) -> None:
        while not self._stop_event.is_set():
            self._run_cycle()
            self._stop_event.wait(self.interval)

    def _run_cycle(self) -> None:
        """Run one full cycle: decay + optional reflection."""
        self._decay_cycle()
        self._cycle_count += 1

        if self._cycle_count % self._reflection_interval == 0:
            self._maybe_run_reflection()

    def _batch_memory_info(self) -> tuple[dict[str, float], dict[str, float], set[str]]:
        """One-query batch (no N+1): memory_key → importance / emotion_intensity,
        plus the gist-resist key set.

        Gist nodes (kind == "semantic" AND source_type == "consolidated")
        resist decay (transformation hypothesis). Empty on any failure.
        """
        try:
            result = self.context.memory_repo.find_all()
            if not getattr(result, "is_ok", False):
                return {}, {}, set()
            values = getattr(result, "value", None)
            if not isinstance(values, list):
                return {}, {}, set()
            importance: dict[str, float] = {}
            emotions: dict[str, float] = {}
            gist: set[str] = set()
            for m in values:
                try:
                    key = m.key
                    importance[key] = max(0.0, min(1.0, float(m.importance)))
                    emotions[key] = max(0.0, min(1.0, float(getattr(m, "emotion_intensity", 0.0) or 0.0)))
                    if getattr(m, "kind", "") == "semantic" and getattr(m, "source_type", "") == "consolidated":
                        gist.add(key)
                except (TypeError, ValueError, AttributeError):
                    continue
            return importance, emotions, gist
        except Exception:
            logger.warning(
                "_batch_memory_info: memory_repo.find_all failed, skipping decay batch",
                exc_info=True,
            )
            return {}, {}, set()

    def _resolve_lambda_k(self) -> float:
        """Resolve importance-λ factor k (default 0.5); non-numeric config → default."""
        candidates = []
        if self._config is not None:
            candidates.append(getattr(self._config, "importance_lambda_k", None))
        candidates.append(getattr(getattr(self.context.settings, "forgetting", None), "importance_lambda_k", None))
        for c in candidates:
            if isinstance(c, bool):
                continue
            if isinstance(c, (int, float)) and c >= 0:
                return float(c)
        return 0.5

    # audit H5 (v4.0) one-shot migration: legacy rows whose stability was
    # inflated by the removed emotion gain (×1.5 per emotional recall) are
    # clamped to the emotion-free init default (1.0) when enabled. The clamp
    # is idempotent; LTM rows are exempt (their stability comes from
    # promotion, not emotion). Gated behind
    # SessionConfig.h5_stability_clamp_enabled (default False) — the v4.0
    # migration script (scripts/migrate_h5_clamp.py) enables/runs it once in
    # production; unit tests seed stability directly and must not be clamped.
    def _h5_stability_clamp_once(self) -> None:
        """Clamp legacy emotion-inflated stability once (audit H5 migration)."""
        if getattr(self._config, "h5_stability_clamp_enabled", False) is not True:
            return
        try:
            result = self.context.memory_repo.get_all_strengths()
            if not result.is_ok:
                return
            clamped = 0
            for strength in result.value:
                if strength.is_ltm or strength.stability <= 1.0:
                    continue
                strength.stability = 1.0
                self.context.memory_repo.save_strength(strength)
                clamped += 1
            if clamped:
                logger.info("H5 migration: clamped emotion-inflated stability on %d rows", clamped)
        except Exception:
            logger.warning("H5 stability clamp failed", exc_info=True)

    def _decay_cycle(self) -> None:
        """Run one decay cycle: update all memory strengths."""
        self._h5_stability_clamp_once()
        result = self.context.memory_repo.get_all_strengths()
        if not result.is_ok:
            return

        now = get_now()
        strengths = result.value
        logger.debug("Decay cycle started, checking %d strengths", len(strengths))

        # Batch-resolve real memory importance once (no N+1 per strength)
        importance_by_key, emotion_by_key, gist_keys = self._batch_memory_info()
        lambda_k = self._resolve_lambda_k()

        processed = 0
        updated = 0
        skipped = 0
        errors = 0
        for strength in strengths:
            processed += 1
            memory_key = strength.memory_key
            old_strength_val = strength.strength

            # Gist transformation resists decay: consolidated semantic nodes
            # are the stable cortical summary and never decay here.
            if memory_key in gist_keys:
                skipped += 1
                continue

            elapsed = (now - strength.last_decay).total_seconds() / 3600 if strength.last_decay else 24.0

            importance = importance_by_key.get(memory_key, 0.5)
            # LTM uses slower decay exponent; importance scales it down (T1)
            base_exp = 0.3 if strength.is_ltm else 0.5
            decay_exp = importance_scaled_exponent(base_exp, importance, k=lambda_k)
            recall = strength.compute_recall(elapsed, decay_exponent=decay_exp)
            score = strength.compute_strength_score(importance=importance)
            new_strength_val = recall * score

            # Emotion eases decay (McGaugh 2004): decay amount is scaled by
            # 1/(1 + 0.5 * emotion_intensity) — factor range 1.0–0.5, fixed
            # internal coefficient (distinct from lane2's brain_emotion_gain_k).
            emotion = emotion_by_key.get(memory_key, 0.0)
            ease = 1.0 / (1.0 + 0.5 * emotion)
            decay_amount = max(0.0, strength.strength - new_strength_val)
            new_strength_val = strength.strength - decay_amount * ease

            # STM → LTM automatic promotion (before min_strength check)
            promoted = False
            if not strength.is_ltm and new_strength_val > 0.7 and strength.recall_count >= 3:
                strength.is_ltm = True
                promoted = True

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
                # Stability-type replay pulse — success-only emit (wiring
                # convention), gated by visibility: fire only on LTM promotion
                # or a notable strength change so per-cycle micro-decay does
                # not flood the 200-slot ring buffer.
                delta = abs(strength.strength - old_strength_val)
                if promoted or delta > 0.05:
                    try:
                        wiring_events.emit(
                            "replay_fire",
                            source=memory_key,
                            weight=strength.strength,
                            meta={"persona": wiring_events.repo_persona(self.context.memory_repo)},
                        )
                    except Exception:
                        logger.debug("wiring emit failed", exc_info=True)
            else:
                errors += 1

        logger.info(
            "Decay cycle done: %d processed / %d updated / %d skipped / %d errors",
            processed,
            updated,
            skipped,
            errors,
        )

        # Hebbian link decay: links idle >7 days drift toward the 0.5 floor
        # (never below — persistent weight must stay ≥ the co-occurrence base).
        try:
            from datetime import timedelta

            from nous.domain.shared.time_utils import format_iso

            cutoff = format_iso(now - timedelta(days=7))
            self.context.entity_repo.decay_stale_links(cutoff)
        except Exception:
            logger.warning("Hebbian link decay failed", exc_info=True)

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
                logger.info(
                    "DecayWorker: reflection produced %d insights for %s",
                    len(results),
                    persona,
                )
                self._record_reflection_event(persona, results)
        except Exception as exc:
            logger.warning("DecayWorker: reflection failed: %s", exc)

    def _record_reflection_event(self, persona: str, results: list[dict[str, Any]]) -> None:
        """Record a ``brain.reflection`` session event for a successful periodic run.

        Trigger 時刻の保存先は legacy のメタ記憶（``_reflection_meta``）から session_events
        へ移行した。実行間隔の制御は REFLECTION_INTERVAL サイクルカウントが担い、
        ここは実行事実の記録のみ（brain.monologue / brain.introspection と同型）。
        """
        repo = getattr(self.context, "_session_event_repo", None)
        if repo is None:
            return
        try:
            repo.insert(
                SessionEvent(
                    session_id="unknown",
                    persona=persona,
                    event_type="brain.reflection",
                    summary=f"定期リフレクション: {len(results)} insights",
                    timestamp=get_now(),
                    metadata={"insights": len(results)},
                )
            )
        except Exception:
            logger.debug("DecayWorker: reflection event insert failed", exc_info=True)
