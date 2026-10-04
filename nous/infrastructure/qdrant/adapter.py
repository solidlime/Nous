from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from typing import TYPE_CHECKING, cast

import numpy as np

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

    def embedding_fingerprint(self, content: str) -> str:
        """sha256(model_name + content) — 再 encode 要否の判定に使う。

        モデル名を混ぜることでモデル変更→全再計算、テキスト変更→差分再計算になる。
        """
        model_name = getattr(getattr(self.embedding, "config", None), "model", "") or ""
        return hashlib.sha256(f"{model_name}\x1f{content}".encode()).hexdigest()

    # ------------------------------------------------------------------
    # Async API (all methods are async, using AsyncQdrantClient)
    # ------------------------------------------------------------------

    async def ensure_collection(self, persona: str) -> Result[None, VectorStoreError]:
        """Create the Qdrant collection for a persona if it does not exist."""
        name = self.collection_name(persona)
        try:
            from qdrant_client.models import Distance, VectorParams

            client = await self.client_manager.get_client()
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
        """Embed and upsert a memory into the vector store.

        fingerprint が同一の既存 point は再 encode しない（ASIST fingerprint 方式）。
        旧 point（fingerprint 無し）は同一内容なら encode 済みとみなし、payload に
        fingerprint を付けるだけにする。判定に使う retrieve が失敗した場合は
        fail-open（再 encode）で従来挙動に落ちる。
        """
        try:
            from qdrant_client.models import PointStruct

            client = await self.client_manager.get_client()
            name = self.collection_name(persona)
            point_id = self._key_to_id(key)
            fingerprint = self.embedding_fingerprint(content)

            existing = await self._fetch_payload(client, name, point_id)
            if existing is not None and existing.get("content") == content:
                prev = existing.get("embedding_fingerprint")
                if prev is None:
                    # 旧 point: 既に embed 済みなので payload だけ更新（再 encode しない）。
                    await client.set_payload(
                        collection_name=name,
                        payload={"embedding_fingerprint": fingerprint},
                        points=[point_id],
                    )
                    logger.info("Backfilled embedding_fingerprint for key: %s", key)
                    return Success(None)
                if prev == fingerprint:
                    logger.debug("Skipped re-encode (fingerprint unchanged): %s", key)
                    return Success(None)

            vector = await self.embedding.async_encode(content, is_query=False)
            payload: dict = {
                "key": key,
                "content": content,
                "embedding_fingerprint": fingerprint,
                "lifecycle_status": lifecycle_status,
                "created_at": datetime.now(UTC).isoformat(),
            }
            if metadata:
                payload.update(metadata)

            point = PointStruct(
                id=point_id,
                vector=vector.tolist(),
                payload=payload,
            )
            await client.upsert(
                collection_name=name,
                points=[point],
            )
            logger.info("Upserted vector for key: %s", key)
            return Success(None)
        except Exception as e:
            logger.error("Failed to upsert vector for %s: %s", key, e)
            return Failure(VectorStoreError(str(e)))

    async def _fetch_payload(self, client, collection: str, point_id: str) -> dict | None:
        """既存 point の payload を取る（無し = 空 dict、取得失敗 = None）。"""
        try:
            records = await client.retrieve(
                collection_name=collection,
                ids=[point_id],
                with_payload=True,
                with_vectors=False,
            )
            return dict(records[0].payload or {}) if records else {}
        except Exception as e:
            logger.debug("Fingerprint lookup failed for %s (re-encode): %s", point_id, e)
            return None

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
            client = await self.client_manager.get_client()
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
            client = await self.client_manager.get_client()
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
                            payload={
                                "key": key,
                                "content": content,
                                "embedding_fingerprint": self.embedding_fingerprint(content),
                            },
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

    async def retrieve_vectors(self, persona: str, keys: list[str]) -> Result[dict[str, np.ndarray], VectorStoreError]:
        """Fetch stored vectors by memory keys in ONE batch (no re-encode).

        Returns ``{memory_key: vector}`` for points that exist in Qdrant.
        Keys without a point are simply absent from the mapping — callers
        treat them as cosine-less (SQLite-only memories).
        """
        if not keys:
            return Success({})
        try:
            client = await self.client_manager.get_client()
            ids = [self._key_to_id(k) for k in keys]
            records = await client.retrieve(
                collection_name=self.collection_name(persona),
                ids=ids,
                with_payload=True,
                with_vectors=True,
            )
            vectors: dict[str, np.ndarray] = {}
            for rec in records:
                key = (rec.payload or {}).get("key", "")
                # qdrant の型定義上 vector は宽い union だが、upsert は list[float] のみ書く
                vec = cast("list[float]", rec.vector)
                if key and vec is not None:
                    vectors[key] = np.asarray(vec, dtype=float)
            return Success(vectors)
        except Exception as e:
            logger.error("Failed to retrieve vectors for '%s' (%d keys): %s", persona, len(keys), e)
            return Failure(VectorStoreError(str(e)))

    async def delete(self, persona: str, key: str) -> Result[None, VectorStoreError]:
        """Delete a point from the vector store."""
        try:
            from qdrant_client.models import PointIdsList

            await (await self.client_manager.get_client()).delete(
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
            info = await (await self.client_manager.get_client()).get_collection(
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
                await (await self.client_manager.get_client()).delete_collection(name)
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
