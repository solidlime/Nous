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


__all__ = ["_tool_wiki_ls", "_tool_wiki_read", "_tool_wiki_write"]
