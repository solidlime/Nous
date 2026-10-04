"""Qdrant payload の embedding_fingerprint による再 encode 排除の unit test。

fingerprint = sha256(model_name + content)。モデル名を混ぜることでモデル変更→
全再計算、テキスト変更→差分再計算になる。旧 point（fingerprint 無し）は
同一内容なら encode 済みとみなして payload を backfill するだけにする。
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import numpy as np
import pytest

from nous.infrastructure.qdrant.adapter import QdrantVectorStore


class _FakeClient:
    def __init__(self, existing: dict | None):
        self.existing = existing
        self.upserted: list = []
        self.payloads: list = []

    async def retrieve(self, collection_name, ids, with_payload=True, with_vectors=False):
        if self.existing is None:
            return []
        return [SimpleNamespace(payload=dict(self.existing), id=ids[0])]

    async def upsert(self, collection_name, points):
        self.upserted.extend(points)

    async def set_payload(self, collection_name, payload, points):
        self.payloads.append(payload)


def _store(existing: dict | None, model: str = "onnx-community/ruri-v3-30m-ONNX"):
    client = _FakeClient(existing)
    mgr = MagicMock()
    mgr.get_client = AsyncMock(return_value=client)
    embedding = MagicMock()
    embedding.config = SimpleNamespace(model=model)
    embedding.async_encode = AsyncMock(return_value=np.array([0.1, 0.2]))
    return QdrantVectorStore(mgr, embedding, "memory_"), client, embedding


def _payload(content: str, fingerprint: str | None, model: str = "onnx-community/ruri-v3-30m-ONNX") -> dict:
    import hashlib

    p = {"key": "k1", "content": content}
    if fingerprint == "<match>":
        p["embedding_fingerprint"] = hashlib.sha256(f"{model}\x1f{content}".encode()).hexdigest()
    elif fingerprint is not None:
        p["embedding_fingerprint"] = fingerprint
    return p


@pytest.mark.asyncio
async def test_fingerprint_match_skips_encode():
    store, client, embedding = _store(_payload("hello", "<match>"))
    result = await store.upsert("p", "k1", "hello")
    assert result.is_ok
    embedding.async_encode.assert_not_awaited()
    assert client.upserted == []


@pytest.mark.asyncio
async def test_content_change_reencodes():
    store, client, embedding = _store(_payload("old", "<match>"))
    result = await store.upsert("p", "k1", "new")
    assert result.is_ok
    embedding.async_encode.assert_awaited_once()
    assert client.upserted[0].payload["embedding_fingerprint"] == store.embedding_fingerprint("new")


@pytest.mark.asyncio
async def test_model_change_reencodes():
    store, client, embedding = _store(_payload("hello", "<match>"))
    # 別モデルの fingerprint と一致しない = モデル変更による全再計算
    embedding.config.model = "other/model"
    result = await store.upsert("p", "k1", "hello")
    assert result.is_ok
    embedding.async_encode.assert_awaited_once()


@pytest.mark.asyncio
async def test_legacy_point_backfills_fingerprint_without_encode():
    """fingerprint 無し + 同一内容 → 再 encode せず payload だけ backfill。"""
    store, client, embedding = _store(_payload("hello", None))
    result = await store.upsert("p", "k1", "hello")
    assert result.is_ok
    embedding.async_encode.assert_not_awaited()
    assert client.payloads == [{"embedding_fingerprint": store.embedding_fingerprint("hello")}]


@pytest.mark.asyncio
async def test_missing_point_encodes():
    store, client, embedding = _store(None)
    result = await store.upsert("p", "k1", "hello")
    assert result.is_ok
    embedding.async_encode.assert_awaited_once()
    assert client.upserted[0].payload["embedding_fingerprint"] == store.embedding_fingerprint("hello")


@pytest.mark.asyncio
async def test_lookup_failure_fails_open_to_encode():
    """retrieve 失敗時は再 encode にフォールバック（従来挙動）。"""
    store, client, embedding = _store(None)

    async def _boom(*a, **kw):
        raise RuntimeError("qdrant down")

    client.retrieve = _boom
    result = await store.upsert("p", "k1", "hello")
    assert result.is_ok
    embedding.async_encode.assert_awaited_once()


@pytest.mark.asyncio
async def test_batch_upsert_stores_fingerprint():
    store, client, embedding = _store(None)
    embedding.async_encode_batch = AsyncMock(return_value=np.array([[0.1], [0.2]]))
    result = await store.upsert_batch("p", [("k1", "a"), ("k2", "b")])
    assert result.is_ok
    assert [pt.payload["embedding_fingerprint"] for pt in client.upserted] == [
        store.embedding_fingerprint("a"),
        store.embedding_fingerprint("b"),
    ]
