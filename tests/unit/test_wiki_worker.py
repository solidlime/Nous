"""WikiWorker tests — ドリーミング（wiki 編纂）の topic 選択・ページ適用・監査記録。

計画書 ``docs/superpowers/plans/2026-11-07-wiki-dreaming.md`` §4.2:
- SELECT: active のみ、project:* タグでクラスタ化、無タグは persona、MIN_TOPIC_MEMORIES 未満は除外
- 適用: slug は topic 配下のみ、sources は候補 key 以外を捨て、空なら拒否、body 上限で拒否
- LLM 失敗・不正 JSON → 例外が外に漏れずファイル無変化、session_events に error 行
- ページ適用毎に session_events へ 1 行（type=wiki.compiled, detail に page_hash）

Qdrant 索引は worker.vector_enabled=False で無効化（LLM 同様、外部依存を分離）。
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import MagicMock

from nous.application.workers.wiki_worker import MIN_TOPIC_MEMORIES, WikiWorker
from nous.domain.memory.entities import Memory
from nous.domain.shared.result import Success
from nous.domain.shared.time_utils import get_now
from nous.infrastructure.sqlite.connection import SQLiteConnection
from nous.infrastructure.sqlite.memory_repo import SQLiteMemoryRepository
from nous.infrastructure.wiki.store import WikiStore


def _mem(key: str, *, tags: list[str] | None = None, lifecycle: str = "active", content: str | None = None) -> Memory:
    now = get_now()
    return Memory(
        key=key,
        content=content or f"{key} のテスト記憶内容。wiki 編纂の対象となる本文。",
        created_at=now,
        updated_at=now,
        importance=0.6,
        kind="semantic",
        source_type="user_stated",
        lifecycle_status=lifecycle,
        tags=tags or [],
    )


def _settings(tmp_path) -> MagicMock:
    """本物の WikiConfig を持つ settings stub（data_root は tmp_path、LLM/Qdrant は未使用）。"""
    from nous.config.settings import WikiConfig

    s = MagicMock()
    s.wiki = WikiConfig(enabled=True)
    s.data_root = str(tmp_path)
    return s


def _setup(
    tmp_path,
    memories: list[Memory],
    *,
    llm: str | None,
    raise_exc: Exception | None = None,
    cfg_update: dict | None = None,
):
    """DB + worker を用意し、_compile_persona を 1 回実行する。"""
    conn = SQLiteConnection(data_dir=str(tmp_path), persona="test_ww")
    conn.initialize_schema()
    repo = SQLiteMemoryRepository(conn)
    for m in memories:
        repo.save(m)
    ctx = SimpleNamespace(memory_repo=repo, connection=conn)
    worker = WikiWorker(_settings(tmp_path))
    if cfg_update:
        worker._cfg = worker._cfg.model_copy(update=cfg_update)
    worker.vector_enabled = False
    worker._ask_llm_for_test = llm  # type: ignore[attr-defined]
    worker._ask_llm_raise = raise_exc  # type: ignore[attr-defined]
    worker._compile_persona(ctx, "test_ww")
    return conn, worker


def _pages_json(*pages: dict) -> str:
    return json.dumps({"pages": list(pages)}, ensure_ascii=False)


def _store(tmp_path) -> WikiStore:
    return WikiStore(tmp_path, "test_ww")


def _event_rows(conn) -> list[tuple[str, str]]:
    rows = conn.get_memory_db().execute("SELECT event_type, summary FROM session_events ORDER BY id").fetchall()
    return [(r["event_type"], r["summary"]) for r in rows]


# ---------------------------------------------------------------------------
# SELECT
# ---------------------------------------------------------------------------


class TestSelectTopics:
    def test_groups_by_project_tag_and_persona(self, tmp_path) -> None:
        """project:* タグでクラスタ化、無タグは persona クラスタ。"""
        memories = [
            _mem("a1", tags=["project:nous", "x"]),
            _mem("a2", tags=["project:nous"]),
            _mem("a3", tags=["project:nous"]),
            _mem("b1"),
            _mem("b2"),
            _mem("b3"),
        ]
        conn, worker = _setup(tmp_path, memories, llm=None)
        try:
            topics = dict(worker._select_topics(memories, get_now(), _store(tmp_path), "test_ww"))
            assert set(topics) == {"project-nous", "persona"}
            assert {m.key for m in topics["project-nous"]} == {"a1", "a2", "a3"}
            assert {m.key for m in topics["persona"]} == {"b1", "b2", "b3"}
        finally:
            conn.close()

    def test_excludes_small_and_non_active_topics(self, tmp_path) -> None:
        """MIN_TOPIC_MEMORIES 未満の topic と非 active 記憶は対象外。"""
        memories = [_mem(f"a{i}", tags=["project:nous"]) for i in range(MIN_TOPIC_MEMORIES - 1)]
        memories += [_mem("arch", tags=["project:dotfiles"], lifecycle="archived") for _ in range(3)]
        conn, worker = _setup(tmp_path, memories, llm=None)
        try:
            assert worker._select_topics(memories, get_now(), _store(tmp_path), "test_ww") == []
        finally:
            conn.close()

    def test_caps_topics_per_cycle(self, tmp_path) -> None:
        """topics_per_cycle を超えるクラスタは件数上位のみ。"""
        memories = []
        for proj, n in (("p1", 5), ("p2", 4), ("p3", 3)):
            memories += [_mem(f"{proj}-{i}", tags=[f"project:{proj}"]) for i in range(n)]
        conn, worker = _setup(tmp_path, memories, llm=None)
        worker._cfg = worker._cfg.model_copy(update={"topics_per_cycle": 2})
        try:
            slugs = [s for s, _ in worker._select_topics(memories, get_now(), _store(tmp_path), "test_ww")]
            assert slugs == ["project-p1", "project-p2"]
        finally:
            conn.close()


# ---------------------------------------------------------------------------
# 適用
# ---------------------------------------------------------------------------


class TestApplyPages:
    def test_writes_page_and_records_event(self, tmp_path) -> None:
        """正常なページはファイルに書かれ、監査行が 1 行入る。"""
        memories = [_mem(f"a{i}", tags=["project:nous"]) for i in range(3)]
        page = {
            "slug": "project-nous-memory",
            "title": "NOUS の記憶設計",
            "body": "## 概要\n\n記憶は SQLite が正。[[project-nous-index]]",
            "sources": ["a0", "a1"],
        }
        conn, _ = _setup(tmp_path, memories, llm=_pages_json(page))
        try:
            stored = _store(tmp_path).read_page("project-nous-memory")
            assert isinstance(stored, Success)
            assert stored.value.title == "NOUS の記憶設計"
            assert stored.value.sources == ("a0", "a1")
            events = _event_rows(conn)
            assert events and events[0][0] == "wiki.compiled"
            assert "created project-nous-memory" in events[0][1]
        finally:
            conn.close()

    def test_rejects_foreign_slug_and_invalid_sources(self, tmp_path) -> None:
        """クラスタ外 slug と、候補外 key しか無い sources は拒否される。"""
        memories = [_mem(f"a{i}", tags=["project:nous"]) for i in range(3)]
        pages = _pages_json(
            {"slug": "other-page", "title": "x", "body": "y", "sources": ["a0"]},
            {"slug": "project-nous-ok", "title": "x", "body": "y", "sources": ["not-a-key"]},
        )
        conn, _ = _setup(tmp_path, memories, llm=pages)
        try:
            store = _store(tmp_path)
            assert not store.read_page("other-page").is_ok
            assert not store.read_page("project-nous-ok").is_ok
            summaries = [s for t, s in _event_rows(conn) if t == "wiki.compiled"]
            assert all(s.startswith("error:") for s in summaries)
        finally:
            conn.close()

    def test_rejects_oversized_body(self, tmp_path) -> None:
        """body が max_page_bytes を超えるページは書かれない。"""
        memories = [_mem(f"a{i}", tags=["project:nous"]) for i in range(3)]
        page = {"slug": "project-nous-big", "title": "x", "body": "あ" * 5000, "sources": ["a0"]}
        conn, worker = _setup(tmp_path, memories, llm=_pages_json(page))
        try:
            worker._cfg = worker._cfg.model_copy(update={"max_page_bytes": 100})
            # 2 周目で上限を効かせる（初回は既定 8192 で書かれてしまうため）
            conn2 = conn
            worker._compile_persona(
                SimpleNamespace(memory_repo=SimpleNamespace(find_all=lambda: _ok(memories)), connection=conn2),
                "test_ww",
            )
            assert not _store(tmp_path).read_page("project-nous-big").is_ok
        finally:
            conn.close()

    def test_update_replaces_and_deletes_old_page(self, tmp_path) -> None:
        """既存ページの改訂と、統合による旧ページ削除が反映される。"""
        memories = [_mem(f"a{i}", tags=["project:nous"]) for i in range(3)]
        store = _store(tmp_path)
        store.write_page("project-nous-old", "旧ページ", "旧本文", sources=("a0",))
        page = {
            "slug": "project-nous-new",
            "title": "統合ページ",
            "body": "統合した本文",
            "sources": ["a0", "a1", "a2"],
            "delete": ["project-nous-old"],
        }
        conn, _ = _setup(tmp_path, memories, llm=_pages_json(page))
        try:
            assert store.read_page("project-nous-new").is_ok
            assert not store.read_page("project-nous-old").is_ok
        finally:
            conn.close()


# ---------------------------------------------------------------------------
# 失敗時 fail-safe
# ---------------------------------------------------------------------------


class TestFailSafe:
    def test_llm_exception_leaves_files_and_records_error(self, tmp_path) -> None:
        """LLM 例外では例外が外に漏れず、ファイル無変化 + error 行。"""
        memories = [_mem(f"a{i}", tags=["project:nous"]) for i in range(3)]
        conn, _ = _setup(tmp_path, memories, llm=None, raise_exc=RuntimeError("boom"))
        try:
            assert _store(tmp_path).list_pages() == []
            summaries = [s for t, s in _event_rows(conn) if t == "wiki.compiled"]
            assert any(s.startswith("error:") for s in summaries)
        finally:
            conn.close()

    def test_invalid_json_records_error(self, tmp_path) -> None:
        """JSON でない応答は error 行のみ（ファイル無変化）。"""
        memories = [_mem(f"a{i}", tags=["project:nous"]) for i in range(3)]
        conn, _ = _setup(tmp_path, memories, llm="これは JSON ではない")
        try:
            assert _store(tmp_path).list_pages() == []
            summaries = [s for t, s in _event_rows(conn) if t == "wiki.compiled"]
            assert any("invalid llm response" in s for s in summaries)
        finally:
            conn.close()

    def test_disabled_does_nothing(self, tmp_path) -> None:
        """enabled=False では例外も書込みも起きない。"""
        s = MagicMock()
        from nous.config.settings import WikiConfig

        s.wiki = WikiConfig(enabled=False)
        s.data_root = str(tmp_path)
        WikiWorker(s).run_cycle()  # no contexts → 影響なし、例外なし


def _ok(value):
    from nous.domain.shared.result import Success

    return Success(value)


class TestIndexMaintenance:
    """§4.6-6: 索引維持 — dangling link の修復と stale topic の優先。"""

    def test_repairs_dangling_links(self, tmp_path) -> None:
        """存在しないページへの [[link]] はプレーンテキストへ落ちる。"""
        store = _store(tmp_path)
        store.write_page("project-nous-a", "A", "[[project-nous-ghost]] と [[project-nous-b]] を見よ。", project="nous")
        store.write_page("project-nous-b", "B", "本文 B。", project="nous")

        worker = WikiWorker(_settings(tmp_path))
        repaired = worker._repair_links(store)

        assert repaired == 1
        read = store.read_page("project-nous-a")
        assert read.is_ok
        body = read.value.body
        assert "[[project-nous-ghost]]" not in body
        assert "project-nous-ghost" in body
        # 実在リンクは残る
        assert "[[project-nous-b]]" in body

    def test_stale_topic_is_prioritized(self, tmp_path) -> None:
        """source 記憶が tombstoned になった topic は記憶数に関わらず先頭に来る。"""
        memories = [_mem(f"big{i}", tags=["project:big"]) for i in range(6)]
        memories += [_mem(f"small{i}", tags=["project:small"]) for i in range(3)]
        memories += [_mem("small-dead", tags=["project:small"], lifecycle="tombstoned")]

        store = _store(tmp_path)
        # small 側のページが tombstoned 記憶を source に持つ → stale
        store.write_page(
            "project-small-page", "Small", "tombstoned を根拠にしている。", project="small", sources=("small-dead",)
        )

        worker = WikiWorker(_settings(tmp_path))
        worker._cfg = worker._cfg.model_copy(update={"topics_per_cycle": 2})
        slugs = [s for s, _ in worker._select_topics(memories, get_now(), store, "test_ww")]

        assert slugs[0] == "project-small"
        assert "project-big" in slugs


class TestPagesAreUniform:
    """編集保護は廃止。旧 ``manual: true`` のページも編纂の通常対象になる。"""

    def _write_legacy_manual(self, tmp_path, slug: str, body: str, project: str = "nous") -> None:
        """手書き判定があった時代のファイルを再現する（旧 frontmatter 付き）。"""
        store = _store(tmp_path)
        path = store.wiki_dir() / f"{slug}.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            f"---\ntitle: ユーザーが書いた題名\nproject: {project}\nsources: a0\nmanual: true\n---\n\n{body}\n",
            encoding="utf-8",
        )
        store.rebuild_index()

    def test_legacy_manual_page_is_overwritten(self, tmp_path) -> None:
        """誤字修正のために手で書いたページも、編纂は普通に上書きする。"""
        memories = [_mem(f"a{i}", tags=["project:nous"]) for i in range(3)]
        self._write_legacy_manual(tmp_path, "project-nous-memory", "手で書いた本文")
        page = {
            "slug": "project-nous-memory",
            "title": "LLM が書き直した題名",
            "body": "LLM の本文",
            "sources": ["a0", "a1"],
        }
        conn, _ = _setup(tmp_path, memories, llm=_pages_json(page))
        try:
            stored = _store(tmp_path).read_page("project-nous-memory")
            assert isinstance(stored, Success)
            assert stored.value.title == "LLM が書き直した題名"
            assert stored.value.body == "LLM の本文"
            summaries = [s for t, s in _event_rows(conn)]
            assert not any("manual" in s for s in summaries), summaries
        finally:
            conn.close()

    def test_legacy_manual_page_is_deleted_by_consolidation(self, tmp_path) -> None:
        """統合の delete 指示は手書きだったページにも普通に効く。"""
        memories = [_mem(f"a{i}", tags=["project:nous"]) for i in range(3)]
        self._write_legacy_manual(tmp_path, "project-nous-notes", "消えてしまう本文")
        page = {
            "slug": "project-nous-overview",
            "title": "Nous 概要",
            "body": "統合後の本文",
            "sources": ["a0", "a1"],
            "delete": ["project-nous-notes"],
        }
        conn, _ = _setup(tmp_path, memories, llm=_pages_json(page))
        try:
            gone = _store(tmp_path).read_page("project-nous-notes")
            assert not gone.is_ok, "manual ページが編集保護で残ってしまった"
            summaries = [s for t, s in _event_rows(conn)]
            assert not any("manual" in s for s in summaries), summaries
        finally:
            conn.close()


class TestSourceArchiving:
    """編纂済みの源記憶を archived へ沈める（削除はしない）。"""

    def test_compile_archives_sources(self, tmp_path) -> None:
        """編纂に使われた source は archived になり、監査行に件数が入る。"""
        memories = [_mem(f"a{i}", tags=["project:nous"]) for i in range(3)]
        page = {
            "slug": "project-nous-memory",
            "title": "NOUS の記憶設計",
            "body": "本文",
            "sources": ["a0", "a1"],
        }
        conn, _ = _setup(tmp_path, memories, llm=_pages_json(page))
        try:
            repo = SQLiteMemoryRepository(conn)
            statuses = {k: repo.find_by_key(k).value.lifecycle_status for k in ("a0", "a1", "a2")}
            assert statuses["a0"] == "archived"
            assert statuses["a1"] == "archived"
            assert statuses["a2"] == "active", "編纂に使っていない記憶まで沈めてはいけない"
            detail = (
                conn.get_memory_db()
                .execute("SELECT detail FROM session_events WHERE event_type='wiki.compiled' ORDER BY id DESC LIMIT 1")
                .fetchone()["detail"]
            )
            assert json.loads(detail)["archived"] == 2
        finally:
            conn.close()

    def test_archive_sources_can_be_disabled(self, tmp_path) -> None:
        """設定で無効にしたら source は active のまま。"""
        memories = [_mem(f"a{i}", tags=["project:nous"]) for i in range(3)]
        page = {"slug": "project-nous-memory", "title": "T", "body": "本文", "sources": ["a0"]}
        conn, _ = _setup(tmp_path, memories, llm=_pages_json(page), cfg_update={"archive_sources": False})
        try:
            repo = SQLiteMemoryRepository(conn)
            assert repo.find_by_key("a0").value.lifecycle_status == "active"
        finally:
            conn.close()


class TestStaleDetection:
    def test_archived_source_does_not_make_topic_stale(self, tmp_path) -> None:
        """archived は意図的に沈めた状態。stale にすると毎サイクル再編纂の無限ループになる。"""
        memories = [
            _mem("a0", tags=["project:nous"], lifecycle="archived"),
            _mem("a1", tags=["project:nous"]),
            _mem("a2", tags=["project:nous"]),
        ]
        store = _store(tmp_path)
        store.write_page("project-nous-page", "T", "本文", project="nous", sources=("a0",))
        worker = WikiWorker(_settings(tmp_path))
        assert worker._stale_topics(store, memories, "test_ww") == set()

    def test_missing_or_tombstoned_source_is_stale(self, tmp_path) -> None:
        """source が消えた / tombstoned なら stale（ページが古い情報を持つ）。"""
        memories = [
            _mem("a0", tags=["project:nous"], lifecycle="tombstoned"),
            _mem("a1", tags=["project:nous"]),
        ]
        store = _store(tmp_path)
        store.write_page("project-nous-page", "T", "本文", project="nous", sources=("a0",))
        store.write_page("project-gone-page", "T", "本文", project="gone", sources=("zzz",))
        worker = WikiWorker(_settings(tmp_path))
        assert worker._stale_topics(store, memories, "test_ww") == {"project-nous", "project-gone"}


class TestTopicRotation:
    def test_never_compiled_topic_wins_over_big_cluster(self, tmp_path) -> None:
        """未編纂 topic は巨大クラスタより優先される（巡回ローテーション）。"""
        memories = [_mem(f"big{i}", tags=["project:big"]) for i in range(10)]
        memories += [_mem(f"small{i}", tags=["project:small"]) for i in range(3)]
        store = _store(tmp_path)
        # big は編纂済み、small は未編纂
        store.write_page("project-big-page", "Big", "本文", project="big", sources=("big0",))
        worker = WikiWorker(_settings(tmp_path))
        worker._cfg = worker._cfg.model_copy(update={"topics_per_cycle": 1})
        slugs = [s for s, _ in worker._select_topics(memories, get_now(), store, "test_ww")]
        assert slugs == ["project-small"]

    def test_oldest_compiled_goes_before_newer(self, tmp_path) -> None:
        """同条件なら最後に編纂されたのが古い topic から回る（frontmatter updated で順序を作る）。"""
        import re

        memories = [_mem(f"a{i}", tags=["project:a"]) for i in range(3)]
        memories += [_mem(f"b{i}", tags=["project:b"]) for i in range(3)]
        store = _store(tmp_path)
        store.write_page("project-a-page", "A", "本文", project="a", sources=("a0",))
        store.write_page("project-b-page", "B", "本文", project="b", sources=("b0",))
        # write_page は毎回 now を刻むので、frontmatter の updated を直接書き換えて順序を固定する
        for slug, stamp in (
            ("project-a-page", "2026-01-01T00:00:00+00:00"),
            ("project-b-page", "2026-01-02T00:00:00+00:00"),
        ):
            path = store.root / f"{slug}.md"
            path.write_text(
                re.sub(r"^updated:.*$", f"updated: {stamp}", path.read_text(encoding="utf-8"), count=1, flags=re.M),
                encoding="utf-8",
            )
        worker = WikiWorker(_settings(tmp_path))
        worker._cfg = worker._cfg.model_copy(update={"topics_per_cycle": 1})
        slugs = [s for s, _ in worker._select_topics(memories, get_now(), store, "test_ww")]
        assert slugs == ["project-a"]


class TestSchedule:
    def test_next_delay_targets_configured_hour(self, tmp_path) -> None:
        """run_at_hour 指定時は 0 < delay <= 24h（次の定刻まで）。"""
        worker = WikiWorker(_settings(tmp_path))
        worker._cfg = worker._cfg.model_copy(update={"run_at_hour": 3})
        delay = worker._next_delay()
        assert 0 < delay <= 86400

    def test_negative_hour_falls_back_to_interval(self, tmp_path) -> None:
        """run_at_hour<0 は旧来の interval 方式。"""
        worker = WikiWorker(_settings(tmp_path))
        worker._cfg = worker._cfg.model_copy(update={"run_at_hour": -1, "interval_seconds": 3600})
        assert worker._next_delay() == 3600


class TestCycleScopedArchive:
    """同じ source を 2 ページが引用しても、archive の計上は cycle 内で 1 回。"""

    def test_duplicate_source_counted_once(self, tmp_path) -> None:
        memories = [_mem(f"a{i}", tags=["project:nous"]) for i in range(3)]
        pages = _pages_json(
            {"slug": "project-nous-one", "title": "1", "body": "本文 1", "sources": ["a0"]},
            {"slug": "project-nous-two", "title": "2", "body": "本文 2", "sources": ["a0"]},
        )
        conn, _ = _setup(tmp_path, memories, llm=pages)
        try:
            details = [
                json.loads(r["detail"])
                for r in conn.get_memory_db()
                .execute("SELECT detail FROM session_events WHERE event_type='wiki.compiled' ORDER BY id")
                .fetchall()
            ]
            assert sum(d.get("archived", 0) for d in details) == 1
        finally:
            conn.close()


class TestRepairLinks:
    def test_repair_links_rewrites_page(self, tmp_path) -> None:
        """dangling link はプレーンテキスト化され、他の frontmatter は保たれる。"""
        store = _store(tmp_path)
        store.write_page(
            "project-nous-notes",
            "ノート",
            "[[project-nous-ghost]] を見よ。",
            project="nous",
            sources=("a0",),
        )
        worker = WikiWorker(_settings(tmp_path))
        assert worker._repair_links(store) == 1
        read = store.read_page("project-nous-notes")
        assert read.is_ok
        assert read.value.project == "nous"
        assert read.value.sources == ("a0",)
        assert "[[project-nous-ghost]]" not in read.value.body


class TestTopicSelectionAfterArchive:
    def test_topic_with_page_survives_archive_below_min_memories(self, tmp_path) -> None:
        """源を archive して active が 1 件になっても、ページのある topic は巡回対象に残る。"""
        memories = [_mem("a0", tags=["project:nous"]), _mem("a1", tags=["project:nous"])]
        store = _store(tmp_path)
        store.write_page("project-nous-page", "既存", "本文", project="nous", sources=("a0", "a1"))
        # 1 件だけ active に戻す（archive 相当）
        memories[1] = _mem("a1", tags=["project:nous"], lifecycle="archived")

        worker = WikiWorker(_settings(tmp_path))
        slugs = [s for s, _ in worker._select_topics(memories, get_now(), store, "test_ww")]
        assert "project-nous" in slugs
        # ページの無い topic は従来どおり下限で弾く
        lonely = [_mem("b0", tags=["project:lonely"])]
        assert worker._select_topics(lonely, get_now(), store, "test_ww") == []
