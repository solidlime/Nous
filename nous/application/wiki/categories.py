"""wiki ページのカテゴリ導出。

新しい frontmatter フィールドは持たない。既にある ``tags`` / ``project`` / slug から
決める（フィールドを増やすと write 経路 4 箇所すべてで引き継ぎ漏れが起きる）。

導出規則（上から順に評価して最初に当たったもの）:

- ``journal`` タグを持つ、または slug が ``journal-`` で始まる → ``journal``
- ``project`` が非空 → ``project``
- slug が persona 名と同じ → ``persona``
- それ以外 → ``other``
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from nous.infrastructure.wiki.store import WikiPage

#: カテゴリの表示順と見出し（UI と MCP で同じ並びを使う）。
CATEGORY_ORDER: tuple[str, ...] = ("journal", "project", "persona", "other")

CATEGORY_LABELS: dict[str, str] = {
    "journal": "日記",
    "project": "プロジェクト",
    "persona": "人柄",
    "other": "その他",
}

JOURNAL_PREFIX = "journal-"


def categorize(page: WikiPage, persona: str) -> str:
    """ページを 4 カテゴリのどれかに落とす。"""
    if "journal" in page.tags or page.slug.startswith(JOURNAL_PREFIX):
        return "journal"
    if page.project:
        return "project"
    if page.slug == persona:
        return "persona"
    return "other"


def category_label(key: str) -> str:
    """カテゴリキーの表示名（未知のキーはそのまま返す）。"""
    return CATEGORY_LABELS.get(key, key)
