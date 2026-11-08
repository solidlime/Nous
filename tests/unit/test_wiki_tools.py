"""wiki ツール（read/ls/write）のテスト — 計画書 §4.5."""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

from nous.api.mcp._tools_wiki import _tool_wiki_ls, _tool_wiki_read, _tool_wiki_write


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
