"""Task 5: QdrantClientManager.reconnect is serialized via asyncio.Lock."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from nous.infrastructure.qdrant.client import QdrantClientManager


@pytest.mark.asyncio
async def test_reconnect_holds_lock_during_swap():
    """reconnect() must hold _lock while swapping the client (docstring contract)."""
    mgr = QdrantClientManager(url="http://x:6333")
    release = asyncio.Event()

    class FakeClient:
        async def get_collections(self):
            await release.wait()
            return SimpleNamespace(collections=[])

        async def close(self):
            pass

    with patch("qdrant_client.AsyncQdrantClient", return_value=FakeClient()):
        task = asyncio.create_task(mgr.reconnect(new_url="http://y:6333"))
        await asyncio.sleep(0.05)
        try:
            assert mgr._lock.locked()
        finally:
            release.set()
            result = await task
    assert result["status"] == "connected"
    assert mgr.url == "http://y:6333"
