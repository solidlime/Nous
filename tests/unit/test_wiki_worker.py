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
from datetime import date, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

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


def _event_rows(conn) -> list[tuple[str, str, dict]]:
    """(event_type, summary, detail) を古い順に返す。detail は JSON を dict 化したもの。"""
    rows = conn.get_memory_db().execute("SELECT event_type, summary, detail FROM session_events ORDER BY id").fetchall()
    return [(r["event_type"], r["summary"], json.loads(r["detail"]) if r["detail"] else {}) for r in rows]


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
            summaries = [s for t, s, _d in _event_rows(conn) if t == "wiki.compiled"]
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
            summaries = [s for t, s, _d in _event_rows(conn) if t == "wiki.compiled"]
            assert any(s.startswith("error:") for s in summaries)
        finally:
            conn.close()

    def test_invalid_json_records_error(self, tmp_path) -> None:
        """JSON でない応答は error 行のみ（ファイル無変化）。"""
        memories = [_mem(f"a{i}", tags=["project:nous"]) for i in range(3)]
        conn, _ = _setup(tmp_path, memories, llm="これは JSON ではない")
        try:
            assert _store(tmp_path).list_pages() == []
            summaries = [s for t, s, _d in _event_rows(conn) if t == "wiki.compiled"]
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
            summaries = [s for t, s, _d in _event_rows(conn)]
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
            summaries = [s for t, s, _d in _event_rows(conn)]
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
    def test_default_tz_is_asia_tokyo(self) -> None:
        """既定が UTC に戻ったら落ちる（03:00 JST の意味を守る番人）。"""
        from nous.config.settings import WikiConfig

        assert WikiConfig().run_at_tz == "Asia/Tokyo"
        assert WikiConfig().run_at_hour == 3

    def test_unknown_tz_is_rejected_at_config_load(self) -> None:
        """未知の TZ 名は起動時に落ちる（無言の永久停止を防ぐ）。"""
        import pytest
        from pydantic import ValidationError

        from nous.config.settings import WikiConfig

        with pytest.raises(ValidationError):
            WikiConfig(run_at_tz="Mars/Olympus")

    def test_next_delay_targets_configured_hour(self, tmp_path) -> None:
        """run_at_hour 指定時は 0 < delay <= 24h（次の定刻まで）。"""
        worker = WikiWorker(_settings(tmp_path))
        worker._cfg = worker._cfg.model_copy(update={"run_at_hour": 3})
        delay = worker._next_delay()
        assert 0 < delay <= 86400

    def test_next_delay_uses_run_at_tz_not_container_tz(self, tmp_path, monkeypatch) -> None:
        """定刻は run_at_tz で解釈する（コンテナ TZ=UTC でも 03:00 JST が基準）。"""
        from datetime import datetime
        from zoneinfo import ZoneInfo

        import nous.domain.shared.time_utils as time_utils

        frozen = datetime(2026, 11, 9, 1, 0, tzinfo=ZoneInfo("Asia/Tokyo"))
        seen_tz: list[str | None] = []

        def _fake_get_now(tz: str | None = None) -> datetime:
            seen_tz.append(tz)
            return frozen.astimezone(ZoneInfo(tz or "Asia/Tokyo"))

        monkeypatch.setattr(time_utils, "get_now", _fake_get_now)
        worker = WikiWorker(_settings(tmp_path))
        worker._cfg = worker._cfg.model_copy(update={"run_at_hour": 3, "run_at_tz": "Asia/Tokyo"})
        assert worker._next_delay() == 2 * 3600  # 01:00 JST → 03:00 JST
        assert seen_tz == ["Asia/Tokyo"]

    def test_next_delay_wraps_to_next_day(self, tmp_path, monkeypatch) -> None:
        """定刻を過ぎていれば翌日（+86400）へ回る。"""
        from datetime import datetime
        from zoneinfo import ZoneInfo

        import nous.domain.shared.time_utils as time_utils

        frozen = datetime(2026, 11, 9, 4, 0, tzinfo=ZoneInfo("Asia/Tokyo"))
        monkeypatch.setattr(time_utils, "get_now", lambda tz=None: frozen)
        worker = WikiWorker(_settings(tmp_path))
        worker._cfg = worker._cfg.model_copy(update={"run_at_hour": 3, "run_at_tz": "Asia/Tokyo"})
        assert worker._next_delay() == 23 * 3600

    def test_unknown_tz_falls_back_without_raising(self, tmp_path) -> None:
        """設定検証をすり抜けた不正 TZ でも落ちず、UTC フォールバックで待ち時間を返す。"""
        worker = WikiWorker(_settings(tmp_path))
        worker._cfg = worker._cfg.model_copy(update={"run_at_hour": 3, "run_at_tz": "Mars/Olympus"})
        assert 0 < worker._next_delay() <= 86400

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


