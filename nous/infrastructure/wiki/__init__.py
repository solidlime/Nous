"""Wiki persistence layer (filesystem is the source of truth).

計画書: ``docs/superpowers/plans/2026-11-07-wiki-dreaming.md`` §3.1。

Wiki pages live at ``{data_root}/persona/{persona}/wiki/{slug}.md`` as
Markdown with a tiny ``---`` frontmatter block (``title`` / ``project`` /
``updated`` / ``sources``).  The DB index and embeddings are derived
artifacts; this module never touches them.
"""

from __future__ import annotations

from .store import (
    INDEX_SLUG,
    MAX_PAGE_BYTES,
    WikiPage,
    WikiStore,
    WikiStoreError,
    parse_page,
    render_page,
)

__all__ = [
    "INDEX_SLUG",
    "MAX_PAGE_BYTES",
    "WikiPage",
    "WikiStore",
    "WikiStoreError",
    "parse_page",
    "render_page",
]
