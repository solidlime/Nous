from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from nous.domain.shared.errors import VectorStoreError
from nous.domain.shared.result import Failure, Result, Success
from nous.infrastructure.logging.structured import get_logger

if TYPE_CHECKING:
    from nous.infrastructure.embedding.model import EmbeddingModel
    from nous.infrastructure.qdrant.client import QdrantClientManager

logger = get_logger(__name__)


class QdrantVectorStore:
    """Vector store adapter for memory search using Qdrant."""

    def __init__(
        self,
        client_manager: QdrantClientManager,
        embedding_model: EmbeddingModel,
        collection_prefix: str = "memory_",
    ) -> None:
        self.client_manager = client_manager
        self.embedding = embedding_model
        self.collection_prefix = collection_prefix

    def collection_name(self, persona: str) -> str:
        """Get the collection name for a persona."""
        return f"{self.collection_prefix}{persona}"

    # ------------------------------------------------------------------
    # Async API (all methods are async, using AsyncQdrantClient)
    # ------------------------------------------------------------------

    async def ensure_collection(self, persona: str) -> Result[None, VectorStoreError]:
        """Create the Qdrant collection for a persona if it does not exist."""
        name = self.collection_name(persona)
        try:
            from qdrant_client.models import Distance, VectorParams

            client = self.client_manager.client
            collections = (await client.get_collections()).collections
            if not any(c.name == name for c in collections):
                dim = await self.embedding.async_dimension()
                await client.create_collection(
                    collection_name=name,
                    vectors_config=VectorParams(
                        size=dim,
                        distance=Distance.COSINE,
                    ),
                )
                logger.info("Created Qdrant collection: %s", name)
            return Success(None)
        except Exception as e:
            err_str = str(e)
            if "No such file or directory" in err_str or "storage" in err_str.lower():
                logger.error(
                    "Failed to ensure collection %s: %s\n"
                    "HINT: Qdrant's storage directory is missing. "
                    "Run via `docker-compose up -d` so the ./data/qdrant volume is mounted, "
                    "or pre-create the storage directory before starting Qdrant standalone.",
                    name,
                    e,
                )
            else:
                logger.error("Failed to ensure collection %s: %s", name, e)
            return Failure(VectorStoreError(str(e)))

    async def upsert(
        self,
        persona: str,
        key: str,
        content: str,
        metadata: dict | None = None,
        lifecycle_status: str = "active",
    ) -> Result[None, VectorStoreError]:
        """Embed and upsert a memory into the vector store."""
        try:
            from qdrant_client.models import PointStruct

            vector = await self.embedding.async_encode(content, is_query=False)
            payload: dict = {
                "key": key,
                "content": content,
                "lifecycle_status": lifecycle_status,
                "created_at": datetime.now(UTC).isoformat(),
            }
            if metadata:
                payload.update(metadata)

            point = PointStruct(
                id=self._key_to_id(key),
                vector=vector.tolist(),
                payload=payload,
            )
            await self.client_manager.client.upsert(
                collection_name=self.collection_name(persona),
                points=[point],
            )
            logger.info("Upserted vector for key: %s", key)
            return Success(None)
        except Exception as e:
            logger.error("Failed to upsert vector for %s: %s", key, e)
            return Failure(VectorStoreError(str(e)))

    async def search(
        self,
        persona: str,
        query: str,
        limit: int = 10,
    ) -> Result[list[tuple[str, float]], VectorStoreError]:
        """Semantic search with pure vector similarity. Returns list of (memory_key, score)."""
        if not self.embedding.is_loaded:
            # Cold start: kick off a single background load (self-healing) and
            # fall back to keyword/FTS rather than blocking this request for
            # seconds. ensure_loaded_background() guards against thread storms.
            self.embedding.ensure_loaded_background()
            return Success([])
        try:
            vector = await self.embedding.async_encode(query, is_query=True)
            client = self.client_manager.client
            response = await client.query_points(
                collection_name=self.collection_name(persona),
                query=vector.tolist(),
                limit=limit,
            )
            results = response.points if response else []
            return Success(
                [
                    (r.payload.get("key", ""), r.score)  # type: ignore[union-attr]
                    for r in results
                    if r.payload
                ],
            )
        except Exception as e:
            logger.error("Failed to search vectors for '%s': %s", query, e)
            return Failure(VectorStoreError(str(e)))

    async def upsert_batch(
        self,
        persona: str,
        memories: list[tuple[str, str]],
        batch_size: int = 64,
    ) -> Result[int, VectorStoreError]:
        """Batch upsert multiple memories. Returns count of upserted points."""
        if not memories:
            return Success(0)
        try:
            from qdrant_client.models import PointStruct

            contents = [content for _, content in memories]
            vectors = await self.embedding.async_encode_batch(contents, is_query=False)
            client = self.client_manager.client
            total = 0
            for i in range(0, len(memories), batch_size):
                batch = memories[i : i + batch_size]
                batch_vectors = vectors[i : i + batch_size]
                points: list[PointStruct] = []
                for (key, content), vec in zip(batch, batch_vectors, strict=True):
                    points.append(
                        PointStruct(
                            id=self._key_to_id(key),
                            vector=vec.tolist(),
                            payload={"key": key, "content": content},
                        )
                    )
                await client.upsert(
                    collection_name=self.collection_name(persona),
                    points=points,
                )
                total += len(points)
            logger.info(
                "Batch upserted %d vectors for persona: %s",
                total,
                persona,
            )
            return Success(total)
        except Exception as e:
            logger.error("Failed to batch upsert for '%s': %s", persona, e)
            return Failure(VectorStoreError(str(e)))

    async def delete(self, persona: str, key: str) -> Result[None, VectorStoreError]:
        """Delete a point from the vector store."""
        try:
            from qdrant_client.models import PointIdsList

            await self.client_manager.client.delete(
                collection_name=self.collection_name(persona),
                points_selector=PointIdsList(points=[self._key_to_id(key)]),
            )
            logger.info("Deleted vector for key: %s", key)
            return Success(None)
        except Exception as e:
            logger.error("Failed to delete vector for %s: %s", key, e)
            return Failure(VectorStoreError(str(e)))

    async def count(self, persona: str) -> Result[int, VectorStoreError]:
        """Count points in the persona's collection."""
        try:
            info = await self.client_manager.client.get_collection(
                collection_name=self.collection_name(persona),
            )
            return Success(info.points_count or 0)
        except Exception as e:
            logger.error("Failed to count vectors for '%s': %s", persona, e)
            return Failure(VectorStoreError(str(e)))

    async def rebuild_collection(self, persona: str) -> Result[None, VectorStoreError]:
        """Delete and recreate collection for a persona."""
        name = self.collection_name(persona)
        try:
            try:
                await self.client_manager.client.delete_collection(name)
                logger.info("Deleted collection: %s", name)
            except Exception:
                logger.debug(
                    "Collection %s did not exist, skipping delete",
                    name,
                )
            return await self.ensure_collection(persona)
        except Exception as e:
            logger.error("Failed to rebuild collection '%s': %s", name, e)
            return Failure(VectorStoreError(str(e)))

    @staticmethod
    def _key_to_id(key: str) -> str:
        """Convert a memory key to a deterministic UUID-like hex string for Qdrant."""
        return hashlib.md5(key.encode(), usedforsecurity=False).hexdigest()

    async def reconnect(
        self,
        new_url: str | None = None,
        new_api_key: str | None = None,
    ) -> dict:
        """Reconnect the Qdrant client. Delegates to client_manager."""
        return await self.client_manager.reconnect(new_url=new_url, new_api_key=new_api_key)

    async def get_connection_status(self) -> dict:
        """Return connection status. Delegates to client_manager."""
        return await self.client_manager.get_connection_status()
