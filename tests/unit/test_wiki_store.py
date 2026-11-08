from __future__ import annotations

import pytest

from nous.infrastructure.wiki.store import (
    INDEX_SLUG,
    MAX_PAGE_BYTES,
    WikiStore,
    WikiStoreError,
    extract_links,
    parse_page,
    render_page,
)


@pytest.fixture
def store(tmp_path):
    return WikiStore(tmp_path, "herta")


def test_write_and_read_roundtrip(store, tmp_path):
    result = store.write_page(
        "project-nous",
        title="NOUS project",
        body="メモリ設計のまとめ。\n\n[[topic-memory]] を参照。",
        project="nous",
        sources=("memory_a", "memory_b"),
    )
    assert result.is_ok

    got = store.read_page("project-nous")
    assert got.is_ok
    page = got.value
    assert page.title == "NOUS project"
    assert page.project == "nous"
    assert page.sources == ("memory_a", "memory_b")
    assert page.links == ("topic-memory",)
    assert page.updated is not None
    # 実ファイルが {data_root}/persona/{persona}/wiki/ 配下に存在する
    assert (tmp_path / "persona" / "herta" / "wiki" / "project-nous.md").is_file()


def test_nested_slug_creates_subdir(store, tmp_path):
    assert store.write_page("project-nous/memory", title="Memory", body="x").is_ok
    assert (tmp_path / "persona" / "herta" / "wiki" / "project-nous" / "memory.md").is_file()
    assert "project-nous/memory" in store.list_slugs()


@pytest.mark.parametrize("slug", ["../escape", "a/../b", "/abs", "Upper", "a b", "a:b", ""])
def test_invalid_slugs_rejected(store, slug):
    result = store.write_page(slug, title="t", body="b")
    assert not result.is_ok
    assert isinstance(result.error, WikiStoreError)


def test_index_is_generated_only(store):
    assert store.write_page(INDEX_SLUG, title="t", body="b").is_ok is False
    assert store.delete_page(INDEX_SLUG).is_ok is False
    store.write_page("topic-memory", title="Memory systems", body="長期記憶の整理。")
    index = store.read_page(INDEX_SLUG)
    assert index.is_ok
    body = index.value.body
    assert "[[topic-memory]]" in body
    assert "Memory systems" in body


def test_size_cap_rejected(store):
    body = "長" * (MAX_PAGE_BYTES // 3 + 10)  # UTF-8 で 3 バイト/文字 → 上限超え
    result = store.write_page("topic-big", title="Big", body=body)
    assert not result.is_ok
    assert "too large" in str(result.error)
    assert not store.read_page("topic-big").is_ok


def test_delete_page(store):
    store.write_page("topic-x", title="X", body="y")
    assert store.delete_page("topic-x").is_ok
    assert not store.read_page("topic-x").is_ok
    assert not store.delete_page("topic-x").is_ok


def test_grep(store):
    store.write_page("project-a", title="A", body="alpha\nbootstrapping の話\nGamma")
    store.write_page("project-b", title="B", body="gamma only")
    hits = store.grep("gamma")
    assert {slug for slug, _, _ in hits} == {"project-a", "project-b"}
    assert hits[0][1] >= 1
    limited = store.grep("gamma", limit=1)
    assert len(limited) == 1
    with pytest.raises(WikiStoreError):
        store.grep("(unclosed")


def test_dangling_links(store):
    store.write_page("project-a", title="A", body="[[project-b]] と [[missing-page]]")
    store.write_page("project-b", title="B", body="ok")
    store.write_page("project-c", title="C", body="[[project-c]] self link")
    assert store.dangling_links() == {"project-a": ["missing-page"]}


def test_extract_links_with_alias_and_duplicates():
    assert extract_links("[[a]] [[a|表示名]] [[b/c]]") == ("a", "b/c")


def test_parse_render_roundtrip():
    page = parse_page("s", "---\ntitle: T\nproject: p\nsources: m1, m2\n---\nbody [[x]]\n")
    assert page.title == "T"
    assert page.project == "p"
    assert page.sources == ("m1", "m2")
    assert page.links == ("x",)
    rendered = render_page(page)
    assert rendered.startswith("---\ntitle: T\nproject: p\nsources: m1, m2\n")
    assert parse_page("s", rendered).body == page.body


def test_persona_validation(tmp_path):
    for bad in ("../x", "a/b", "", "."):
        with pytest.raises(WikiStoreError):
            WikiStore(tmp_path, bad)
