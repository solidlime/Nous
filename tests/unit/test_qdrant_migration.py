"""起動時の埋め込みマイグレーション / 次元照合 / fingerprint 次元の unit test。

背景: ba00515e で埋め込みモデルを 30m→70m(MRL 256) に変更。旧 point は旧空間の
ベクトルを保持したままなので、再 upsert されるまで検索スコアが無意味になる。
本テストは (1) ensure_collection の次元照合、(2) fingerprint の dimensions 包含、
(3) reencode_stale の差分再エンコードと中断→再開耐性 をモックで検証する。
"""

from __future__ import annotations

import hashlib
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import numpy as np
import pytest

from nous.infrastructure.qdrant.adapter import QdrantVectorStore


class _FakeQdrant:
    """scroll/upsert/get_collection を in-memory で再現する最小モック。

    upsert された payload を store に反映するので、再実行時に既エンコード point が
    再送されないことを検証できる（= 中断→再開の冪等性）。
    """

    def __init__(self, points: list[dict]) -> None:
        self.store: dict[str, dict] = {p["id"]: dict(p["payload"]) for p in points}
        self.upserted_batches: list[list] = []
        self.upsert_calls = 0
        self.raise_on_upsert_call: int | None = None

    async def scroll(self, collection_name, limit=10, offset=None, with_payload=True, with_vectors=False):
        ids = list(self.store)
        start = 0 if offset is None else offset
        page = ids[start : start + limit]
        recs = [SimpleNamespace(id=i, payload=dict(self.store[i])) for i in page]
        nxt = start + limit if start + limit < len(ids) else None
        return recs, nxt

    async def get_collection(self, collection_name):
        return SimpleNamespace(points_count=len(self.store))

    async def upsert(self, collection_name, points):
        self.upsert_calls += 1
        if self.raise_on_upsert_call == self.upsert_calls:
            raise RuntimeError("qdrant interrupted")
        for pt in points:
            self.store[pt.id] = dict(pt.payload)
        self.upserted_batches.append(points)


def _store(
    points: list[dict],
    *,
    model: str = "mochiya98/ruri-v3-70m-onnx",
    dimensions: int = 256,
):
    client = _FakeQdrant(points)
    mgr = MagicMock()
    mgr.get_client = AsyncMock(return_value=client)
    embedding = MagicMock()
    embedding.config = SimpleNamespace(model=model, dimensions=dimensions)
    embedding.async_encode_batch = AsyncMock(
        side_effect=lambda texts, is_query=False: np.array([[float(i + 1)] for i in range(len(texts))]),
    )
    return QdrantVectorStore(mgr, embedding, "memory_"), client, embedding


def _point(pid: str, content: str, fingerprint: str) -> dict:
    return {"id": pid, "payload": {"key": pid, "content": content, "embedding_fingerprint": fingerprint}}


# ---------------------------------------------------------------------------
# 2. ensure_collection の次元照合
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ensure_collection_fails_on_dimension_mismatch():
    """既存コレクション次元 != embedding.dimension なら無言で通さず失敗する。"""
    from qdrant_client.models import Distance, VectorParams

    from nous.domain.shared.result import Failure

    client = MagicMock()
    client.get_collections = AsyncMock(return_value=SimpleNamespace(collections=[SimpleNamespace(name="memory_p")]))
    client.get_collection = AsyncMock(
        return_value=SimpleNamespace(
            config=SimpleNamespace(params=SimpleNamespace(vectors=VectorParams(size=384, distance=Distance.COSINE))),
        ),
    )
    mgr = MagicMock()
    mgr.get_client = AsyncMock(return_value=client)
    embedding = MagicMock()
    embedding.async_dimension = AsyncMock(return_value=256)
    store = QdrantVectorStore(mgr, embedding, "memory_")

    result = await store.ensure_collection("p")

    assert isinstance(result, Failure)
    message = str(result.error)
    assert "384" in message
    assert "256" in message
    assert "rebuild" in message.lower()


