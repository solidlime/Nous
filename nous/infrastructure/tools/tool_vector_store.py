from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING

from qdrant_client.models import Distance, PointStruct, VectorParams

from nous.infrastructure.logging.structured import get_logger

if TYPE_CHECKING:
    from qdrant_client import AsyncQdrantClient

    from nous.infrastructure.embedding.model import EmbeddingModel

logger = get_logger(__name__)

COLLECTION_NAME = "tool_definitions"


class ToolVectorStore:
    """Qdrant wrapper for tool definition vector search."""

    def __init__(self, client: AsyncQdrantClient, embedding: EmbeddingModel) -> None:
        self._client = client
        self._embedding = embedding

    async def collection_exists(self) -> bool:
        """Check if the tool_definitions collection exists in Qdrant."""
        try:
            collections = (await self._client.get_collections()).collections
            return any(c.name == COLLECTION_NAME for c in collections)
        except Exception:
            return False

    async def ensure_collection(self) -> None:
        """Create collection if not exists."""
        if await self.collection_exists():
            logger.debug("ToolVectorStore: collection '%s' already exists", COLLECTION_NAME)
            return
        dim = await self._embedding.async_dimension()
        await self._client.create_collection(
            collection_name=COLLECTION_NAME,
            vectors_config=VectorParams(size=dim, distance=Distance.COSINE),
        )
        logger.info("ToolVectorStore: created collection '%s' (dim=%d)", COLLECTION_NAME, dim)

    @staticmethod
    def _key_to_id(key: str) -> str:
        return hashlib.md5(key.encode(), usedforsecurity=False).hexdigest()

    async def index_tools(self, tools: list) -> None:
        """Index tool definitions into Qdrant.

        Args:
            tools: list of ToolDefinition objects (name, description, input_schema)
        """
        points = []
        for t in tools:
            content = f"{t.name}\n{t.description}"
            vector = await self._embedding.async_encode(content, is_query=False)
            payload = {
                "tool_name": t.name,
                "description": t.description,
                "input_schema": t.input_schema,
            }
            point = PointStruct(
                id=self._key_to_id(t.name),
                vector=vector.tolist(),
                payload=payload,
            )
            points.append(point)

        if points:
            await self._client.upsert(collection_name=COLLECTION_NAME, points=points)
            logger.info("ToolVectorStore: indexed %d tools", len(points))

    async def search(self, query: str, limit: int = 10) -> list:
        """Semantic search for tools.

        Returns: list of (payload_dict, float_score)
        """
        vector = await self._embedding.async_encode(query, is_query=True)
        response = await self._client.query_points(
            collection_name=COLLECTION_NAME,
            query=vector.tolist(),
            limit=limit,
        )
        results = []
        for point in response.points:
            if point.payload:
                results.append((dict(point.payload), point.score))
        return results

    async def delete_all(self) -> None:
        """Delete all tool definitions (for reindexing)."""
        await self._client.delete_collection(collection_name=COLLECTION_NAME)
        await self.ensure_collection()
