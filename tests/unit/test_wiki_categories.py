"""wiki ページのカテゴリ導出（新フィールドを持たない 4 分類）。"""

from __future__ import annotations

from nous.application.wiki.categories import categorize, category_label
from nous.infrastructure.wiki.store import WikiPage


def _page(slug, project=None, tags=()):
    return WikiPage(slug=slug, title=slug, body="", project=project, tags=tuple(tags))


class TestCategorize:
    def test_journal_tag_wins(self):
        assert categorize(_page("project-nous", project="nous", tags=("journal", "2026-11")), "herta") == "journal"

    def test_journal_slug_prefix(self):
        """タグを落とされた古いページでも slug で日記に戻す。"""
        assert categorize(_page("journal-2026-11-09"), "herta") == "journal"

    def test_project(self):
        assert categorize(_page("project-nous-overview", project="nous"), "herta") == "project"

    def test_persona(self):
        assert categorize(_page("herta"), "herta") == "persona"

    def test_other(self):
        assert categorize(_page("herta-notes"), "herta") == "other"

    def test_labels(self):
        assert category_label("journal") == "日記"
        assert category_label("unknown-cat") == "unknown-cat"
