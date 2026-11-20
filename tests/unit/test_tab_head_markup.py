"""全タブの見出し帯 `.tab-head` 契約テスト（kanban #127）.

見出しの inline style を `.tab-head` に一本化する変更で、
- h2 のテキスト（タブ名）とパネル/見出しの id が変わらないこと
- 旧 inline 見出し帯（margin-bottom:16px; padding-bottom:12px; border-bottom:...）が残らないこと
- sections.css 側に .tab-head 系の規則が実在すること
を固定する。SSR の属性書式（test_wiki_router）とは別レイヤの回帰防止。
"""

from pathlib import Path

import pytest

from nous.api.http.sections import (
    render_graph_tab,
    render_memories_tab,
    render_overview_tab,
    render_project_tab,
    render_settings_tab,
    render_timeline_tab,
    render_wiki_tab,
)
from nous.api.http.sections.activity import render_activity_tab

SECTIONS_CSS = Path(__file__).resolve().parents[2] / "nous" / "api" / "http" / "static" / "styles" / "sections.css"

# (タブ名, renderer, h2 のテキスト)
TABS = [
    ("overview", render_overview_tab, "Overview"),
    ("memories", render_memories_tab, "Memories"),
    ("activity", render_activity_tab, "Activity"),
    ("graph", render_graph_tab, "Knowledge Graph"),
    ("projects", render_project_tab, "Projects"),
    ("settings", render_settings_tab, "Settings"),
    ("timeline", render_timeline_tab, "Timeline"),
    ("wiki", render_wiki_tab, "Wiki"),
]


@pytest.mark.parametrize("name,render,title", TABS)
def test_tab_head_is_class_based(name, render, title):
    html = render()
    assert f'id="tab-{name}" class="tab-panel' in html
    head = html.index('class="tab-head"')
    # 見出し帯の直後に h2 があり、タブ名が保たれている
    assert "<h2" in html[head : head + 400]
    assert title in html[head : head + 400]
    # 旧 inline 見出し帯の実体が残っていない
    assert 'border-bottom:1px solid var(--glass-border);">' not in html
    assert "<h2 style=" not in html


def test_timeline_subhead_keeps_its_class():
    """2つ目の h2 は .tab-head の外。.tl-subhead で整列を自前保持する。"""
    html = render_timeline_tab()
    assert 'class="tl-subhead"' in html
    assert "Memory Timeline" in html


def test_sections_css_defines_tab_head_vocabulary():
    css = SECTIONS_CSS.read_text(encoding="utf-8")
    for sel in (
        ".tab-head {",
        ".tab-head h2 {",
        ".tab-head h2 span",
        ".tab-head img {",
        ".tl-subhead {",
        ".proj-form {",
        ".proj-section-title {",
        ".proj-row {",
        ".proj-badge-row {",
        ".settings-warn-card {",
        ".ov-quick-row {",
        ".ov-hero-portrait {",
        ".ov-section-title {",
    ):
        assert sel in css, f"sections.css に {sel} がありません"
