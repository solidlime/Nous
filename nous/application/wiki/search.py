"""wiki ページ検索 — Qdrant 索引（collection ``wiki_<persona>``）+ ファイル TF フォールバック。

計画書 ``docs/superpowers/plans/2026-11-07-wiki-dreaming.md`` §4.4:
既存の memory 検索結果（``results[]`` / ``memories``）は一切変えない。wiki は別枠の
``wiki[]`` として返す（既存ハーネスが ``memory.key`` 前提で読むため、混ぜると壊れる）。

Qdrant 未起動・索引未作成でもファイル層が正なので、TF 走査にフォールバックする。
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from nous.domain.shared.result import Success
from nous.infrastructure.logging.structured import get_logger

if TYPE_CHECKING:
    from nous.application.use_cases import AppContext

logger = get_logger(__name__)

#: 応答に含める本文抜粋の長さ。
EXCERPT_CHARS = 200

#: これ未満のページ数ならベクトル索引を使わない。ファイル TF が全ページを走査するので
#: 結果は同一のまま、検索 1 回ごとの追加 embedding + Qdrant 往復（実測 100-250ms）を削れる。
_VECTOR_MIN_PAGES = 8

_WORD_RE = re.compile(r"[a-z0-9]+")


async def search_wiki_pages(ctx: AppContext, persona: str, query: str, limit: int = 3) -> list[dict[str, Any]]:
    """wiki ページを検索し ``[{slug, title, project, excerpt, score}]`` を返す。

    スコアは Qdrant cosine（0-1 相当）を優先し、索引ミス／未作成分は
    ファイル TF（クエリ語の出現率）を 0-1 に正規化して使う。
    """
    if not query.strip() or limit < 1:
        return []

    pages_by_slug: dict[str, Any] = {}
    try:
        from nous.infrastructure.wiki.store import WikiStore

        store = WikiStore(ctx.settings.data_root, persona)
        pages_by_slug = {p.slug: p for p in store.list_pages()}
    except Exception as e:
        logger.debug("wiki store unavailable for %s: %s", persona, e)
        return []

    scores: dict[str, float] = {}
    # 1) ベクトル索引（ミラー）。小規模 wiki はどのみち TF が全ページを見るので
    #    省略する（検索 1 回ごとの追加 embedding + Qdrant 往復を削る）。失敗は TF が吸収する。
    if pages_by_slug and len(pages_by_slug) >= _VECTOR_MIN_PAGES:
        try:
            from nous.application import use_cases

            vector_store = getattr(ctx, "vector_store", None)
            if vector_store is not None:
                wiki_vs = use_cases.QdrantVectorStore(vector_store.client_manager, vector_store.embedding, "wiki_")
                result = await wiki_vs.search(persona, query, limit=max(limit * 2, 6))
                if isinstance(result, Success):
                    for slug, score in result.value:
                        if slug in pages_by_slug:
                            scores[slug] = max(scores.get(slug, 0.0), float(score))
        except Exception as e:
            logger.debug("wiki vector search failed for %s: %s", persona, e)

    # 2) ファイル TF（索引未作成・未ヒット分の底上げ）
    terms = _query_terms(query)
    for slug, page in pages_by_slug.items():
        if slug in scores:
            continue
        tf = _tf_score(page.title, page.body, query, terms)
        if tf > 0:
            scores[slug] = tf

    ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)[:limit]
    return [
        {
            "slug": slug,
            "title": pages_by_slug[slug].title,
            "project": pages_by_slug[slug].project,
            "excerpt": _excerpt(pages_by_slug[slug].body),
            "score": round(min(1.0, max(0.0, score)), 4),
        }
        for slug, score in ranked
    ]


def _query_terms(query: str) -> list[str]:
    """クエリの照合語（英数トークン + 空白区切り断片）。"""
    lowered = query.lower()
    terms = set(_WORD_RE.findall(lowered))
    terms.update(part for part in re.split(r"\s+", lowered) if len(part) >= 2)
    return sorted(terms)


def _tf_score(title: str, body: str, query: str, terms: list[str]) -> float:
    """単純 TF: クエリ全体の一致 + 語毎の一致率を 0-1 に正規化。"""
    haystack = f"{title}\n{body}".lower()
    if query.strip().lower() in haystack:
        return 1.0
    if not terms:
        return 0.0
    hit = sum(1 for term in terms if term in haystack)
    return hit / len(terms)


def _excerpt(body: str) -> str:
    """本文の先頭を 1 行に潰して抜粋にする（見出し記号は落とす）。"""
    flat = re.sub(r"^#+\s*", "", body, flags=re.MULTILINE)
    flat = re.sub(r"\s+", " ", flat).strip()
    return flat[:EXCERPT_CHARS]
