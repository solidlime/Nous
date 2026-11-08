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


def _setup(tmp_path, memories: list[Memory], *, llm: str | None, raise_exc: Exception | None = None):
    """DB + worker を用意し、_compile_persona を 1 回実行する。"""
    conn = SQLiteConnection(data_dir=str(tmp_path), persona="test_ww")
    conn.initialize_schema()
    repo = SQLiteMemoryRepository(conn)
    for m in memories:
        repo.save(m)
    ctx = SimpleNamespace(memory_repo=repo, connection=conn)
    worker = WikiWorker(_settings(tmp_path))
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
        """source 記憶が archived になった topic は記憶数に関わらず先頭に来る。"""
        memories = [_mem(f"big{i}", tags=["project:big"]) for i in range(6)]
        memories += [_mem(f"small{i}", tags=["project:small"]) for i in range(3)]
        memories += [_mem("small-arch", tags=["project:small"], lifecycle="archived")]

        store = _store(tmp_path)
        # small 側のページが archived 記憶を source に持つ → stale
        store.write_page(
            "project-small-page", "Small", "archived を根拠にしている。", project="small", sources=("small-arch",)
        )

        worker = WikiWorker(_settings(tmp_path))
        worker._cfg = worker._cfg.model_copy(update={"topics_per_cycle": 2})
        slugs = [s for s, _ in worker._select_topics(memories, get_now(), store, "test_ww")]

        assert slugs[0] == "project-small"
        assert "project-big" in slugs


class TestManualPages:
    def test_manual_page_is_not_overwritten(self, tmp_path) -> None:
        """ダッシュボードで手書きされたページ（manual: true）は編纂で上書きしない。"""
        memories = [_mem(f"a{i}", tags=["project:nous"]) for i in range(3)]
        store = _store(tmp_path)
        store.write_page(
            "project-nous-memory",
            "ユーザーが書いた題名",
            "手書き本文（編纂に潰されないこと）",
            project="nous",
            sources=("a0",),
            manual=True,
        )
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
            assert stored.value.manual is True
            assert stored.value.title == "ユーザーが書いた題名"
            assert stored.value.body == "手書き本文（編纂に潰されないこと）"
            summaries = [s for t, s in _event_rows(conn)]
            assert any("manual page kept" in s for s in summaries), summaries
        finally:
            conn.close()

    def test_manual_page_survives_consolidation_delete(self, tmp_path) -> None:
        """編纂の delete 指示でも手書きページは消さない（統合の犠牲にしない）。"""
        memories = [_mem(f"a{i}", tags=["project:nous"]) for i in range(3)]
        store = _store(tmp_path)
        store.write_page(
            "project-nous-notes",
            "手書きノート",
            "消えては困る本文",
            project="nous",
            sources=("a0",),
            manual=True,
        )
        page = {
            "slug": "project-nous-overview",
            "title": "Nous 概要",
            "body": "統合後の本文",
            "sources": ["a0", "a1"],
            "delete": ["project-nous-notes"],
        }
        conn, _ = _setup(tmp_path, memories, llm=_pages_json(page))
        try:
            kept = _store(tmp_path).read_page("project-nous-notes")
            assert isinstance(kept, Success), "manual ページが delete 指示で消えた"
            assert kept.value.body == "消えては困る本文"
            summaries = [s for t, s in _event_rows(conn)]
            assert any("kept project-nous-notes: manual page" in s for s in summaries), summaries
        finally:
            conn.close()
