"""SQLite-backed implementation of the EntityRepository protocol."""

from __future__ import annotations

import json

from nous.domain.memory.graph import Entity, EntityGraph, EntityRelation
from nous.domain.shared.errors import RepositoryError
from nous.domain.shared.result import Failure, Result, Success
from nous.domain.shared.time_utils import format_iso, get_now
from nous.infrastructure.logging.structured import get_logger
from nous.infrastructure.sqlite.base_repo import SQLiteRepository

logger = get_logger(__name__)


class SQLiteEntityRepository(SQLiteRepository):
    """SQLite-backed entity graph repository."""

    # ------------------------------------------------------------------
    # Entity CRUD
    # ------------------------------------------------------------------

    def save_entity(self, entity: Entity) -> Result[None, RepositoryError]:
        """Insert or update an entity (bump mention_count & last_seen)."""
        try:
            now = format_iso(get_now())
            metadata_json = json.dumps(entity.metadata, ensure_ascii=False) if entity.metadata else "{}"
            self._db.execute(
                """
                INSERT INTO entities (id, entity_type, first_seen, last_seen, mention_count, metadata)
                VALUES (?, ?, ?, ?, 1, ?)
                ON CONFLICT(id) DO UPDATE SET
                    last_seen = ?,
                    mention_count = mention_count + 1,
                    metadata = CASE WHEN excluded.metadata != '{}' THEN excluded.metadata ELSE entities.metadata END
                """,
                (
                    entity.id,
                    entity.entity_type,
                    entity.first_seen or now,
                    entity.last_seen or now,
                    metadata_json,
                    entity.last_seen or now,
                ),
            )
            return Success(None)
        except Exception as e:
            logger.error("Failed to save entity %s: %s", entity.id, e)
            return Failure(RepositoryError(str(e)))

    def get_entity(self, entity_id: str) -> Result[Entity | None, RepositoryError]:
        try:
            row = self._db.execute("SELECT * FROM entities WHERE id = ?", (entity_id,)).fetchone()
            if row is None:
                return Success(None)
            return Success(self._row_to_entity(row))
        except Exception as e:
            logger.error("Failed to get entity %s: %s", entity_id, e)
            return Failure(RepositoryError(str(e)))

    def find_entities(
        self, query: str, entity_type: str | None = None, limit: int = 20
    ) -> Result[list[Entity], RepositoryError]:
        try:
            if entity_type:
                rows = self._db.execute(
                    "SELECT * FROM entities WHERE id LIKE ? AND entity_type = ? ORDER BY mention_count DESC LIMIT ?",
                    (f"%{query}%", entity_type, limit),
                ).fetchall()
            else:
                rows = self._db.execute(
                    "SELECT * FROM entities WHERE id LIKE ? ORDER BY mention_count DESC LIMIT ?",
                    (f"%{query}%", limit),
                ).fetchall()
            return Success([self._row_to_entity(r) for r in rows])
        except Exception as e:
            logger.error("Failed to find entities for '%s': %s", query, e)
            return Failure(RepositoryError(str(e)))

    # ------------------------------------------------------------------
    # Relations
    # ------------------------------------------------------------------

    def save_relation(self, relation: EntityRelation) -> Result[None, RepositoryError]:
        try:
            now = format_iso(get_now())
            # Use empty string sentinel for NULL memory_key so UNIQUE constraint works
            memory_key = relation.memory_key or ""
            self._db.execute(
                """
                INSERT OR IGNORE INTO entity_relations
                    (source_entity, target_entity, relation_type, memory_key, confidence, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    relation.source_entity,
                    relation.target_entity,
                    relation.relation_type,
                    memory_key,
                    relation.confidence,
                    relation.created_at or now,
                ),
            )
            return Success(None)
        except Exception as e:
            logger.error("Failed to save relation %s->%s: %s", relation.source_entity, relation.target_entity, e)
            return Failure(RepositoryError(str(e)))

    def get_relations(self, entity_id: str, direction: str = "both") -> Result[list[EntityRelation], RepositoryError]:
        try:
            if direction == "outgoing":
                rows = self._db.execute(
                    "SELECT * FROM entity_relations WHERE source_entity = ?",
                    (entity_id,),
                ).fetchall()
            elif direction == "incoming":
                rows = self._db.execute(
                    "SELECT * FROM entity_relations WHERE target_entity = ?",
                    (entity_id,),
                ).fetchall()
            else:
                rows = self._db.execute(
                    "SELECT * FROM entity_relations WHERE source_entity = ? OR target_entity = ?",
                    (entity_id, entity_id),
                ).fetchall()
            return Success([self._row_to_relation(r) for r in rows])
        except Exception as e:
            logger.error("Failed to get relations for %s: %s", entity_id, e)
            return Failure(RepositoryError(str(e)))

    # ------------------------------------------------------------------
    # Memory ↔ Entity links
    # ------------------------------------------------------------------

    def link_memory_entity(
        self, memory_key: str, entity_id: str, role: str = "mentioned"
    ) -> Result[None, RepositoryError]:
        try:
            self._db.execute(
                "INSERT OR IGNORE INTO memory_entities (memory_key, entity_id, role) VALUES (?, ?, ?)",
                (memory_key, entity_id, role),
            )
            return Success(None)
        except Exception as e:
            logger.error("Failed to link memory %s → entity %s: %s", memory_key, entity_id, e)
            return Failure(RepositoryError(str(e)))

    def get_entity_memories(self, entity_id: str, limit: int = 50) -> Result[list[str], RepositoryError]:
        try:
            rows = self._db.execute(
                "SELECT memory_key FROM memory_entities WHERE entity_id = ? LIMIT ?",
                (entity_id, limit),
            ).fetchall()
            return Success([r["memory_key"] for r in rows])
        except Exception as e:
            logger.error("Failed to get memories for entity %s: %s", entity_id, e)
            return Failure(RepositoryError(str(e)))

    def get_memory_entities(self, memory_key: str) -> Result[list[Entity], RepositoryError]:
        try:
            rows = self._db.execute(
                """
                SELECT e.* FROM entities e
                JOIN memory_entities me ON e.id = me.entity_id
                WHERE me.memory_key = ?
                """,
                (memory_key,),
            ).fetchall()
            return Success([self._row_to_entity(r) for r in rows])
        except Exception as e:
            logger.error("Failed to get entities for memory %s: %s", memory_key, e)
            return Failure(RepositoryError(str(e)))

    # ------------------------------------------------------------------
    # Graph traversal
    # ------------------------------------------------------------------

    def get_entity_graph(self, entity_id: str, depth: int = 1) -> Result[EntityGraph, RepositoryError]:
        """Build a sub-graph centred on *entity_id* up to *depth* hops."""
        try:
            center_result = self.get_entity(entity_id)
            if not center_result.is_ok:
                return Failure(center_result.error)
            center = center_result.value
            if center is None:
                return Failure(RepositoryError(f"Entity not found: {entity_id}"))

            all_relations: list[EntityRelation] = []
            related_ids: set[str] = set()
            visited: set[str] = {entity_id}
            frontier: set[str] = {entity_id}

            for _ in range(depth):
                next_frontier: set[str] = set()
                for eid in frontier:
                    rels_result = self.get_relations(eid)
                    if not rels_result.is_ok:
                        continue
                    for rel in rels_result.value:
                        all_relations.append(rel)
                        for neighbour in (rel.source_entity, rel.target_entity):
                            if neighbour not in visited:
                                related_ids.add(neighbour)
                                next_frontier.add(neighbour)
                                visited.add(neighbour)
                frontier = next_frontier

            # Collect related entities
            related_entities: list[Entity] = []
            for rid in related_ids:
                ent_result = self.get_entity(rid)
                if ent_result.is_ok and ent_result.value is not None:
                    related_entities.append(ent_result.value)

            # Collect memory keys
            mem_result = self.get_entity_memories(entity_id)
            memories = mem_result.value if mem_result.is_ok else []

            return Success(
                EntityGraph(
                    center=center,
                    relations=all_relations,
                    related_entities=related_entities,
                    related_memories=memories,
                )
            )
        except Exception as e:
            logger.error("Failed to get entity graph for %s: %s", entity_id, e)
            return Failure(RepositoryError(str(e)))

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _row_to_entity(row) -> Entity:
        metadata = {}
        if row["metadata"]:
            import contextlib

            with contextlib.suppress(json.JSONDecodeError, TypeError):
                metadata = json.loads(row["metadata"])
        return Entity(
            id=row["id"],
            entity_type=row["entity_type"],
            first_seen=row["first_seen"],
            last_seen=row["last_seen"],
            mention_count=row["mention_count"],
            metadata=metadata,
        )

    @staticmethod
    def _row_to_relation(row) -> EntityRelation:
        memory_key = row["memory_key"]
        if memory_key == "":
            memory_key = None
        return EntityRelation(
            source_entity=row["source_entity"],
            target_entity=row["target_entity"],
            relation_type=row["relation_type"],
            memory_key=memory_key,
            confidence=row["confidence"],
            created_at=row["created_at"],
        )
