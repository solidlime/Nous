"""未解決の問い（open-question）の正規化キーと解消（kanban #55）。

LLM の自由記述をそのままハッシュすると、文面が 1 文字変わるたびに新しい問いが
生まれる（本番で 45 件に増殖した）。キーは「何についての問いか」だけで決める:

- 矛盾: ``pair:<slug_a>|<slug_b>:<kind>``（slug はソート済み）
- 問い: ``q:<topic>:<正規化本文の先頭 12 桁>``

Zero Inbox（#54）では「閉じる = 消す」。解消された問いを archived に沈めても
次のサイクル冒頭で物理削除されるので、最初から消す。
"""

from __future__ import annotations

import hashlib
import logging
import re
import unicodedata
from typing import TYPE_CHECKING

from nous.domain.shared.result import Success

if TYPE_CHECKING:
    from collections.abc import Iterable

    from nous.domain.memory.entities import Memory

logger = logging.getLogger(__name__)

OPEN_QUESTION_TAG = "open-question"
OPEN_QUESTION_PREFIX = "open-question:"
QUESTION_KEY_PREFIX = "qkey:"

_STRIP_RE = re.compile(r"[^0-9a-z\u3040-\u30ff\u4e00-\u9fff]+")


def normalize_question_text(text: str) -> str:
    """比較用の正規化（NFKC・小文字・記号と空白の除去）。"""
    return _STRIP_RE.sub("", unicodedata.normalize("NFKC", text).lower())


def _digest(text: str, size: int = 12) -> str:
    return hashlib.sha1(normalize_question_text(text).encode("utf-8")).hexdigest()[:size]


def question_pair_key(a: str, b: str, kind: str | None = None) -> str:
    """矛盾 1 件の正規化キー。同じ 2 ページ・同じ種別なら文面が変わっても同じキー。"""
    left, right = sorted((a.strip().lower(), b.strip().lower()))
    return f"{QUESTION_KEY_PREFIX}pair:{left}|{right}:{(kind or 'fact').strip().lower() or 'fact'}"


def question_query_key(topic: str, query: str) -> str:
    """自由記述の問いの正規化キー（topic + 本文の正規化ハッシュ）。"""
    return f"{QUESTION_KEY_PREFIX}q:{topic.strip().lower()}:{_digest(query)}"


def question_key_of(memory: object) -> str:
    """記憶の ``source_context`` から qkey を復元する（旧形式は空文字）。"""
    raw = str(getattr(memory, "source_context", "") or "")
    if not raw.startswith(OPEN_QUESTION_PREFIX):
        return ""
    return raw[len(OPEN_QUESTION_PREFIX) :]


def is_open_question(memory: object) -> bool:
    return OPEN_QUESTION_TAG in (getattr(memory, "tags", ()) or ())


def source_context_for(key: str) -> str:
    return f"{OPEN_QUESTION_PREFIX}{key}"


def find_open_questions(ctx) -> list[Memory]:
    """未解決の問いを全部返す（新しい順）。repo はペルソナごとの DB なので絞り込み不要。"""
    result = ctx.memory_repo.find_all()
    if not isinstance(result, Success):
        return []
    questions = [
        m
        for m in result.value
        if is_open_question(m) and str(getattr(m, "source_context", "")).startswith(OPEN_QUESTION_PREFIX)
    ]
    questions.sort(key=_timestamp, reverse=True)
    return questions


def _timestamp(memory: object) -> float:
    """並べ替え用の秒。naive/aware 混在でも比較できるように float へ落とす。"""
    value = getattr(memory, "created_at", None) or getattr(memory, "updated_at", None)
    return float(value.timestamp()) if value is not None and hasattr(value, "timestamp") else 0.0


async def delete_memories(ctx, persona: str, memories: Iterable[object]) -> int:
    """記憶を物理削除する（SQLite の行ごと + ベクトル）。消せた件数を返す。

    ``memory_service.delete_memory`` は tombstone を立てるだけで行が残るので使わない。
    Zero Inbox では「解消した問い」は消す（2 回目以降に拾わない）。
    """
    keys = [str(getattr(m, "key", "") or "") for m in memories]
    keys = [k for k in keys if k]
    if not keys:
        return 0
    deleted = 0
    repo = getattr(ctx, "memory_repo", None)
    if repo is not None:
        try:
            result = repo.delete_many(keys)
            if getattr(result, "is_ok", False):
                deleted = int(result.value)
            else:
                logger.warning("questions: delete_many failed: %s", getattr(result, "error", ""))
        except Exception:  # noqa: BLE001 — 呼び手は監査の数字で気づける
            logger.warning("questions: delete_many raised", exc_info=True)
    else:  # memory_repo を持たない ctx（テスト用の最小スタブ）
        for key in keys:
            try:
                if getattr(ctx.memory_service.delete_memory(key), "is_ok", False):
                    deleted += 1
            except Exception:
                logger.warning("questions: delete failed for %s", key, exc_info=True)
    if deleted:
        vector_store = getattr(ctx, "vector_store", None)
        for key in keys:
            if vector_store is None:
                break
            try:
                await vector_store.delete(persona, key)
            except Exception:  # noqa: BLE001 — 索引はミラー。消え残っても再構築で直る
                logger.debug("questions: vector delete failed for %s", key, exc_info=True)
    return deleted


async def close_open_questions(ctx, persona: str, key: str) -> int:
    """指定 qkey の未解決の問いを解消として消す。"""
    if not key:
        return 0
    targets = [m for m in find_open_questions(ctx) if question_key_of(m) == key]
    return await delete_memories(ctx, persona, targets)


async def dedupe_open_questions(ctx, persona: str, *, cap: int) -> tuple[int, int]:
    """本文の正規化が同じ問いを 1 件に畳み、上限を超えた古い問いを消す。

    戻り値は ``(消した件数, 残った件数)``。
    """
    questions = find_open_questions(ctx)
    keep: list[object] = []
    buckets: dict[str, object] = {}
    dropped: list[object] = []
    for memory in questions:  # 新しい順
        # 同一性の正本は qkey。本文の正規化は qkey を持たない旧形式（qhash）の救済だけに使う。
        fingerprint = question_key_of(memory)
        if not fingerprint.startswith("qkey:"):
            fingerprint = "qhash:" + (normalize_question_text(str(getattr(memory, "content", "")))[:160] or fingerprint)
        if fingerprint in buckets:
            dropped.append(memory)
            continue
        buckets[fingerprint] = memory
        keep.append(memory)
        if len(keep) > max(0, cap):
            dropped.append(memory)
            keep.pop()
    deleted = await delete_memories(ctx, persona, dropped)
    return deleted, len(keep)
