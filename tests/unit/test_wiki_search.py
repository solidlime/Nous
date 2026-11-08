"""wiki ページ検索（TF フォールバック）のテスト — 計画書 §4.4 の ``wiki[]`` 経路. 

Qdrant 無しでもファイル層からヒットすること、無関係クエリは空を返すことを確認する。
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from nous.application.wiki.search import EXCERPT_CHARS, search_wiki_pages
from nous.infrastructure.wiki.store import WikiStore

PERSONA = "herta"


def _ctx(tmp_path):
    settings = SimpleNamespace(data_root=str(tmp_path))
    return SimpleNamespace(settings=settings, vector_store=None)


def _seed(tmp_path) -> None:
    store = WikiStore(tmp_path, PERSONA)
    store.write_page(
        "project-nous-memory-design",
        "NOUS の記憶設計",
        "## 決定\nマスターデータは SQLite が正。ベクトルは派生索引。",
        project="nous",
        sources=("a1",),
    )
    store.write_page(
        "herta-preferences",
        "ヘルタの好み",
        "## 好み\n紅茶と数学。退屈は嫌い。",
        sources=("a2",),
    )


async def test_search_hits_wiki_page_by_title(tmp_path):
    _seed(tmp_path)
    hits = await search_wiki_pages(_ctx(tmp_path), PERSONA, "記憶設計", limit=3)
    assert hits
    assert hits[0]["slug"] == "project-nous-memory-design"
    assert hits[0]["title"] == "NOUS の記憶設計"
    assert hits[0]["project"] == "nous"
    assert len(hits[0]["excerpt"]) <= EXCERPT_CHARS
    assert hits[0]["score"] == pytest.approx(1.0)


async def test_search_returns_excerpt_and_project(tmp_path):
    _seed(tmp_path)
    hits = await search_wiki_pages(_ctx(tmp_path), PERSONA, "SQLite ベクトル", limit=3)
    assert hits
    assert any("SQLite" in hit["excerpt"] for hit in hits)


async def test_search_no_hit_is_empty(tmp_path):
    _seed(tmp_path)
    hits = await search_wiki_pages(_ctx(tmp_path), PERSONA, "全く無関係な話題 zzz", limit=3)
    assert hits == []


async def test_search_missing_persona_is_empty(tmp_path):
    hits = await search_wiki_pages(_ctx(tmp_path), "nobody", "記憶", limit=3)
    assert hits == []
