"""wiki ツール（read/ls/write）のテスト — 計画書 §4.5."""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

from nous.api.mcp._tools_wiki import (
    _tool_wiki_grep,
    _tool_wiki_ls,
    _tool_wiki_read,
    _tool_wiki_write,
)
from nous.infrastructure.wiki.store import WikiStore


def _ctx(tmp_path) -> Any:
    return SimpleNamespace(settings=SimpleNamespace(data_root=str(tmp_path)))


def _payload(raw: str) -> dict:
    data: dict = json.loads(raw)
    return data


async def test_write_then_read_roundtrip(tmp_path):
    ctx = _ctx(tmp_path)
    written = _payload(
        await _tool_wiki_write(ctx, "herta", "project-nous-memory", "NOUS の記憶", "本文", project="nous")
    )
    assert written["ok"] is True
    assert written["data"]["slug"] == "project-nous-memory"

    read = _payload(await _tool_wiki_read(ctx, "herta", "project-nous-memory"))
    assert read["ok"] is True
    assert read["data"] == "本文"
    assert read["title"] == "NOUS の記憶"
    assert read["project"] == "nous"


async def test_read_missing_page_is_not_found(tmp_path):
    result = _payload(await _tool_wiki_read(_ctx(tmp_path), "herta", "no-such-page"))
    assert result["ok"] is False
    assert result["error"]["code"] == "NOT_FOUND"


async def test_write_uppercase_slug_and_index_rejected(tmp_path):
    ctx = _ctx(tmp_path)
    bad = _payload(await _tool_wiki_write(ctx, "herta", "Project-Bad", "t", "b"))
    assert bad["ok"] is False
    assert bad["error"]["code"] == "VALIDATION_ERROR"

    index = _payload(await _tool_wiki_write(ctx, "herta", "index", "t", "b"))
    assert index["ok"] is False


async def test_ls_filters_by_project(tmp_path):
    ctx = _ctx(tmp_path)
    await _tool_wiki_write(ctx, "herta", "project-nous-a", "A", "body a", project="nous")
    await _tool_wiki_write(ctx, "herta", "project-other-b", "B", "body b", project="other")
    await _tool_wiki_write(ctx, "herta", "herta-c", "C", "body c")

    all_pages = _payload(await _tool_wiki_ls(ctx, "herta"))
    assert all_pages["total"] == 3

    nous_pages = _payload(await _tool_wiki_ls(ctx, "herta", project="NOUS"))
    assert nous_pages["total"] == 1
    assert nous_pages["data"][0]["slug"] == "project-nous-a"


async def test_ls_exposes_tags_and_filters_by_tag(tmp_path):
    """`tag="journal"` で日記だけ引ける（計画書 §3.1 の一括参照）。"""
    store = WikiStore(str(tmp_path), "herta")
    store.write_page("journal-2026-11-09", "9日の記録", "本文", tags=("journal", "2026-11"))
    store.write_page("project-nous-a", "A", "本文", project="nous")

    ctx = _ctx(tmp_path)
    all_pages = _payload(await _tool_wiki_ls(ctx, "herta"))
    by_slug = {p["slug"]: p for p in all_pages["data"]}
    assert by_slug["journal-2026-11-09"]["tags"] == ["journal", "2026-11"]
    assert by_slug["project-nous-a"]["tags"] == []

    journals = _payload(await _tool_wiki_ls(ctx, "herta", tag="journal"))
    assert journals["total"] == 1
    assert journals["data"][0]["slug"] == "journal-2026-11-09"


async def test_grep_hits_slug_line_and_text(tmp_path):
    ctx = _ctx(tmp_path)
    await _tool_wiki_write(ctx, "herta", "herta-a", "A", "coffee は好物" + chr(10) + "ビールも好き")
    await _tool_wiki_write(ctx, "herta", "herta-b", "B", "Coffee 派と紅茶派")

    result = _payload(await _tool_wiki_grep(ctx, "herta", "coffee"))
    assert result["ok"] is True
    assert result["total"] == 2
    slugs = {hit["slug"] for hit in result["data"]}
    assert slugs == {"herta-a", "herta-b"}
    assert all(hit["line"] >= 1 and "offee" in hit["text"] for hit in result["data"])


async def test_grep_rejects_empty_pattern_and_bad_regex(tmp_path):
    ctx = _ctx(tmp_path)
    await _tool_wiki_write(ctx, "herta", "herta-a", "A", "body")

    empty = _payload(await _tool_wiki_grep(ctx, "herta", "   "))
    assert empty["ok"] is False and empty["error"]["code"] == "VALIDATION_ERROR"

    bad = _payload(await _tool_wiki_grep(ctx, "herta", "(["))
    assert bad["ok"] is False and bad["error"]["code"] == "VALIDATION_ERROR"


async def test_grep_respects_limit(tmp_path):
    ctx = _ctx(tmp_path)
    await _tool_wiki_write(ctx, "herta", "herta-a", "A", "派 派 派" + chr(10) + "派 派")
    result = _payload(await _tool_wiki_grep(ctx, "herta", "派", limit=2))
    assert result["total"] == 2


async def test_write_preserves_existing_tags(tmp_path):
    """既存ページを書いてもタグは消えない（journal タグの一括参照を守る）。"""
    from nous.infrastructure.wiki.store import WikiStore

    ctx = _ctx(tmp_path)
    store = WikiStore(str(tmp_path), "herta")
    assert store.write_page("journal-2026-11-09", "d", "本文", tags=("journal", "2026-11")).is_ok

    assert _payload(await _tool_wiki_write(ctx, "herta", "journal-2026-11-09", "d", "書き直し"))["ok"] is True
    assert store.read_page("journal-2026-11-09").value.tags == ("journal", "2026-11")
