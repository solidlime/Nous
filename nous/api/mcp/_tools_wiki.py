"""wiki ツールの中核実装（MCP / builtin 共用）— 計画書 §4.5.

読む・書く・一覧・grep・削除の 5 面。削除は取り消せないので、``index`` を拒む
（store 側で拒否）のと、存在確認を先に行って「消した」と言い切れる時だけ成功を
返すのを守る。索引（Qdrant）も同時に落とす。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from nous.api.mcp._envelope import ToolErrorCode, tool_error, tool_ok
from nous.domain.shared.result import Failure, Success
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
        "tags": list(page.tags),
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
    ctx: AppContext,
    persona: str,
    project: str | None = None,
    tag: str | None = None,
    limit: int = LS_DEFAULT_LIMIT,
) -> str:
    """wiki ページの一覧（slug / title / project / tags / 更新日時）。

    ``tag`` を渡すとそのタグを持つページだけに絞る（``tag="journal"`` で日記をまとめて引く）。
    """
    pages = _store(ctx, persona).list_pages()
    if project:
        wanted = project.lower()
        pages = [p for p in pages if (p.project or "").lower() == wanted]
    if tag:
        pages = [p for p in pages if tag in p.tags]
    pages = sorted(pages, key=lambda p: p.updated or "", reverse=True)
    items = [_page_dict(p) for p in pages[: max(1, limit)]]
    return tool_ok(items, total=len(pages))


async def _tool_wiki_delete(ctx: AppContext, persona: str, slug: str) -> str:
    """wiki ページを削除する（``index`` は拒否、索引も落とす）。

    存在確認を先に行う: 無い slug を「消した」と返すと、呼び出し側は消えたつも
    りで次の判断をする。
    """
    from nous.application.wiki.vector_index import async_drop_page

    store = _store(ctx, persona)
    prior = store.read_page(slug)
    if isinstance(prior, Failure):
        return tool_error(ToolErrorCode.NOT_FOUND, f"wiki page not found: {slug}")
    result = store.delete_page(slug)
    if isinstance(result, Failure):
        return tool_error(ToolErrorCode.VALIDATION_ERROR, str(result.error))
    # 索引はミラー。落とせなくても削除は成立する（毎サイクルの再同期で直る）。
    await async_drop_page(ctx.settings, persona, slug)
    return tool_ok({"slug": slug, "deleted": True, "title": prior.value.title})


async def _tool_wiki_write(
    ctx: AppContext,
    persona: str,
    slug: str,
    title: str,
    body: str,
    project: str | None = None,
    sources: list[str] | None = None,
) -> str:
    """wiki ページを書く（slug は ``project-<slug>-<topic>`` か ``<persona>-<topic>``）。

    既存ページの ``tags`` は引き継ぐ（書いたことでタグが消えない）。
    """
    store = _store(ctx, persona)
    prior = store.read_page(slug)
    prior_page = prior.value if isinstance(prior, Success) else None
    result = store.write_page(
        slug,
        title,
        body,
        project=project,
        sources=tuple(sources or ()),
        tags=prior_page.tags if prior_page else (),
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
