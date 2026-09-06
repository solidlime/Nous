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


def test_get_client_rebuilds_client_from_dead_loop():
    """Client created on a dead (temporary) event loop is rebuilt in the current loop."""
    mgr = QdrantClientManager(url="http://localhost:6333")

    async def connect():
        return await mgr.connect()

    async def get():
        client = await mgr.get_client()
        return client, asyncio.get_running_loop()

    loop1 = asyncio.new_event_loop()
    try:
        c1 = loop1.run_until_complete(connect())
    finally:
        loop1.close()

    loop2 = asyncio.new_event_loop()
    try:
        c2, running = loop2.run_until_complete(get())
    finally:
        loop2.close()

    assert c2 is not c1
    assert mgr._client is c2
    assert mgr._loop is running
