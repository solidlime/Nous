from __future__ import annotations

import contextlib
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from nous.domain.memory.entities import Memory
    from nous.domain.memory.repository import MemoryRepository

from nous.domain.value_objects import normalize_importance

logger = logging.getLogger(__name__)


class MemoryEnrichService:
    """Handles memory enrichment via Sudachi NER and LLM-based evaluation."""

    def __init__(
        self,
        enricher: object | None,
        entity_service: object | None,
        repo: MemoryRepository,
    ) -> None:
        self._enricher = enricher
        self._entity_service = entity_service
        self._repo = repo

    async def enrich_memory(
        self,
        memory: Memory,
        content: str,
        type_hints: list[str] | None,
        key: str,
        importance: float,
    ) -> None:
        """Run enrichment pipeline on a newly created memory (best-effort).

        Steps:
        1. Extract entities via Sudachi NER
        2. Call LLM enricher for auto-evaluation
        3. Update importance if different from default
        4. Register extracted relations
        """
        if self._enricher is not None and importance == 0.5:
            try:
                # Extract entities using Sudachi NER (accurate path) for LLM context.
                from nous.domain.memory.sudachi_extractor import (
                    SudachiExtractor,
                )

                sudachi = SudachiExtractor()
                accurate = sudachi.extract(content.strip())
                # Convert list[dict] with keys {name, type, start, end} → list[tuple[str, str]]
                extracted_entities = [(e["name"], e["type"]) for e in accurate]
                enrichment = await self._enricher.enrich_async(
                    content=content.strip(),
                    type_tags=type_hints or [],
                    entities=extracted_entities,
                )
                if enrichment is not None:
                    from nous.domain.memory.wiring_events import (
                        emit as _wiring_emit,
                    )
                    from nous.domain.memory.wiring_events import (
                        repo_persona as _repo_persona,
                    )

                    persona = _repo_persona(self._repo)
                    usage = getattr(enrichment, "usage", None)
                    if usage:
                        logger.info(
                            "enrichment usage for %s: %s",
                            key,
                            usage,
                        )
                    usage_meta = {"persona": persona, "memory_key": key, "usage": usage}
                    # Update importance if auto-evaluated differently
                    if enrichment.importance != 0.5:
                        clamped = normalize_importance(enrichment.importance)
                        memory.importance = clamped
                        with contextlib.suppress(Exception):
                            self._repo.update(key, importance=clamped)

                    # Register auto-extracted relations
                    if enrichment.relations and self._entity_service is not None:
                        for rel in enrichment.relations:
                            ok = False
                            with contextlib.suppress(Exception):
                                self._entity_service.add_relation(
                                    source=rel.source_entity,
                                    target=rel.target_entity,
                                    relation_type=rel.relation_type,
                                    memory_key=key,
                                    confidence=rel.confidence,
                                )
                                ok = True
                            # Offline reactivation pulse — one per registered
                            # relation; importance-only path fires below.
                            if ok:
                                try:
                                    _wiring_emit(
                                        "replay_fire",
                                        source=rel.source_entity,
                                        target=rel.target_entity,
                                        weight=rel.confidence,
                                        meta=usage_meta,
                                    )
                                except Exception:
                                    logger.debug(
                                        "wiring emit failed for %s->%s",
                                        rel.source_entity,
                                        rel.target_entity,
                                        exc_info=True,
                                    )
                    elif enrichment.importance != 0.5:
                        clamped = normalize_importance(enrichment.importance)
                        try:
                            _wiring_emit(
                                "replay_fire",
                                source=key,
                                weight=clamped,
                                meta=usage_meta,
                            )
                        except Exception:
                            logger.debug("wiring emit failed for %s", key, exc_info=True)
            except Exception as exc:
                logger.debug("enrich failed: %s", exc)
