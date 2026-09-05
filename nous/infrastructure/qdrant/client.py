from __future__ import annotations

import asyncio
import contextlib
from typing import TYPE_CHECKING

from nous.infrastructure.logging.structured import get_logger

if TYPE_CHECKING:
    from qdrant_client import AsyncQdrantClient

logger = get_logger(__name__)


class QdrantClientManager:
    """Manages Qdrant client lifecycle with async-first API."""

    def __init__(self, url: str = "http://localhost:6333", api_key: str | None = None) -> None:
        self.url = url
        self.api_key = api_key
        self._client: AsyncQdrantClient | None = None
        self._lock = asyncio.Lock()

    @property
    def client(self) -> AsyncQdrantClient:
        """Get the connected client. Raises RuntimeError if not connected."""
        if self._client is None:
            msg = "Client not connected. Call await connect() first."
            raise RuntimeError(msg)
        return self._client

    async def connect(self) -> AsyncQdrantClient:
        """Lazily connect to Qdrant (thread-safe via asyncio.Lock)."""
        async with self._lock:
            return await self._connect_locked()

    async def _connect_locked(self) -> AsyncQdrantClient:
        """Create the client if absent. Caller must hold _lock (non-reentrant)."""
        if self._client is None:
            from qdrant_client import AsyncQdrantClient

            self._client = AsyncQdrantClient(
                url=self.url,
                api_key=self.api_key,
                timeout=30,
            )
            logger.info("Qdrant client connected to %s", self.url)
        return self._client

    async def close(self) -> None:
        """Close the Qdrant client connection."""
        async with self._lock:
            if self._client is not None:
                try:
                    await self._client.close()
                except Exception as e:
                    logger.warning("Error closing Qdrant client: %s", e)
                finally:
                    self._client = None

    async def health_check(self) -> bool:
        """Check if Qdrant is reachable (async)."""
        try:
            client = await self.connect()
            await client.get_collections()
            return True
        except Exception as e:
            logger.warning("Qdrant health check failed: %s", e)
            return False

    async def reconnect(
        self,
        new_url: str | None = None,
        new_api_key: str | None = None,
    ) -> dict:
        """Reconnect the client (thread-safe via asyncio.Lock)."""
        async with self._lock:
            old_client = self._client
            old_url = self.url
            old_api_key = self.api_key

            if new_url:
                self.url = new_url
            if new_api_key is not None:
                self.api_key = new_api_key

            self._client = None

            try:
                client = await self._connect_locked()
                collections = await client.get_collections()
                # Close old client
                if old_client is not None:
                    with contextlib.suppress(Exception):
                        await old_client.close()
                logger.info("Qdrant reconnected to %s", self.url)
                return {
                    "status": "connected",
                    "url": self.url,
                    "collections": len(collections.collections),
                    "message": f"Connected to {self.url}",
                }
            except Exception as e:
                logger.error("Failed to reconnect to Qdrant: %s", e)
                # Fallback: restore old client
                self._client = old_client
                self.url = old_url
                self.api_key = old_api_key
                return {
                    "status": "error",
                    "url": self.url,
                    "collections": 0,
                    "message": f"Reconnect failed, reverted: {e}",
                }

    async def get_connection_status(self) -> dict:
        """Return connection status."""
        if self._client is None:
            return {"status": "disconnected", "url": self.url, "collections": []}
        try:
            collections = await self._client.get_collections()
            return {
                "status": "connected",
                "url": self.url,
                "collections": [c.name for c in collections.collections],
            }
        except Exception:
            return {"status": "disconnected", "url": self.url, "collections": []}
