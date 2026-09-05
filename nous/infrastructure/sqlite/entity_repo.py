"""SQLite-backed implementation of the EntityRepository protocol."""

from __future__ import annotations

import json

from nous.domain.memory.graph import Entity, EntityGraph, EntityRelation
from nous.domain.memory.memory_link import MemoryLink
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

    def upsert_link(
        self,
        source_key: str,
        target_key: str,
        link_type: str = "semantic",
        strength: float = 0.1,
        eta: float = 0.05,
    ) -> Result[None, RepositoryError]:
        """Atomically strengthen a Hebbian link (single-statement upsert).

        Oja-normalized update on conflict (T3): with y = current weight and
        coact = ``strength``,
        ``weight = MIN(1.0, MAX(0.5, w + η·c − η·w²·c))`` — self-normalizing,
        converges without pinning at 1.0 and never breaches the 0.5 floor.
        New edge starts at weight 0.5 + strength; co_activation_count bumps
        and last_activated refreshes. Read-modify-write is forbidden by
        design — the ON CONFLICT clause makes the update atomic.
        """
        try:
            now = format_iso(get_now())
            self._db.execute(
                """
                INSERT INTO memory_links (source_key, target_key, weight, link_type, co_activation_count, last_activated)
                VALUES (?, ?, 0.5 + ?, ?, 1, ?)
                ON CONFLICT(source_key, target_key, link_type) DO UPDATE SET
                    weight = MIN(1.0, MAX(0.5, weight + ? * ? - ? * weight * weight * ?)),
                    co_activation_count = co_activation_count + 1,
                    last_activated = ?
                """,
                (source_key, target_key, strength, link_type, now, eta, strength, eta, strength, now),
            )
            try:
                from nous.domain.memory.wiring_events import emit as _wiring_emit
                from nous.domain.memory.wiring_events import repo_persona as _repo_persona

                row = self._db.execute(
                    "SELECT weight FROM memory_links WHERE source_key = ? AND target_key = ? AND link_type = ?",
                    (source_key, target_key, link_type),
                ).fetchone()
                if row is not None:
                    _wiring_emit(
                        "link_fire",
                        source=source_key,
                        target=target_key,
                        weight=float(row["weight"]),
                        meta={"link_type": link_type, "coact": strength, "persona": _repo_persona(self)},
                    )
            except Exception:
                logger.debug("wiring emit failed for %s->%s", source_key, target_key, exc_info=True)
            return Success(None)
        except Exception as e:
            logger.error("Failed to upsert link %s->%s: %s", source_key, target_key, e)
            return Failure(RepositoryError(str(e)))

    def decay_stale_links(
        self,
        cutoff_iso: str,
        rate: float = 0.005,
        floor: float = 0.5,
    ) -> Result[int, RepositoryError]:
        """Decay weights of links idle since *cutoff_iso* (single UPDATE, no N+1).

        Invariant: persistent weight never drops below *floor* (0.5).  The
        union read in get_links_for_keys lets persistent weights override the
        co-occurrence base (0.5) — decaying below it would make decayed links
        WEAKER than plain co-occurrence, inverting the semantics.  Decay only
        differentiates within [floor, 1.0].
        """
        try:
            cursor = self._db.execute(
                "UPDATE memory_links SET weight = MAX(?, weight - ?) WHERE last_activated < ? AND weight > ?",
                (floor, rate, cutoff_iso, floor),
            )
            return Success(cursor.rowcount)
        except Exception as e:
            logger.error("Failed to decay stale links: %s", e)
            return Failure(RepositoryError(str(e)))

    def get_links_for_keys(self, keys: list[str], limit: int = 1000) -> list[MemoryLink]:
        """Return associative links for spreading activation.

        Union read: entity co-occurrence edges (weight=0.5) form the base
        graph; persistent memory_links edges (Hebbian) override same-pair
        co-occurrence weights and add pairs that share no entity.  Persistent
        edges are expanded in both directions (SA reads outgoing only).
        Day-1 behaviour is unchanged when memory_links is empty.
        """
        if not keys:
            return []
        links: dict[tuple[str, str], MemoryLink] = {}
        try:
            placeholders = ", ".join("?" for _ in keys)
            rows = self._db.execute(
                "SELECT DISTINCT me1.memory_key AS src, me2.memory_key AS dst "  # nosec B608 -- IN-list is "?" placeholders; values bound via sqlite params
                "FROM memory_entities me1 "
                "JOIN memory_entities me2 ON me1.entity_id = me2.entity_id "
                f"WHERE me1.memory_key IN ({placeholders}) AND me2.memory_key != me1.memory_key "
                "ORDER BY src, dst LIMIT ?",
                (*keys, limit),
            ).fetchall()
            for r in rows:
                links[(r["src"], r["dst"])] = MemoryLink(
                    source_key=r["src"], target_key=r["dst"], weight=0.5, link_type="semantic"
                )

            link_rows = self._db.execute(
                "SELECT * FROM memory_links "  # nosec B608 -- IN-list is "?" placeholders; values bound via sqlite params
                f"WHERE source_key IN ({placeholders}) OR target_key IN ({placeholders}) "
                "LIMIT ?",
                (*keys, *keys, limit),
            ).fetchall()
            for r in link_rows:
                for src, dst in ((r["source_key"], r["target_key"]), (r["target_key"], r["source_key"])):
                    # Persistent weight wins over the co-occurrence base
                    links[(src, dst)] = MemoryLink(
                        source_key=src,
                        target_key=dst,
                        weight=r["weight"],
                        link_type=r["link_type"],
                        co_activation_count=r["co_activation_count"],
                        last_activated=r["last_activated"],
                    )
            return list(links.values())[:limit]
        except Exception as e:
            logger.error("Failed to get links for %d keys: %s", len(keys), e)
            return []

    def get_entities_for_memories(self, memory_keys: list[str], limit: int = 50) -> list[dict]:
        """Return entities mentioned in the given memories, ordered by mention_count desc.

        Two-stage query so *limit* applies to distinct entities (top-N hubs),
        not raw rows. Each row carries ``memory_key`` so callers can build
        memory→entity edges; rows are restricted to the visible entity set.
        """
        if not memory_keys:
            return []
        try:
            placeholders = ", ".join("?" for _ in memory_keys)
            # Stage 1: pick distinct top-N entities by mention_count.
            id_rows = self._db.execute(
                "SELECT e.id FROM memory_entities me "  # nosec B608 -- IN-list is "?" placeholders; values bound via sqlite params
                "JOIN entities e ON e.id = me.entity_id "
                f"WHERE me.memory_key IN ({placeholders}) "
                "GROUP BY e.id ORDER BY MAX(e.mention_count) DESC, e.id LIMIT ?",
                (*memory_keys, limit),
            ).fetchall()
            ids = [r["id"] for r in id_rows]
            if not ids:
                return []
            # Stage 2: fetch memory_key-bearing rows for the visible set.
            id_placeholders = ", ".join("?" for _ in ids)
            rows = self._db.execute(
                "SELECT e.id, e.id AS label, e.entity_type AS type, e.mention_count, me.memory_key "  # nosec B608 -- IN-list is "?" placeholders; values bound via sqlite params
                "FROM memory_entities me "
                "JOIN entities e ON e.id = me.entity_id "
                f"WHERE me.entity_id IN ({id_placeholders}) "
                "ORDER BY e.mention_count DESC, e.id",
                (*ids,),
            ).fetchall()
            return [dict(r) for r in rows]
        except Exception as e:
            logger.error("Failed to get entities for %d memories: %s", len(memory_keys), e)
            return []

    def get_relations_between_entities(self, entity_ids: list[str]) -> list[dict]:
        """Return relations whose *both* endpoints are within *entity_ids*."""
        if not entity_ids:
            return []
        try:
            placeholders = ", ".join("?" for _ in entity_ids)
            rows = self._db.execute(
                "SELECT source_entity AS source_id, target_entity AS target_id, "  # nosec B608 -- IN-list is "?" placeholders; values bound via sqlite params
                "relation_type AS relation, confidence "
                f"FROM entity_relations WHERE source_entity IN ({placeholders}) "
                f"AND target_entity IN ({placeholders})",
                (*entity_ids, *entity_ids),
            ).fetchall()
            return [dict(r) for r in rows]
        except Exception as e:
            logger.error("Failed to get relations between %d entities: %s", len(entity_ids), e)
            return []

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
