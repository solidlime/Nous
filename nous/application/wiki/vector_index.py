"""wiki ページのベクトル索引（Qdrant collection prefix ``wiki_``）への反映。

ファイル層（``WikiStore``）が正で、索引はミラー。索引更新の失敗はファイル層の
成否に影響させない（warning のみ）。編纂 worker（同期 thread）と HTTP ルータ
（非同期）の両方から使うため、同期ラッパと async 実体を分けている。
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from nous.infrastructure.logging.structured import get_logger

if TYPE_CHECKING:
    from nous.config.settings import Settings

logger = get_logger(__name__)


async def async_sync_page(settings: Settings, persona: str, slug: str, title: str, body: str) -> None:
    """1 ページを索引へ upsert する（失敗は warning）。"""
    from nous.application import use_cases

    mgr = use_cases.QdrantClientManager(settings.qdrant.url, settings.qdrant.api_key)
    try:
        await mgr.connect()
        if not await mgr.health_check():
            return
        store = use_cases.QdrantVectorStore(mgr, _embedding(settings), "wiki_")
        await store.ensure_collection(persona)
        await store.upsert(persona, slug, f"{title}\n\n{body}")
    except Exception as e:
        logger.warning("wiki vector upsert failed for %s: %s", slug, e)
    finally:
        close = getattr(mgr, "close", None)
        if close is not None:
            result = close()
            if asyncio.iscoroutine(result):
                await result


async def async_drop_page(settings: Settings, persona: str, slug: str) -> None:
    """1 ページを索引から削除する（失敗は warning）。"""
    from nous.application import use_cases

    mgr = use_cases.QdrantClientManager(settings.qdrant.url, settings.qdrant.api_key)
    try:
        await mgr.connect()
        if not await mgr.health_check():
            return
        store = use_cases.QdrantVectorStore(mgr, _embedding(settings), "wiki_")
        await store.delete(persona, slug)
    except Exception as e:
        logger.warning("wiki vector delete failed for %s: %s", slug, e)
    finally:
        close = getattr(mgr, "close", None)
        if close is not None:
            result = close()
            if asyncio.iscoroutine(result):
                await result


async def async_drop_memories(settings: Settings, persona: str, keys: list[str]) -> None:
    """記憶のベクトル（collection prefix ``""``）をキーごとに削除する（失敗は warning）。"""
    if not keys:
        return
    from nous.application import use_cases

    mgr = use_cases.QdrantClientManager(settings.qdrant.url, settings.qdrant.api_key)
    try:
        await mgr.connect()
        if not await mgr.health_check():
            return
        store = use_cases.QdrantVectorStore(mgr, _embedding(settings), "")
        for key in keys:
            try:
                await store.delete(persona, key)
            except Exception as e:
                logger.warning("memory vector delete failed for %s: %s", key, e)
    except Exception as e:
        logger.warning("memory vector delete failed for %s: %s", persona, e)
    finally:
        close = getattr(mgr, "close", None)
        if close is not None:
            result = close()
            if asyncio.iscoroutine(result):
                await result


def sync_page(settings: Settings, persona: str, slug: str, title: str, body: str) -> None:
    """同期ラッパ（編纂 worker の thread から呼ぶ）。"""
    try:
        asyncio.run(async_sync_page(settings, persona, slug, title, body))
    except Exception as e:
        logger.warning("wiki vector upsert failed for %s: %s", slug, e)


def drop_page(settings: Settings, persona: str, slug: str) -> None:
    """同期ラッパ（編纂 worker の thread から呼ぶ）。"""
    try:
        asyncio.run(async_drop_page(settings, persona, slug))
    except Exception as e:
        logger.warning("wiki vector delete failed for %s: %s", slug, e)


def drop_memories(settings: Settings, persona: str, keys: list[str]) -> None:
    """同期ラッパ（編纂 worker の thread から呼ぶ）。"""
    try:
        asyncio.run(async_drop_memories(settings, persona, keys))
    except Exception as e:
        logger.warning("memory vector delete failed for %s: %s", persona, e)


def _embedding(settings: Settings):
    """共有 EmbeddingModel（AppContext と同じ resolution を使う）。"""
    from nous.application.use_cases import AppContextRegistry

    for persona in list(AppContextRegistry._contexts.keys()):
        ctx = AppContextRegistry.get(persona)
        model = getattr(ctx, "embedding_model", None)
        if model is not None:
            return model
    raise RuntimeError("no embedding model available")
