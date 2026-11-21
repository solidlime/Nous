"""wiki vector_index の回帰テスト — 記憶ベクトル削除の collection prefix。

2026-11-21: ``async_drop_memories`` が空 prefix で存在しないコレクションを
叩いて 404 → SQLite 行は消えるのにベクトルだけ残る孤児化が発生した。
settings.qdrant.collection_prefix（既定 "memory_"）を使うことの保証。
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import TYPE_CHECKING, cast

import pytest

import nous.application.wiki.vector_index as vi

if TYPE_CHECKING:
    from nous.config.settings import Settings


class _FakeStore:
    instances: list[_FakeStore] = []

    def __init__(self, mgr, emb, prefix):
        self.prefix = prefix
        self.deleted: list[tuple[str, str]] = []
        _FakeStore.instances.append(self)

    async def delete(self, persona: str, key: str) -> None:
        self.deleted.append((persona, key))


class _FakeMgr:
    async def connect(self):
        return None

    async def health_check(self) -> bool:
        return True

    def close(self):
        return None


@pytest.fixture(autouse=True)
def _fake_qdrant(monkeypatch):
    import nous.application.use_cases as use_cases

    _FakeStore.instances = []
    monkeypatch.setattr(use_cases, "QdrantClientManager", lambda *_a, **_k: _FakeMgr())
    monkeypatch.setattr(use_cases, "QdrantVectorStore", _FakeStore)
    # _embedding は AppContextRegistry を舐める — このテストでは不要なので固定
    monkeypatch.setattr(vi, "_embedding", lambda _s: "fake-emb")
    yield


def _settings(prefix: str) -> Settings:
    # 動作に必要な qdrant 設定だけ持つ偽物（実 Settings の構築は環境変数依存）
    return cast(
        "Settings",
        SimpleNamespace(qdrant=SimpleNamespace(url="http://qdrant", api_key=None, collection_prefix=prefix)),
    )


@pytest.mark.asyncio
async def test_drop_memories_uses_memory_collection_prefix():
    """記憶ベクトル削除は settings.qdrant.collection_prefix のコレクションを叩く。"""
    await vi.async_drop_memories(_settings("memory_"), "herta", ["k1", "k2"])
    store = _FakeStore.instances[-1]
    assert store.prefix == "memory_"
    assert store.deleted == [("herta", "k1"), ("herta", "k2")]


@pytest.mark.asyncio
async def test_drop_memories_follows_configured_prefix():
    """prefix は設定次第 — ハードコードしない。"""
    await vi.async_drop_memories(_settings("vec_"), "herta", ["k1"])
    assert _FakeStore.instances[-1].prefix == "vec_"


@pytest.mark.asyncio
async def test_drop_memories_empty_keys_is_noop():
    await vi.async_drop_memories(_settings("memory_"), "herta", [])
    assert _FakeStore.instances == []


@pytest.mark.asyncio
async def test_drop_memories_unhealthy_qdrant_skips_delete():

    class _DownMgr(_FakeMgr):
        async def health_check(self) -> bool:
            return False

    before = len(_FakeStore.instances)
    import nous.application.use_cases as uc

    orig = uc.QdrantClientManager
    uc.QdrantClientManager = lambda *_a, **_k: _DownMgr()
    try:
        await vi.async_drop_memories(_settings("memory_"), "herta", ["k1"])
    finally:
        uc.QdrantClientManager = orig
    assert len(_FakeStore.instances) == before
