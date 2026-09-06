"""Enrichment domain models for memory importance and entity relation extraction."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class RelationCandidate:
    """A candidate relation extracted from memory content."""

    source_entity: str
    target_entity: str
    relation_type: str
    confidence: float = 1.0


@dataclass
class EnrichmentResult:
    """Result of enriching a memory via LLM."""

    importance: float
    relations: list[RelationCandidate] = field(default_factory=list)
    usage: dict | None = None  # token usage from DoneEvent.usage; None when unavailable
