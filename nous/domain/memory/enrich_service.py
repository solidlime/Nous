from __future__ import annotations

import contextlib
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from nous.domain.memory.entities import Memory
    from nous.domain.memory.repository import MemoryRepository

from nous.domain.value_objects import normalize_importance


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
            with contextlib.suppress(Exception):
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
                    # Update importance if auto-evaluated differently
                    if enrichment.importance != 0.5:
                        clamped = normalize_importance(enrichment.importance)
                        memory.importance = clamped
                        with contextlib.suppress(Exception):
                            self._repo.update(key, importance=clamped)

                    # Register auto-extracted relations
                    if enrichment.relations and self._entity_service is not None:
                        for rel in enrichment.relations:
                            with contextlib.suppress(Exception):
                                self._entity_service.add_relation(
                                    source=rel.source_entity,
                                    target=rel.target_entity,
                                    relation_type=rel.relation_type,
                                    memory_key=key,
                                    confidence=rel.confidence,
                                )