class TestLlmRetry:
    """空応答・切れ JSON は 1 回だけ予算を倍にして再試行する（2026-11-09 の本番障害）。"""

    _PAGE = {
        "slug": "project-nous-memory",
        "title": "NOUS の記憶設計",
        "body": "## 概要 記憶は SQLite が正。",
        "sources": ["a0", "a1"],
    }

    @staticmethod
    def _run(tmp_path, responses: list[str | None]):
        """_ask_llm を差し替えて _compile_persona を 1 回実行する。"""
        conn = SQLiteConnection(data_dir=str(tmp_path), persona="test_ww")
        conn.initialize_schema()
        repo = SQLiteMemoryRepository(conn)
        for i in range(3):
            repo.save(_mem(f"a{i}", tags=["project:nous"]))
        worker = WikiWorker(_settings(tmp_path))
        worker.vector_enabled = False
        seen: list[int] = []

        def _fake_ask_llm(*_args, **kwargs):
            boost = kwargs.get("boost", 0)
            seen.append(boost)
            resp = responses[len(seen) - 1]
            # 本番の _ask_llm と同じ計器を埋める（監査 detail の検証用）。
            worker._last_llm = {
                "max_tokens": 16000 * (2**boost),
                "text_len": len(resp or ""),
                "stream_error": resp is None,
            }
            return resp

        worker._ask_llm = _fake_ask_llm  # type: ignore[method-assign]
        worker._compile_persona(SimpleNamespace(memory_repo=repo, connection=conn), "test_ww")
        return conn, worker, seen

    def test_empty_response_retries_and_succeeds(self, tmp_path) -> None:
        conn, _w, seen = self._run(tmp_path, ["", _pages_json(self._PAGE)])
        try:
            assert seen == [0, 1]  # 2 回目は予算 2 倍（boost=1）
            assert _store(tmp_path).read_page("project-nous-memory").is_ok
            assert not [s for _t, s, _d in _event_rows(conn) if s.startswith("error:")]
            # 再試行で救ったことが監査に残る（無言の回復を作らない）
            recovered = [(s, d) for _t, s, d in _event_rows(conn) if s.startswith("recovered:")]
            assert len(recovered) == 1
            assert recovered[0][0] == "recovered: project-nous on attempt 2"
            assert recovered[0][1]["max_tokens"] == 32000
        finally:
            conn.close()

    def test_truncated_json_retries_and_succeeds(self, tmp_path) -> None:
        """本番と同じ「文字列の途中で切れた JSON」で再試行する。"""
        # 本文文字列の中に閉じ括弧を入れ、rfind("}") が文字列内を指す形にする
        # （本番の `Unterminated string starting at ... char 4153` と同じ経路）。
        truncated = (
            '{"pages": [{"slug": "project-nous-memory", "title": "NOUS の記憶設計", '
            '"body": "閉じ括弧 } を含む本文の途中'
        )
        conn, _w, seen = self._run(tmp_path, [truncated, _pages_json(self._PAGE)])
        try:
            assert seen == [0, 1]
            assert _store(tmp_path).read_page("project-nous-memory").is_ok
            assert not [s for _t, s, _d in _event_rows(conn) if s.startswith("error:")]
        finally:
            conn.close()

    def test_two_failures_record_single_error_event(self, tmp_path) -> None:
        conn, _w, seen = self._run(tmp_path, [None, None])
        try:
            assert seen == [0, 1]
            errors = [(s, d) for _t, s, d in _event_rows(conn) if s.startswith("error:")]
            assert len(errors) == 1
            msg, detail = errors[0]
            assert "llm stream error" in msg  # None は stream エラーとして区別
            # 監査 detail に「どの attempt で、いくつの予算で、何文字返ったか」が残る
            assert detail["attempt"] == 1
            assert detail["max_tokens"] == 32000
            assert detail["stream_error"] is True
            assert _store(tmp_path).list_pages() == []
        finally:
            conn.close()

    def test_stream_error_and_empty_text_are_distinguished(self, tmp_path) -> None:
        """collect_text の None（stream エラー）と ""（本文なし）を別の文言で残す。"""
        conn_none, _w1, _s1 = self._run(tmp_path / "a", [None, None])
        try:
            msg_none = [s for _t, s, _d in _event_rows(conn_none) if s.startswith("error:")][0]
        finally:
            conn_none.close()
        conn_empty, _w2, _s2 = self._run(tmp_path / "b", ["", ""])
        try:
            msg_empty = [s for _t, s, _d in _event_rows(conn_empty) if s.startswith("error:")][0]
        finally:
            conn_empty.close()
        assert "stream error" in msg_none
        assert "returned no text" in msg_empty
        assert "attempt 2" in msg_none and "attempt 2" in msg_empty

    def test_empty_payload_records_skip_event(self, tmp_path) -> None:
        """{"pages": []} で無言で抜けない（「動いているのに更新されない」を可視化する）。"""
        conn, _w, seen = self._run(tmp_path, ['{"pages": []}'])
        try:
            assert seen == [0]  # 成功扱いなので再試行しない
            skips = [s for _t, s, _d in _event_rows(conn) if s.startswith("skipped:")]
            assert skips == ["skipped: no pages returned for project-nous"]
        finally:
            conn.close()

    def test_bytes_budget_doubles_on_retry(self, tmp_path, monkeypatch) -> None:
        """retry の boost が実際の max_tokens（16000→32000）まで届くことを固定する。"""
        budgets: list[int] = []
        responses = ["", _pages_json(self._PAGE)]

        async def _fake_collect_text(_provider, **kwargs):
            budgets.append(kwargs["max_tokens"])
            return responses[len(budgets) - 1]

        import nous.infrastructure.llm.text_utils as text_utils

        monkeypatch.setattr(text_utils, "collect_text", _fake_collect_text)
        conn = SQLiteConnection(data_dir=str(tmp_path), persona="test_ww")
        conn.initialize_schema()
        repo = SQLiteMemoryRepository(conn)
        for i in range(3):
            repo.save(_mem(f"a{i}", tags=["project:nous"]))
        worker = WikiWorker(_settings(tmp_path))
        worker.vector_enabled = False
        worker._cfg = worker._cfg.model_copy(update={"api_key": "test-key"})
        try:
            worker._compile_persona(SimpleNamespace(memory_repo=repo, connection=conn), "test_ww")
            assert budgets == [16000, 32000]
            assert _store(tmp_path).read_page("project-nous-memory").is_ok
        finally:
            conn.close()


class TestErrorRetry:
    """失敗したサイクルは定刻を待たず短くリトライする（24h 空白の防止）。"""

    def test_error_event_increments_cycle_errors(self, tmp_path) -> None:
        conn = SQLiteConnection(data_dir=str(tmp_path), persona="test_ww")
        conn.initialize_schema()
        try:
            ctx = SimpleNamespace(connection=conn)
            worker = WikiWorker(_settings(tmp_path))
            worker._record_event(ctx, "test_ww", "error: llm returned no text for persona", None)
            worker._record_event(ctx, "test_ww", "created project-x from 5 memories", None)
            assert worker._cycle_errors == 1
        finally:
            conn.close()


# ---------------------------------------------------------------------------
# 日記（#38）
# ---------------------------------------------------------------------------

_JST = ZoneInfo("Asia/Tokyo")
_DAY = "2026-11-09"


def _mem_at(key: str, ts: datetime, *, lifecycle: str = "active") -> Memory:
    return Memory(
        key=key,
        content=f"{key} の記憶内容。日記の材料になる本文。",
        created_at=ts,
        updated_at=ts,
        importance=0.6,
        kind="semantic",
        source_type="user_stated",
        lifecycle_status=lifecycle,
        tags=[],
    )


