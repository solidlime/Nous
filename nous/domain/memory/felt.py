"""Felt tags — 体験記憶に「その時の感情1語」を添える（backlog #40）。

語彙は自由（正典25語に縛らない — 「もやもや」のような生の語を残す）。
保存側（``memory_extractor``）と検索側（``engine`` の felt_boost）が
同じ正規化を共有するためにここへ置く。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable

FELT_TAG_PREFIX = "felt:"
FELT_MAX_CHARS = 20


def normalize_felt(value: object) -> str:
    """LLM 産の felt を小文字化・記号除去・20字上限で正規化する。不正なら ``""``。"""
    if not isinstance(value, str):
        return ""
    text = "".join(ch for ch in value.strip().lower() if ch.isalnum())
    return text[:FELT_MAX_CHARS]


def felt_tag(value: object) -> str | None:
    """``felt:<語>`` タグ。空なら None（タグを足さない）。"""
    word = normalize_felt(value)
    return f"{FELT_TAG_PREFIX}{word}" if word else None


def felt_words(tags: Iterable[str] | None) -> list[str]:
    """記憶の tags に付いた felt 語（空タグは捨てる）。"""
    return [
        tag[len(FELT_TAG_PREFIX) :]
        for tag in tags or []
        if isinstance(tag, str) and tag.startswith(FELT_TAG_PREFIX) and len(tag) > len(FELT_TAG_PREFIX)
    ]


def felt_match(tags: Iterable[str] | None, query_lower: str) -> bool:
    """クエリ（小文字化済み）に感情語が含まれ、felt タグと一致するか。

    2 段: (a) felt 語がクエリにそのまま現れる（「もやもや」のような自由語）、
    (b) 日本語は語形変化で末尾が変わる（「嬉しい」↔「嬉しかった」）ので先頭2字で照合。
    shortcut: (b) は粗い（「楽しい/楽しま」等の 2 字語幹が共通）。誤爆が実害になったら
    形態素解析に置き換える。1 文字語は部分一致で誤爆するので一致に使わない。
    """
    if not query_lower:
        return False
    for word in felt_words(tags):
        if len(word) < 2:
            continue
        if word in query_lower:
            return True
        if not word.isascii() and word[:2] in query_lower:
            return True
    return False
