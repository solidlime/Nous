"""LAZY_MANIFEST の /static パスが実在すること（kanban #132）.

v4 は manifest を SSOT にして「タブ初回に必要な script だけ」を読む。束ね役の
chunk（overview/memories/misc）を廃したので、manifest の ``scripts`` がそのまま
実ファイルを指す。typo や消し忘れはブラウザでしか露見しないため、ここで固定する。
"""

from pathlib import Path

import pytest

from nous.api.http.sections.base import LAZY_MANIFEST, render_head

STATIC = Path(__file__).resolve().parents[2] / "nous" / "api" / "http"


def _local(path: str) -> Path:
    return STATIC / "static" / path.removeprefix("/static/")


def test_tab_scripts_exist_on_disk():
    missing = [
        f"{tab}:{src}"
        for tab, spec in LAZY_MANIFEST["tabs"].items()
        for src in spec["scripts"]
        if src.startswith("/static/") and not _local(src).is_file()
    ]
    assert missing == [], f"manifest が存在しない script を指している: {missing}"


def test_no_bundling_chunk_indirection():
    """#132: 束ね chunk を挟まず、実体ファイルを直接並べる。

    chunk を挟むとそのタブを開くだけで全タブ分の script が走る。
    導入するなら「そのタブだけ」を保証する別の仕組みとセットで。
    """
    bundled = [
        f"{tab}:{src}"
        for tab, spec in LAZY_MANIFEST["tabs"].items()
        for src in spec["scripts"]
        if src.endswith(".chunk.js") and tab != "chat"
    ]
    assert bundled == [], f"chat 以外に chunk 経由の script がある: {bundled}"


@pytest.mark.parametrize("tab", ["wiki", "projects", "activity", "timeline", "graph", "settings"])
def test_each_tab_loads_only_its_own_sources(tab):
    spec = LAZY_MANIFEST["tabs"][tab]
    others = {src for other, s in LAZY_MANIFEST["tabs"].items() if other != tab for src in s["scripts"]}
    own = set(spec["scripts"])
    assert own - others == own, f"{tab} が他タブの source を巻き込んでいる: {sorted(own & others)}"


def test_manifest_is_embedded_in_head():
    """契約文字列の維持（test_wiki_router / e2e が HTML を grep する）。"""
    head = render_head()
    assert 'id="lazy-manifest"' in head
    assert "/static/features/wiki.js" in head
    assert "/static/shell.js" in head