def _journal_setup(
    tmp_path, memories: list[Memory], llm: str | None, raise_exc: Exception | None = None, cfg_update=None
):
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
    return conn, worker, ctx


class TestJournal:
    _now = datetime(2026, 11, 10, 3, 0, tzinfo=_JST)
    _body = "## やったこと\n\n- 日記のテストを書いた\n\n## 決めたこと\n\n- なし"

    def test_only_previous_jst_day_is_collected(self, tmp_path) -> None:
        """前日 JST の 00:01 と 23:59 だけ拾い、当日 00:01 と一昨日は落とす。"""
        memories = [
            _mem_at("old", datetime(2026, 11, 8, 23, 0, tzinfo=_JST)),
            _mem_at("late", datetime(2026, 11, 9, 23, 59, tzinfo=_JST)),
            _mem_at("early", datetime(2026, 11, 9, 0, 1, tzinfo=_JST)),
            _mem_at("today", datetime(2026, 11, 10, 0, 1, tzinfo=_JST)),
        ]
        conn, worker, ctx = _journal_setup(tmp_path, memories, self._body)
        try:
            worker._compile_journal(ctx, "test_ww", _store(tmp_path), self._now)
            page = _store(tmp_path).read_page(f"journal-{_DAY}").value
            assert page.sources == ("early", "late")  # created_at 昇順
            assert page.title == f"{_DAY} の記録"
            assert page.tags == ("journal", "2026-11")
            assert page.body.startswith("## やったこと")
            summaries = [s for _t, s, _d in _event_rows(conn)]
            assert f"created journal-{_DAY} from 2 memories" in summaries
        finally:
            conn.close()

    def test_no_memories_writes_nothing(self, tmp_path) -> None:
        """前日に記憶が無ければページも監査イベントも作らない。"""
        memories = [_mem_at("today", datetime(2026, 11, 10, 0, 1, tzinfo=_JST))]
        conn, worker, ctx = _journal_setup(tmp_path, memories, self._body)
        try:
            worker._compile_journal(ctx, "test_ww", _store(tmp_path), self._now)
            assert _store(tmp_path).list_slugs() == []
            assert [s for _t, s, _d in _event_rows(conn) if "journal" in s] == []
        finally:
            conn.close()

    def test_same_day_twice_keeps_one_page(self, tmp_path) -> None:
        """同日 2 回走っても slug は 1 つ（2 回目は updated）。"""
        memories = [_mem_at("a", datetime(2026, 11, 9, 10, 0, tzinfo=_JST))]
        conn, worker, ctx = _journal_setup(tmp_path, memories, self._body)
        store = _store(tmp_path)
        try:
            worker._compile_journal(ctx, "test_ww", store, self._now)
            worker._compile_journal(ctx, "test_ww", store, self._now)
            assert [s for s in store.list_slugs() if s.startswith("journal-")] == [f"journal-{_DAY}"]
            actions = [s.split()[0] for _t, s, _d in _event_rows(conn) if "journal-" in s]
            assert actions == ["created", "updated"]
        finally:
            conn.close()

    def test_sources_capped_by_config(self, tmp_path) -> None:
        """材料は journal_max_sources 件まで（created_at 昇順で先勝ち）。"""
        base = datetime(2026, 11, 9, 0, 0, tzinfo=_JST)
        memories = [_mem_at(f"m{i:02d}", base + timedelta(minutes=i)) for i in range(61)]
        conn, worker, ctx = _journal_setup(tmp_path, memories, self._body)
        try:
            worker._compile_journal(ctx, "test_ww", _store(tmp_path), self._now)
            page = _store(tmp_path).read_page(f"journal-{_DAY}").value
            assert len(page.sources) == 60
            assert page.sources[0] == "m00" and page.sources[-1] == "m59"
        finally:
            conn.close()

    def test_llm_failure_records_error_and_keeps_cycle_alive(self, tmp_path) -> None:
        """LLM 失敗は error 行を残し、ページは作らない（例外は外に漏らさない）。"""
        memories = [_mem_at("a", datetime(2026, 11, 9, 10, 0, tzinfo=_JST))]
        conn, worker, ctx = _journal_setup(tmp_path, memories, None, raise_exc=RuntimeError("boom"))
        try:
            worker._compile_journal(ctx, "test_ww", _store(tmp_path), self._now)
            assert _store(tmp_path).list_slugs() == []
            assert f"error: journal {_DAY}: boom" in [s for _t, s, _d in _event_rows(conn)]
        finally:
            conn.close()

    def test_prompt_has_fixed_headings_and_short_hint(self, tmp_path) -> None:
        memories = [_mem_at(f"m{i}", datetime(2026, 11, 9, 10, 0, tzinfo=_JST)) for i in range(2)]
        conn, worker, _ctx = _journal_setup(tmp_path, memories, self._body)
        try:
            prompt = worker._build_journal_prompt(date(2026, 11, 9), memories, [], self._now)
            for heading in (
                "## やったこと",
                "## 感想",
                "## 決めたこと",
                "## 引っかかったこと",
                "## 未解決",
            ):
                assert heading in prompt
            assert "材料に無い事実は書かない" in prompt
            assert "短く書く" in prompt
            six = memories * 3
            assert "短く書く" not in worker._build_journal_prompt(date(2026, 11, 9), six, [], self._now)
        finally:
            conn.close()

    def test_state_applied_to_persona(self, tmp_path) -> None:
        """2 回目の呼び出しの JSON で感情・体調を 1 回だけ反映する。"""
        memories = [_mem_at("a", datetime(2026, 11, 9, 10, 0, tzinfo=_JST))]
        conn, worker, ctx = _journal_setup(tmp_path, memories, None)
        service = _fake_service()
        ctx.persona_service = service
        worker._ask_text = _fake_llm([self._body, _STATE_JSON])  # type: ignore[method-assign]
        try:
            worker._compile_journal(ctx, "test_ww", _store(tmp_path), self._now)
            assert _store(tmp_path).read_page(f"journal-{_DAY}").is_ok
            service.update_emotion.assert_called_once_with("test_ww", "happy", 0.8, context=f"journal:journal-{_DAY}")
            assert service.update_physical_state.call_args.kwargs == {
                "physical_state": "落ち着いている",
                "mental_state": "集中している",
                "fatigue": 0.3,
            }
            # 監査は「保存された値」を書く（happy は normalize_emotion で joy になる）
            assert "applied state emotion=joy intensity=0.8" in [s for _t, s, _d in _event_rows(conn)]
        finally:
            conn.close()

    def test_state_can_be_disabled(self, tmp_path) -> None:
        """journal_apply_state=False なら状態反映も LLM 呼び出しもしない。"""
        memories = [_mem_at("a", datetime(2026, 11, 9, 10, 0, tzinfo=_JST))]
        conn, worker, ctx = _journal_setup(tmp_path, memories, None, cfg_update={"journal_apply_state": False})
        service = _fake_service()
        ctx.persona_service = service
        worker._ask_text = _fake_llm([self._body, _STATE_JSON])  # type: ignore[method-assign]
        try:
            worker._compile_journal(ctx, "test_ww", _store(tmp_path), self._now)
            service.update_emotion.assert_not_called()
            service.update_physical_state.assert_not_called()
            assert [s for _t, s, _d in _event_rows(conn) if "applied state" in s] == []
        finally:
            conn.close()

    def test_state_empty_response_updates_nothing(self, tmp_path) -> None:
        """状態推定が空/非 JSON なら何もしない（error 行も出さない）。"""
        memories = [_mem_at("a", datetime(2026, 11, 9, 10, 0, tzinfo=_JST))]
        conn, worker, ctx = _journal_setup(tmp_path, memories, None)
        service = _fake_service()
        ctx.persona_service = service
        worker._ask_text = _fake_llm([self._body, ""])  # type: ignore[method-assign]
        try:
            worker._compile_journal(ctx, "test_ww", _store(tmp_path), self._now)
            service.update_emotion.assert_not_called()
            assert [s for _t, s, _d in _event_rows(conn) if "journal state" in s] == []
        finally:
            conn.close()

    def test_state_failure_does_not_stop_cycle(self, tmp_path) -> None:
        """状態反映が落ちても日記は残り、error 行だけが増える。"""
        memories = [_mem_at("a", datetime(2026, 11, 9, 10, 0, tzinfo=_JST))]
        conn, worker, ctx = _journal_setup(tmp_path, memories, None)
        service = _fake_service()
        service.update_emotion.side_effect = RuntimeError("db down")
        ctx.persona_service = service
        worker._ask_text = _fake_llm([self._body, _STATE_JSON])  # type: ignore[method-assign]
        try:
            worker._compile_journal(ctx, "test_ww", _store(tmp_path), self._now)
            assert _store(tmp_path).read_page(f"journal-{_DAY}").is_ok
            summaries = [s for _t, s, _d in _event_rows(conn)]
            # 日記本体は成功しているので cycle 失敗には数えない（warning 扱い）
            assert f"warning: journal state journal-{_DAY}: db down" in summaries
        finally:
            conn.close()


