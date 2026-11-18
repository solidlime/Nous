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


def test_parse_ignores_legacy_manual_flag():
    """旧 frontmatter の ``manual: true`` は読めても無視する（後方互換）。"""
    page = parse_page("s", "---\ntitle: T\nmanual: true\n---\nbody\n")
    assert page.title == "T"
    assert page.body == "body"
    assert not hasattr(page, "manual")
    assert "manual" not in render_page(page)


def test_persona_validation(tmp_path):
    for bad in ("../x", "a/b", "", "."):
        with pytest.raises(WikiStoreError):
            WikiStore(tmp_path, bad)


def test_tags_roundtrip(store):
    """tags は書いた値のまま読み戻せる（render → parse も同値）。"""
    assert store.write_page(
        "journal-2026-11-09", title="記録", body="x", sources=("m1",), tags=("journal", "2026-11")
    ).is_ok
    page = store.read_page("journal-2026-11-09").value
    assert page.tags == ("journal", "2026-11")
    assert parse_page("s", render_page(page)).tags == page.tags


def test_invalid_tags_are_dropped(store):
    """strip + lower してから検証。大文字は正規化、記号・長すぎ・9 個目・重複は捨てる。"""
    long_tag = "a" * 25
    too_many = tuple(f"t{i}" for i in range(9))
    assert store.write_page(
        "p-tags", title="t", body="b", tags=("Journal", "bad tag!", long_tag, "ok_tag", *too_many)
    ).is_ok
    assert store.read_page("p-tags").value.tags == (
        "journal",
        "ok_tag",
        "t0",
        "t1",
        "t2",
        "t3",
        "t4",
        "t5",
    )


def test_empty_tags_emit_no_frontmatter_line(store):
    """tags 空なら ``tags:`` 行は出さない（既存ページの形を変えない）。"""
    assert store.write_page("p-plain", title="t", body="b").is_ok
    raw = (store.root / "p-plain.md").read_text(encoding="utf-8")
    assert "tags:" not in raw
    assert store.read_page("p-plain").value.tags == ()


def test_index_keeps_recent_journals_in_own_section(store):
    """日記は通常ページの枠を食い潰さず、専用節に直近分だけ並ぶ。"""
    store.write_page("project-nous", title="NOUS", body="x", project="nous")
    for day in range(1, 12):
        store.write_page(f"journal-2026-11-{day:02d}", title=f"2026-11-{day:02d} の記録", body="y")

    index = store.read_page(INDEX_SLUG).value.body
    assert "## 日記" in index
    assert "[[journal-2026-11-11]]" in index  # 新しい順に載る
    assert "[[journal-2026-11-01]]" not in index  # 7 件を超えた分は畳む
    assert "他 4 日分" in index
    assert "[[project-nous]]" in index


def test_history_records_each_write_and_delete(store):
    """書込み・削除の前版が履歴に残り、新しい順にメタだけ返る（本文は含めない）。"""
    store.write_page("p-hist", title="v1", body="one")
    store.write_page("p-hist", title="v2", body="two")
    store.write_page("p-hist", title="v3", body="three")

    revisions = store.history("p-hist")
    assert [r["title"] for r in revisions] == ["v2", "v1"]  # 現在版(v3)の前版から
    assert revisions[0]["action"] == "write"
    assert revisions[1]["action"] == "create"  # 初版も戻せる
    assert "body" not in revisions[0]

    assert store.delete_page("p-hist").is_ok
    assert store.history("p-hist")[0]["action"] == "delete"


def test_restore_revision_writes_back_and_keeps_new_entry(store):
    """過去の版に戻すと本文が戻り、戻した操作自体も履歴に残る（1 段戻しではなく追記型）。"""
    store.write_page("p-restore", title="v1", body="old body", sources=("k1",))
    rev = store.history("p-restore")[0]["rev"]  # 初版(create)
    store.write_page("p-restore", title="v2", body="new body")

    restored = store.restore_revision("p-restore", rev)
    assert restored.is_ok
    current = store.read_page("p-restore").value
    assert current.body == "old body"
    assert current.sources == ("k1",)
    # 戻し先の版 + 直前版(v2) が履歴に並ぶ
    assert [r["title"] for r in store.history("p-restore")] == ["v2", "v1"]


def test_restore_missing_revision_is_failure(store):
    store.write_page("p-miss", title="v1", body="b")
    assert not store.restore_revision("p-miss", 999).is_ok


def test_written_page_is_writable_by_the_sandbox_user(store, tmp_path):
    """nous（root）が置いたページを、別 uid の sandbox が編集できること。

    実機で /home/agent と .agents が root 所有になり書けなかったのと同じ種類の穴。
    wiki は rw マウントで persona が書く場所なので、置いた後に 0666 へ落とす。
    """
    import stat

    assert store.write_page("project-nous", title="NOUS", body="本文").is_ok

    page = tmp_path / "persona" / "herta" / "wiki" / "project-nous.md"
    assert stat.S_IMODE(page.stat().st_mode) == 0o666


def test_symlinked_page_is_rejected(store, tmp_path):
    """wiki はペルソナが 0777 で書ける。symlink を置かれても辿らない。

    辿ると nous（root）の権限で他ペルソナの file を読めてしまう。
    """
    victim = tmp_path / "persona" / "other" / "db" / "memory.sqlite"
    victim.parent.mkdir(parents=True)
    victim.write_text("secret")
    store.root.mkdir(parents=True, exist_ok=True)
    (store.root / "leak.md").symlink_to(victim)

    assert not store.read_page("leak").is_ok
    assert "leak" not in store.list_slugs()


def test_history_stays_private_to_nous(store, tmp_path):
    """履歴は nous しか書かない。dir も 0755 のまま（dir に write があると file mode は無意味）。

    dir がペルソナに書けると .jsonl を差し替えて版を偽造できる。
    """
    import stat

    assert store.write_page("page", title="t", body="b").is_ok

    hist = tmp_path / "persona" / "herta" / "wiki" / "_history" / "page.jsonl"
    assert stat.S_IMODE(hist.stat().st_mode) == 0o644
    assert stat.S_IMODE(hist.parent.stat().st_mode) == 0o755


def test_symlinked_wiki_dir_is_not_written_through(store, tmp_path):
    """_purged やネスト slug の親 dir を symlink にされても、その先へ書かない。"""
    victim_dir = tmp_path / "persona" / "other" / "wiki"
    victim_dir.mkdir(parents=True)
    store.root.mkdir(parents=True, exist_ok=True)
    (store.root / "_purged").symlink_to(victim_dir)

    from nous.infrastructure.wiki.store import WikiStoreError, write_shared

    with pytest.raises(WikiStoreError):
        write_shared(store.root / "_purged" / "gists.jsonl", "x")


def test_nested_slug_through_symlinked_dir_returns_failure(store):
    """ネスト slug の親 dir が symlink でも、例外を投げず Failure で返す。

    ペルソナは wiki を 0777 で書けるので `ln -s . wiki/sub` を置ける。
    WikiStoreError が write_page を貫通すると 500 になる。
    """
    store.root.mkdir(parents=True, exist_ok=True)
    (store.root / "sub").symlink_to(store.root)

    assert not store.write_page("sub/x", title="t", body="b").is_ok
