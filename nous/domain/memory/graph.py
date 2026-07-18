"""Lightweight entity graph domain model and service."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from nous.domain.memory.sudachi_extractor import HybridEntityExtractor
    from nous.domain.shared.errors import DomainError
    from nous.domain.shared.result import Result


@dataclass
class Entity:
    """A named entity extracted from memories."""

    id: str  # normalised name (lowercase, stripped)
    entity_type: str = "unknown"  # person / place / thing / concept / event
    first_seen: str = ""
    last_seen: str = ""
    mention_count: int = 1
    metadata: dict = field(default_factory=dict)


@dataclass
class EntityRelation:
    """A directional relation between two entities."""

    source_entity: str
    target_entity: str
    relation_type: str  # knows / owns / likes / dislikes / visited / created …
    memory_key: str | None = None
    confidence: float = 1.0
    created_at: str = ""


@dataclass
class EntityGraph:
    """An entity-centric sub-graph."""

    center: Entity
    relations: list[EntityRelation] = field(default_factory=list)
    related_entities: list[Entity] = field(default_factory=list)
    related_memories: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Repository protocol
# ---------------------------------------------------------------------------


@runtime_checkable
class EntityRepository(Protocol):
    """Persistence interface for the entity graph."""

    def save_entity(self, entity: Entity) -> Result[None, DomainError]: ...

    def get_entity(self, entity_id: str) -> Result[Entity | None, DomainError]: ...

    def find_entities(
        self, query: str, entity_type: str | None = None, limit: int = 20
    ) -> Result[list[Entity], DomainError]: ...

    def save_relation(self, relation: EntityRelation) -> Result[None, DomainError]: ...

    def get_relations(self, entity_id: str, direction: str = "both") -> Result[list[EntityRelation], DomainError]: ...

    def link_memory_entity(
        self, memory_key: str, entity_id: str, role: str = "mentioned"
    ) -> Result[None, DomainError]: ...

    def get_entity_memories(self, entity_id: str, limit: int = 50) -> Result[list[str], DomainError]: ...

    def get_memory_entities(self, memory_key: str) -> Result[list[Entity], DomainError]: ...

    def get_entity_graph(self, entity_id: str, depth: int = 1) -> Result[EntityGraph, DomainError]: ...


# ---------------------------------------------------------------------------
# Domain service
# ---------------------------------------------------------------------------


class EntityService:
    """Domain service orchestrating entity extraction and graph queries."""

    def __init__(
        self,
        entity_repo: EntityRepository,
        extractor: HybridEntityExtractor | None = None,
    ) -> None:
        self.repo = entity_repo
        if extractor is None:
            from nous.domain.memory.sudachi_extractor import (
                HybridEntityExtractor,
            )

            extractor = HybridEntityExtractor()
        self.extractor = extractor

    # -- write operations --------------------------------------------------

    def extract_and_link(
        self,
        memory_key: str,
        content: str,
        tags: list[str] | None = None,
    ) -> Result[list[Entity], DomainError]:
        """Extract entities from *content* and link them to *memory_key*."""
        from nous.domain.shared.errors import RepositoryError
        from nous.domain.shared.result import Failure, Success
        from nous.domain.shared.time_utils import format_iso, get_now

        try:
            raw = self.extractor.extract(content)
            # Also treat tags as potential entities
            if tags:
                for tag in tags:
                    tag_stripped = tag.strip()
                    if tag_stripped and len(tag_stripped) >= 2:
                        raw.append((tag_stripped, "concept"))

            now_str = format_iso(get_now())
            entities: list[Entity] = []
            seen_ids: set[str] = set()

            for name, etype in raw:
                eid = name.lower().strip()
                if not eid or eid in seen_ids:
                    continue
                seen_ids.add(eid)

                entity = Entity(
                    id=eid,
                    entity_type=etype,
                    first_seen=now_str,
                    last_seen=now_str,
                )
                save_result = self.repo.save_entity(entity)
                if not save_result.is_ok:
                    continue

                link_result = self.repo.link_memory_entity(memory_key, eid)
                if link_result.is_ok:
                    entities.append(entity)

            return Success(entities)
        except Exception as exc:
            return Failure(RepositoryError(str(exc)))

    def add_relation(
        self,
        source: str,
        target: str,
        relation_type: str,
        memory_key: str | None = None,
        confidence: float = 1.0,
    ) -> Result[None, DomainError]:
        """Explicitly add a relation between two entities."""
        from nous.domain.shared.errors import RepositoryError
        from nous.domain.shared.result import Failure
        from nous.domain.shared.time_utils import format_iso, get_now

        try:
            now_str = format_iso(get_now())
            # Ensure both entities exist
            for eid in (source.lower().strip(), target.lower().strip()):
                existing = self.repo.get_entity(eid)
                if existing.is_ok and existing.value is None:
                    self.repo.save_entity(
                        Entity(
                            id=eid,
                            first_seen=now_str,
                            last_seen=now_str,
                        )
                    )

            relation = EntityRelation(
                source_entity=source.lower().strip(),
                target_entity=target.lower().strip(),
                relation_type=relation_type,
                memory_key=memory_key,
                confidence=confidence,
                created_at=now_str,
            )
            return self.repo.save_relation(relation)
        except Exception as exc:
            return Failure(RepositoryError(str(exc)))

    # -- read operations ---------------------------------------------------

    def get_entity_graph(self, entity_id: str, depth: int = 1) -> Result[EntityGraph, DomainError]:
        """Retrieve the sub-graph centred on *entity_id*."""
        return self.repo.get_entity_graph(entity_id.lower().strip(), depth)

    def find_entities(
        self, query: str, entity_type: str | None = None, limit: int = 20
    ) -> Result[list[Entity], DomainError]:
        """Search entities by name pattern."""
        return self.repo.find_entities(query, entity_type, limit)

    def find_related_memories(self, entity_id: str, limit: int = 20) -> Result[list[str], DomainError]:
        """Return memory keys linked to *entity_id*."""
        return self.repo.get_entity_memories(entity_id.lower().strip(), limit)