_STATE_JSON = json.dumps(
    {
        "emotion": "happy",
        "emotion_intensity": 0.8,
        "physical_state": "落ち着いている",
        "mental_state": "集中している",
        "body_state": {"fatigue": 0.3},
    },
    ensure_ascii=False,
)


def _fake_service() -> MagicMock:
    service = MagicMock()
    service.update_emotion.return_value = Success(None)
    service.update_physical_state.return_value = Success(None)
    return service


def _fake_llm(responses: list[str]):
    seq = list(responses)

    def ask(prompt: str, boost: int = 0) -> str:
        return seq.pop(0) if seq else ""

    return ask


class TestJournalIsolation:
    """日記が topic 編纂の巡回・プロンプト・削除に混ざらないこと（静かに壊れる箇所の番人）。"""

    _now = datetime(2026, 11, 10, 3, 0, tzinfo=_JST)

    def _seed_journal(self, tmp_path) -> WikiStore:
        store = _store(tmp_path)
        store.write_page(
            "journal-2026-11-09",
            "2026-11-09 の記録",
            "## やったこと\n\n- 日記",
            sources=("a",),
            tags=("journal", "2026-11"),
        )
        return store

    def test_last_compiled_ignores_journal(self, tmp_path) -> None:
        """日記は topic の「編纂済み」判定に入らない（入ると topic が巡回から落ちる）。"""
        store = self._seed_journal(tmp_path)
        store.write_page("project-nous-x", "x", "body", project="nous", sources=("m1",))
        conn, worker, _ctx = _journal_setup(tmp_path, [], None)
        try:
            assert "journal-2026-11-09" not in worker._last_compiled(store)
            assert set(worker._last_compiled(store)) == {"project-nous"}
        finally:
            conn.close()

    def test_stale_topics_ignores_journal(self, tmp_path) -> None:
        """日記の sources が消えても stale 扱いにしない。"""
        store = self._seed_journal(tmp_path)
        conn, worker, _ctx = _journal_setup(tmp_path, [], None)
        try:
            assert worker._stale_topics(store, [], "test_ww") == set()
        finally:
            conn.close()

    def test_build_prompt_excludes_journal_pages(self, tmp_path) -> None:
        """topic 編纂プロンプトに日記の slug が載らない（token が日数分だけ膨らむ）。"""
        store = self._seed_journal(tmp_path)
        store.write_page("project-nous-x", "x", "body", project="nous", sources=("m1",))
        conn, worker, _ctx = _journal_setup(tmp_path, [], None)
        try:
            prompt = worker._build_prompt("project-nous", [], store.list_pages(), self._now)
            assert "journal-2026-11-09" not in prompt
            assert "project-nous-x" in prompt
        finally:
            conn.close()

    def test_delete_ignores_journal_slug(self, tmp_path) -> None:
        """LLM が delete に日記を入れても消えない（slug 接頭辞ガード）。"""
        store = self._seed_journal(tmp_path)
        conn, worker, ctx = _journal_setup(tmp_path, [], None)
        candidate = _mem("src", tags=["project:nous"])
        page = {
            "slug": "project-nous-x",
            "title": "x",
            "body": "body",
            "sources": ["src"],
            "delete": ["journal-2026-11-09"],
        }
        try:
            worker._apply_page(
                ctx,
                "test_ww",
                store,
                "project-nous",
                page,
                {"src": candidate},
                {"journal-2026-11-09", "project-nous-x"},
                set(),
            )
            assert store.read_page("journal-2026-11-09").is_ok
        finally:
            conn.close()

    def test_compile_persona_runs_journal_first(self, tmp_path) -> None:
        """日記 → topic の順（逆だと topic が sources を archived に沈めて日記が痩せる）。"""
        memories = [_mem_at("a", datetime(2026, 11, 9, 10, 0, tzinfo=_JST))]
        memory_topic = [_mem_at(f"p{i}", datetime(2026, 11, 9, 11, 0, tzinfo=_JST)) for i in range(3)]
        for m in memory_topic:
            m.tags = ["project:zzz"]
        conn, worker, ctx = _journal_setup(tmp_path, memories + memory_topic, None)
        order: list[str] = []
        worker._compile_journal = lambda *a, **k: order.append("journal")  # type: ignore[method-assign]
        worker._compile_topic = lambda *a, **k: order.append("topic")  # type: ignore[method-assign]
        worker._repair_links = lambda *a, **k: order.append("repair") or 0  # type: ignore[method-assign]
        worker._cfg = worker._cfg.model_copy(update={"journal_enabled": True})
        try:
            worker._cfg = worker._cfg.model_copy(update={"min_memories_per_topic": 3})
            worker._compile_persona(ctx, "test_ww")
            assert order and order[0] == "journal" and order[-1] == "repair"
        finally:
            conn.close()

    def test_body_budget_leaves_room_for_frontmatter(self, tmp_path) -> None:
        """sources が多くてもページが書ける（本文予算 = max_page_bytes - frontmatter 実測）。"""
        base = datetime(2026, 11, 9, 0, 0, tzinfo=_JST)
        memories = [_mem_at(f"memory_key_{i:03d}", base + timedelta(minutes=i)) for i in range(60)]
        body = "x" * 7000
        conn, worker, ctx = _journal_setup(tmp_path, memories, body)
        try:
            worker._compile_journal(ctx, "test_ww", _store(tmp_path), self._now)
            page = _store(tmp_path).read_page("journal-2026-11-09")
            assert page.is_ok, page.error if hasattr(page, "error") else "write failed"
        finally:
            conn.close()


