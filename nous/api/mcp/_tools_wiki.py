"""wiki ツールの中核実装（MCP / builtin 共用）— 計画書 §4.5.

読む・書く・一覧 の 3 面だけ。削除は持たない（誤削除より退屈な解決を選ぶ:
未使用ページは index で沈黙するだけで、害にならない）。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from nous.api.mcp._envelope import ToolErrorCode, tool_error, tool_ok
from nous.domain.shared.result import Failure
from nous.infrastructure.wiki.store import WikiStore

if TYPE_CHECKING:
    from nous.application.use_cases import AppContext

#: wiki_ls の既定件数上限。
LS_DEFAULT_LIMIT = 50

#: wiki_grep の既定件数上限（行単位ヒット）。
GREP_DEFAULT_LIMIT = 50
GREP_MAX_LIMIT = 200


def _store(ctx: AppContext, persona: str) -> WikiStore:
    return WikiStore(ctx.settings.data_root, persona)


def _page_dict(page: Any) -> dict[str, Any]:
    return {
        "slug": page.slug,
        "title": page.title,
        "project": page.project,
        "sources": list(page.sources),
        "updated": page.updated,
        "links": list(page.links),
    }


async def _tool_wiki_read(ctx: AppContext, persona: str, slug: str) -> str:
    """wiki ページを slug で読む。"""
    result = _store(ctx, persona).read_page(slug)
    if isinstance(result, Failure):
        return tool_error(ToolErrorCode.NOT_FOUND, f"wiki page not found: {slug}")
    page = result.value
    return tool_ok(page.body, **{k: v for k, v in _page_dict(page).items() if k != "sources"})


async def _tool_wiki_ls(
    ctx: AppContext, persona: str, project: str | None = None, limit: int = LS_DEFAULT_LIMIT
) -> str:
    """wiki ページの一覧（slug / title / project / 更新日時）。"""
    pages = _store(ctx, persona).list_pages()
    if project:
        wanted = project.lower()
        pages = [p for p in pages if (p.project or "").lower() == wanted]
    pages = sorted(pages, key=lambda p: p.updated or "", reverse=True)
    items = [_page_dict(p) for p in pages[: max(1, limit)]]
    return tool_ok(items, total=len(pages))


async def _tool_wiki_write(
    ctx: AppContext,
    persona: str,
    slug: str,
    title: str,
    body: str,
    project: str | None = None,
    sources: list[str] | None = None,
) -> str:
    """wiki ページを書く（slug は ``project-<slug>-<topic>`` か ``<persona>-<topic>``）。"""
    result = _store(ctx, persona).write_page(
        slug,
        title,
        body,
        project=project,
        sources=tuple(sources or ()),
    )
    if isinstance(result, Failure):
        return tool_error(ToolErrorCode.VALIDATION_ERROR, str(result.error))
    page = result.value
    return tool_ok({"slug": page.slug, "title": page.title, "project": page.project}, **{})


async def _tool_wiki_grep(ctx: AppContext, persona: str, pattern: str, limit: int = GREP_DEFAULT_LIMIT) -> str:
    """wiki 本文を行単位の正規表現で grep する（slug・行番号・行テキストを返す）。

    意味検索では取り逃がす「字面が一致しないと嘘になる」照合用。
    目次（index.md）は本文の写しなので対象外。
    """
    if not pattern.strip():
        return tool_error(ToolErrorCode.VALIDATION_ERROR, "pattern must not be empty")
    capped = max(1, min(limit, GREP_MAX_LIMIT))
    try:
        hits = _store(ctx, persona).grep(pattern, limit=capped)
    except Exception as exc:  # invalid regex は WikiStoreError
        return tool_error(ToolErrorCode.VALIDATION_ERROR, f"{exc}")
    items = [{"slug": slug, "line": line_no, "text": text} for slug, line_no, text in hits]
    return tool_ok(items, total=len(items), pattern=pattern)


__all__ = ["_tool_wiki_grep", "_tool_wiki_ls", "_tool_wiki_read", "_tool_wiki_write"]