@pytest.mark.asyncio
async def test_ensure_collection_passes_when_dimension_matches():
    from qdrant_client.models import Distance, VectorParams

    from nous.domain.shared.result import Success

    client = MagicMock()
    client.get_collections = AsyncMock(return_value=SimpleNamespace(collections=[SimpleNamespace(name="memory_p")]))
    client.get_collection = AsyncMock(
        return_value=SimpleNamespace(
            config=SimpleNamespace(params=SimpleNamespace(vectors=VectorParams(size=256, distance=Distance.COSINE))),
        ),
    )
    mgr = MagicMock()
    mgr.get_client = AsyncMock(return_value=client)
    embedding = MagicMock()
    embedding.async_dimension = AsyncMock(return_value=256)
    store = QdrantVectorStore(mgr, embedding, "memory_")

    result = await store.ensure_collection("p")
    assert isinstance(result, Success)


# ---------------------------------------------------------------------------
# 3. fingerprint に dimensions を含める
# ---------------------------------------------------------------------------


def test_fingerprint_changes_with_dimensions():
    store256, _, embedding = _store([], dimensions=256)
    fp256 = store256.embedding_fingerprint("hello")
    embedding.config.dimensions = 128
    fp128 = store256.embedding_fingerprint("hello")
    assert fp256 != fp128


# ---------------------------------------------------------------------------
# 1. reencode_stale — stale point だけ再エンコード
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reencode_stale_only_reencodes_stale_points():
    store, client, embedding = _store([])
    fresh = store.embedding_fingerprint("current text")
    stale = hashlib.sha256(b"onnx-community/ruri-v3-30m-ONNX\x1fNone\x1fcurrent text").hexdigest()
    client.store = {
        "k1": _point("k1", "current text", stale)["payload"],
        "k2": _point("k2", "current text", fresh)["payload"],
    }
    result = await store.reencode_stale("p", batch_size=32)

    assert result.is_ok
    assert result.value == 1
    assert {pt.id for batch in client.upserted_batches for pt in batch} == {"k1"}
    assert client.store["k1"]["embedding_fingerprint"] == store.embedding_fingerprint("current text")
    embedding.async_encode_batch.assert_awaited_once_with(["current text"], is_query=False)


@pytest.mark.asyncio
async def test_reencode_stale_noop_when_all_fresh():
    store, client, embedding = _store([])
    fp = store.embedding_fingerprint("t")
    client.store = {"k1": _point("k1", "t", fp)["payload"]}
    result = await store.reencode_stale("p")
    assert result.is_ok
    assert result.value == 0
    embedding.async_encode_batch.assert_not_awaited()


# ---------------------------------------------------------------------------
# 中断 → 再実行で残りが処理される
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reencode_stale_resumes_after_interruption():
    store, client, embedding = _store([])
    stale = hashlib.sha256(b"old-model\x1fNone\x1fc").hexdigest()
    client.store = {f"k{i}": _point(f"k{i}", f"c{i}", stale)["payload"] for i in range(4)}

    # 2 バッチ目で中断（batch_size=2 → 1 バッチ目適用後に失敗）
    client.raise_on_upsert_call = 2
    first = await store.reencode_stale("p", batch_size=2)
    assert not first.is_ok
    assert len(client.upserted_batches) == 1  # 部分適用は有効
    applied_first = {pt.id for pt in client.upserted_batches[0]}
    assert len(applied_first) == 2

    # 再実行: 残りだけ処理して完走
    client.raise_on_upsert_call = None
    embedding.async_encode_batch.reset_mock()
    second = await store.reencode_stale("p", batch_size=2)

    assert second.is_ok
    assert second.value == 2
    remaining = {f"k{i}" for i in range(4)} - applied_first
    assert {pt.id for pt in client.upserted_batches[1]} == remaining
    # 適用済み point は再エンコードされない
    called_texts = [t for call in embedding.async_encode_batch.await_args_list for t in call.args[0]]
    assert sorted(called_texts) == sorted(f"c{i}" for i in range(4) if f"k{i}" in remaining)