class TestStripCodeFence:
    def test_text_after_closing_fence_is_dropped(self) -> None:
        """閉じフェンスの後ろの説明文は本文に混ぜない。"""
        from nous.application.workers.wiki_worker import _strip_code_fence

        raw = "```markdown\n## やったこと\n\n- x\n```\n以上の通りです。"
        assert _strip_code_fence(raw) == "## やったこと\n\n- x"

    def test_unclosed_fence_keeps_body(self) -> None:
        """閉じフェンスが無ければ全部本文（途中で切れた応答でも書ける）。"""
        from nous.application.workers.wiki_worker import _strip_code_fence

        assert _strip_code_fence("```markdown\n## やったこと\n- x") == "## やったこと\n- x"

    def test_no_fence_is_returned_stripped(self) -> None:
        from nous.application.workers.wiki_worker import _strip_code_fence

        assert _strip_code_fence("  ## やったこと\n- x \n") == "## やったこと\n- x"


class TestJournalStateInstrumentation:
    _now = datetime(2026, 11, 10, 3, 0, tzinfo=_JST)
    _body = "## やったこと\n\n- 日記"

    def test_no_persona_service_records_skip(self, tmp_path) -> None:
        """persona_service が無いときは黙って何もしないのではなく 1 行残す。"""
        memories = [_mem_at("a", datetime(2026, 11, 9, 10, 0, tzinfo=_JST))]
        conn, worker, ctx = _journal_setup(tmp_path, memories, self._body)
        worker._ask_text = _fake_llm([self._body])  # type: ignore[method-assign]
        try:
            worker._compile_journal(ctx, "test_ww", _store(tmp_path), self._now)
            summaries = [s for _t, s, _d in _event_rows(conn)]
            assert "skipped: journal state (no persona_service)" in summaries
        finally:
            conn.close()

    def test_state_failure_is_not_a_cycle_error(self, tmp_path) -> None:
        """状態反映の失敗で cycle を失敗扱いにしない（30 分後の無駄な再挑戦を避ける）。"""
        memories = [_mem_at("a", datetime(2026, 11, 9, 10, 0, tzinfo=_JST))]
        conn, worker, ctx = _journal_setup(tmp_path, memories, None)
        service = _fake_service()
        service.update_emotion.side_effect = RuntimeError("db down")
        ctx.persona_service = service
        worker._ask_text = _fake_llm([self._body, _STATE_JSON])  # type: ignore[method-assign]
        try:
            worker._compile_journal(ctx, "test_ww", _store(tmp_path), self._now)
            assert worker._cycle_errors == 0
        finally:
            conn.close()


class TestRetryScheduling:
    def test_failed_cycle_retries_soon_instead_of_next_day(self, tmp_path) -> None:
        """失敗があったら翌日まで待たず、短い再挑戦間隔で回し直す（例外で日を捨てない）。"""
        worker = WikiWorker(_settings(tmp_path))
        worker._cfg = worker._cfg.model_copy(update={"run_at_hour": 3})
        worker._error_retry_seconds = 0.01
        worker._empty_retries = 0
        planned: list[float] = []

        def fake_next_delay() -> float:
            # 1 回目は即実行、2 回目以降は「翌日」を返す（再挑戦がこれを無視することを見る）。
            planned.append(1.0 if planned else 0.0)
            return 86400.0 if len(planned) > 1 else 0.0

        worker._next_delay = fake_next_delay  # type: ignore[method-assign]
        calls: list[int] = []

        def run_cycle() -> None:
            calls.append(len(calls))
            if len(calls) == 1:
                worker._cycle_errors = 1  # 1 周目は失敗したことにする
            else:
                worker._stop_event.set()  # 2 周目で止める

        worker.run_cycle = run_cycle  # type: ignore[method-assign]
        worker._run()
        assert len(calls) == 2
        assert len(planned) == 1  # 再挑戦では定刻を引き直さない


# ---------------------------------------------------------------------------
# 日記の営み（#46: その日の会話ログを材料に足す）
# ---------------------------------------------------------------------------


def _sess_event(conn, event_type: str, ts: datetime, detail: dict, persona: str = "test_ww") -> None:
    """session_events に 1 行入れる（pi hook と同じ形）。"""
    from nous.domain.memory.session_event import SessionEvent
    from nous.infrastructure.sqlite.session_event_repo import SessionEventRepository

    SessionEventRepository(conn).insert(
        SessionEvent(
            session_id="s1",
            persona=persona,
            event_type=event_type,
            timestamp=ts,
            summary="x",
            detail=json.dumps(detail, ensure_ascii=False),
        )
    )


class TestJournalActivity:
    _now = datetime(2026, 11, 10, 3, 0, tzinfo=_JST)
    _day = date(2026, 11, 9)
    _body = "## 活動\n\n- 11:36 起きた\n\n## やったこと\n\n- 直した"

    def test_collects_only_that_jst_day_in_time_order(self, tmp_path) -> None:
        """前日 JST の 2 件だけを時刻昇順で。前日 23:00・当日 00:10 は落とす。"""
        conn, worker, ctx = _journal_setup(tmp_path, [], self._body)
        try:
            _sess_event(conn, "turn.completed", datetime(2026, 11, 9, 15, 20, tzinfo=_JST), {"user_text": "お菓子作り"})
            _sess_event(conn, "turn.completed", datetime(2026, 11, 9, 11, 36, tzinfo=_JST), {"user_text": "起きた"})
            _sess_event(conn, "turn.completed", datetime(2026, 11, 8, 23, 0, tzinfo=_JST), {"user_text": "前の日"})
            _sess_event(conn, "turn.completed", datetime(2026, 11, 10, 0, 10, tzinfo=_JST), {"user_text": "翌日"})
            activity = worker._journal_activity(ctx, "test_ww", self._day, self._now)
            lines = activity.splitlines()
            assert [line[:6] for line in lines] == ["- 11:3", "- 15:2"]
            assert "お菓子作り" in activity
            assert "前の日" not in activity and "翌日" not in activity
        finally:
            conn.close()

    def test_place_moved_query_uses_small_limit(self, tmp_path) -> None:
        """移動の取得は独立の上限（会話行の予算を食い潰さない）。"""
        conn, worker, ctx = _journal_setup(tmp_path, [], self._body)
        try:
            worker._cfg = worker._cfg.model_copy(update={"journal_activity_max_events": 400})
            with patch(
                "nous.infrastructure.sqlite.session_event_repo.SessionEventRepository.get_by_persona",
                return_value=[],
            ) as get:
                worker._journal_activity(ctx, "test_ww", self._day, self._now)
            limits = {c.kwargs["event_type"]: c.kwargs["limit"] for c in get.call_args_list if "event_type" in c.kwargs}
            assert limits["place.moved"] == 50
            assert limits["turn.completed"] == 400
        finally:
            conn.close()

    def test_place_moved_becomes_activity_line(self, tmp_path) -> None:
        """移動は日記の材料になる（`place.moved` を無視すると移動が全部消える）。"""
        conn, worker, ctx = _journal_setup(tmp_path, [], self._body)
        try:
            _sess_event(
                conn,
                "place.moved",
                datetime(2026, 11, 9, 9, 5, tzinfo=_JST),
                {"from": "自室", "to": "観測デッキ", "minutes": 10},
            )
            activity = worker._journal_activity(ctx, "test_ww", self._day, self._now)
            assert "09:05" in activity and "観測デッキ へ移動" in activity
        finally:
            conn.close()

    def test_session_started_becomes_activity_line(self, tmp_path) -> None:
        conn, worker, ctx = _journal_setup(tmp_path, [], self._body)
        try:
            _sess_event(
                conn,
                "session.started",
                datetime(2026, 11, 9, 9, 5, tzinfo=_JST),
                {"name": "Nous開発", "project": "nous"},
            )
            activity = worker._journal_activity(ctx, "test_ww", self._day, self._now)
            assert "09:05" in activity and "Nous開発" in activity
        finally:
            conn.close()

    def test_activity_only_day_still_writes_journal(self, tmp_path) -> None:
        """記憶 0 件でも営みがあれば日記を作る（sources は空）。"""
        conn, worker, ctx = _journal_setup(tmp_path, [], self._body)
        try:
            _sess_event(conn, "turn.completed", datetime(2026, 11, 9, 15, 20, tzinfo=_JST), {"user_text": "お菓子作り"})
            worker._compile_journal(ctx, "test_ww", _store(tmp_path), self._now)
            page = _store(tmp_path).read_page(f"journal-{_DAY}").value
            assert page.sources == ()
            assert [s for _t, s, _d in _event_rows(conn) if "journal-" in s] == [
                f"created journal-{_DAY} from 0 memories"
            ]
        finally:
            conn.close()

    def test_no_memories_and_no_activity_writes_nothing(self, tmp_path) -> None:
        conn, worker, ctx = _journal_setup(tmp_path, [], self._body)
        try:
            worker._compile_journal(ctx, "test_ww", _store(tmp_path), self._now)
            assert not _store(tmp_path).read_page(f"journal-{_DAY}").is_ok
            assert [s for _t, s, _d in _event_rows(conn) if "journal" in s] == []
        finally:
            conn.close()

    def test_activity_chars_cap_is_respected(self, tmp_path) -> None:
        """材料は合計 journal_activity_chars を超えない。溢れる日は等間隔に抜く。"""
        conn, worker, ctx = _journal_setup(tmp_path, [], self._body, cfg_update={"journal_activity_chars": 400})
        try:
            for i in range(10):
                _sess_event(
                    conn,
                    "turn.completed",
                    datetime(2026, 11, 9, 10, i, tzinfo=_JST),
                    {"user_text": "あ" * 200},
                )
            activity = worker._journal_activity(ctx, "test_ww", self._day, self._now)
            lines = activity.splitlines()
            assert len(activity) <= 400 + len(lines)  # 改行分の余裕だけ許す
            # 等間隔に抜くので、先頭と末尾（朝と夜）は残る。
            assert lines[0].startswith("- 10:00 ")
            assert lines[-1].startswith("- 10:09 ")
        finally:
            conn.close()

    def test_disabled_returns_empty(self, tmp_path) -> None:
        conn, worker, ctx = _journal_setup(tmp_path, [], self._body, cfg_update={"journal_include_activity": False})
        try:
            _sess_event(conn, "turn.completed", datetime(2026, 11, 9, 11, 36, tzinfo=_JST), {"user_text": "起きた"})
            assert worker._journal_activity(ctx, "test_ww", self._day, self._now) == ""
        finally:
            conn.close()

    def test_prompt_has_activity_first_and_forbids_invented_places(self, tmp_path) -> None:
        conn, worker, _ctx = _journal_setup(tmp_path, [], self._body)
        try:
            prompt = worker._build_journal_prompt(self._day, [], [], self._now, activity="- 11:36 起きた")
            assert prompt.index("## 活動") < prompt.index("## やったこと")
            assert "材料に書かれていない設定は書かない" in prompt
            assert "- 11:36 起きた" in prompt
            # 省略条件は見出し単位（日単位にすると材料が少ない日に空見出しを並べる）。
            assert "各見出しは、その見出しに書ける材料が無ければ省略してよい" in prompt
            # 営みが無い日は「(なし)」を渡す（見出しの省略をプロンプトが許す）。
            assert "(なし)" in worker._build_journal_prompt(self._day, [], [], self._now, activity="")
        finally:
            conn.close()

    def test_naive_and_aware_timestamps_do_not_crash(self, tmp_path) -> None:
        """naive（API が timestamp 省略時に datetime.now() で書く）と aware の混在で落ちない。"""
        conn, worker, ctx = _journal_setup(tmp_path, [], self._body)
        try:
            # 2026-11-09 15:20 JST = 06:20 UTC。naive は JST ローカルとして扱う想定。
            _sess_event(conn, "turn.completed", datetime(2026, 11, 9, 15, 20, tzinfo=_JST), {"user_text": "お菓子作り"})
            _sess_event(conn, "turn.completed", datetime(2026, 11, 9, 11, 36), {"user_text": "起きた"})
            activity = worker._journal_activity(ctx, "test_ww", self._day, self._now)
            assert "お菓子作り" in activity and "起きた" in activity
        finally:
            conn.close()

    def test_session_started_without_detail_is_dropped(self, tmp_path) -> None:
        """情報ゼロの「セッション開始」行で営みの枠を埋めない。"""
        conn, worker, ctx = _journal_setup(tmp_path, [], self._body)
        try:
            _sess_event(conn, "session.started", datetime(2026, 11, 9, 9, 5, tzinfo=_JST), {})
            assert worker._journal_activity(ctx, "test_ww", self._day, self._now) == ""
        finally:
            conn.close()


class TestNoTopicSilence:
    """#45: 編纂対象 0 件のときに「何もしなかった」を 1 行残す。"""

    def test_records_skipped_and_never_calls_llm(self, tmp_path) -> None:
        conn, worker = _setup(tmp_path, [], llm=None, raise_exc=RuntimeError("llm must not be called"))
        try:
            summaries = [s for _t, s, _d in _event_rows(conn)]
            skips = [s for s in summaries if s.startswith("skipped: no topic")]
            assert len(skips) == 1, summaries
            assert "memories=0" in skips[0]
        finally:
            conn.close()

    def test_counts_excluded_memories(self, tmp_path) -> None:
        """全部 archived なら excluded に数える（区別のため）。"""
        memories = [_mem(f"a{i}", tags=["project:nous"], lifecycle="archived") for i in range(3)]
        conn, _worker = _setup(tmp_path, memories, llm=None)
        try:
            skips = [s for _t, s, _d in _event_rows(conn) if s.startswith("skipped: no topic")]
            assert len(skips) == 1
            assert "memories=3" in skips[0] and "excluded=3" in skips[0]
        finally:
            conn.close()


class TestPromptRevisionContext:
    """#44: ページ本文と源記憶を文脈に戻さないと「現在形の嘘」が残る。"""

    _now = datetime(2026, 11, 13, 3, 0, tzinfo=_JST)

    def test_topic_page_gets_full_body_and_other_topic_gets_preview(self, tmp_path) -> None:
        """編纂対象 topic のページだけ全文（page_body_chars まで）を渡す。"""
        from nous.infrastructure.wiki.store import WikiStore

        store = WikiStore(tmp_path, "test_ww")
        long_body = "冒頭の説明。" + ("埋め草" * 400) + "末尾の古い記述。"
        store.write_page("project-nous-x", "x", long_body, project="nous", sources=("m1",))
        store.write_page("project-other-y", "y", long_body, project="other", sources=("m2",))
        conn, worker, _ctx = _journal_setup(tmp_path, [], None)
        try:
            prompt = worker._build_prompt("project-nous", [], store.list_pages(), self._now)
        finally:
            conn.close()
        assert "末尾の古い記述" in prompt  # 400 字プレビューでは落ちる位置
        assert '"slug": "project-other-y"' in prompt
        assert "preview" in prompt  # 別 topic はプレビューのまま

    def test_memories_carry_their_day(self, tmp_path) -> None:
        """記憶に when（書かれた日）を付ける。無いと LLM は新旧を判断できない。"""
        conn, worker, _ctx = _journal_setup(tmp_path, [], None)
        try:
            prompt = worker._build_prompt("project-nous", [_mem("m1")], [], self._now)
        finally:
            conn.close()
        assert '"when": "' in prompt

    def test_cited_archived_memories_come_back(self, tmp_path) -> None:
        """ページが引用している archived 記憶を文脈に戻す（バケツ対応）。"""
        from nous.infrastructure.wiki.store import WikiStore

        store = WikiStore(tmp_path, "test_ww")
        store.write_page("project-nous-x", "x", "body", project="nous", sources=("old1", "old2", "gone"))
        conn, worker, _ctx = _journal_setup(tmp_path, [], None)
        try:
            cycle = [_mem("new1", tags=["project:nous"])]
            by_key = {
                "new1": cycle[0],
                "old1": _mem("old1", lifecycle="archived", content="manual を廃止した。"),
                "old2": _mem("old2", lifecycle="archived", content="タグを足した。"),
            }
            merged = worker._topic_memories(cycle, store.list_pages(), "project-nous", by_key)
            keys = {m.key for m in merged}
            assert keys == {"new1", "old1", "old2"}  # gone は存在しないので落ちる
        finally:
            conn.close()

    def test_tombstoned_and_other_topic_memories_stay_out(self, tmp_path) -> None:
        """tombstoned は戻さない。別 topic のページが引用する記憶も戻さない。"""
        from nous.infrastructure.wiki.store import WikiStore

        store = WikiStore(tmp_path, "test_ww")
        store.write_page("project-nous-x", "x", "body", project="nous", sources=("dead",))
        store.write_page("project-other-y", "y", "body", project="other", sources=("foreign",))
        conn, worker, _ctx = _journal_setup(tmp_path, [], None)
        try:
            cycle = [_mem("new1", tags=["project:nous"])]
            by_key = {
                "new1": cycle[0],
                "dead": _mem("dead", lifecycle="tombstoned"),
                "foreign": _mem("foreign", lifecycle="archived"),
            }
            merged = worker._topic_memories(cycle, store.list_pages(), "project-nous", by_key)
            assert {m.key for m in merged} == {"new1"}
        finally:
            conn.close()

    def test_revision_budget_caps_restored_memories(self, tmp_path) -> None:
        """revision_source_memories を超えて戻さない（プロンプト膨張の歯止め）。"""
        from nous.infrastructure.wiki.store import WikiStore

        store = WikiStore(tmp_path, "test_ww")
        store.write_page("project-nous-x", "x", "body", project="nous", sources=tuple(f"old{i}" for i in range(10)))
        conn, worker, _ctx = _journal_setup(tmp_path, [], None, cfg_update={"revision_source_memories": 2})
        try:
            cycle = [_mem("new1", tags=["project:nous"])]
            by_key = {"new1": cycle[0], **{f"old{i}": _mem(f"old{i}", lifecycle="archived") for i in range(10)}}
            merged = worker._topic_memories(cycle, store.list_pages(), "project-nous", by_key)
            assert len(merged) == 3  # new1 + 2
        finally:
            conn.close()

    def test_restored_memories_survive_the_topic_cap(self, tmp_path) -> None:
        """cycle 記憶が上限を埋めていても、戻した源記憶は落ちない（#44 の本丸）。"""
        from nous.infrastructure.wiki.store import WikiStore

        store = WikiStore(tmp_path, "test_ww")
        store.write_page("project-nous-x", "x", "body", project="nous", sources=("old1",))
        conn, worker, _ctx = _journal_setup(
            tmp_path, [], None, cfg_update={"max_memories_per_topic": 3, "revision_source_memories": 1}
        )
        try:
            cycle = [_mem(f"new{i}", tags=["project:nous"]) for i in range(5)]
            by_key = {"old1": _mem("old1", lifecycle="archived"), **{m.key: m for m in cycle}}
            merged = worker._topic_memories(cycle, store.list_pages(), "project-nous", by_key)
            keys = {m.key for m in merged}
            assert "old1" in keys
            assert len(merged) == 3
        finally:
            conn.close()

    def test_archiving_already_archived_sources_is_not_counted(self, tmp_path) -> None:
        """戻した archived 源を「新たに沈めた」と数えない（監査が嘘をつく）。"""
        conn, worker, ctx = _journal_setup(tmp_path, [], None)
        try:
            ctx.memory_repo.save(_mem("old1", lifecycle="archived"))
            known = {"old1": _mem("old1", lifecycle="archived")}
            assert worker._archive_sources(ctx, ["old1"], set(), known) == 0
            ctx.memory_repo.save(_mem("fresh", lifecycle="active"))
            assert worker._archive_sources(ctx, ["fresh"], set(), {"fresh": _mem("fresh")}) == 1
        finally:
            conn.close()

    def test_page_words_pull_back_old_uncited_memory(self, tmp_path) -> None:
        """本文にしか無い語（manual など）で、引用されていない古い記憶を掘り起こす。

        実例（#44, 2026-11-13 本番）: `project-nous-wiki-compilation` は
        「巡回順は…（manual 含む）」と書いたままだが、manual 廃止の記憶は
        どのページの sources にも無く、cycle の直近 40 件からも外れていた。
        """
        from nous.infrastructure.wiki.store import WikiStore

        store = WikiStore(tmp_path, "test_ww")
        store.write_page(
            "project-nous-wiki-compilation",
            "Wiki 編纂",
            "巡回順は stale → 最終接触が古い順（manual 含む）→ 記憶数。",
            project="nous",
            sources=(),
        )
        conn, worker, _ctx = _journal_setup(tmp_path, [], None)
        try:
            old = _mem("old_manual", lifecycle="archived", content="手書き判定 manual は廃止した。")
            older = _mem("old_manual", tags=["project:nous"], lifecycle="archived", content=old.content)
            cycle = [_mem(f"new{i}", tags=["project:nous"], content=f"別件の開発メモ{i}") for i in range(40)]
            by_key = {"old_manual": older, **{m.key: m for m in cycle}}
            merged = worker._topic_memories(cycle, store.list_pages(), "project-nous", by_key)
            assert "old_manual" in {m.key for m in merged}
        finally:
            conn.close()

    def test_recall_ignores_other_topics_and_tombstones(self, tmp_path) -> None:
        """掘り起こしは同じ topic の生きた記憶だけ。"""
        conn, worker, _ctx = _journal_setup(tmp_path, [], None)
        try:
            foreign = _mem("foreign", tags=["project:other"], content="manual の話。")
            dead = _mem("dead", tags=["project:nous"], content="manual の話。", lifecycle="tombstoned")
            got = worker._recall_by_text("manual を含む巡回", {"foreign": foreign, "dead": dead}, "project-nous")
            assert got == []
        finally:
            conn.close()
