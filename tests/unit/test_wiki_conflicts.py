"""矛盾整理（#39）のテスト。

計画書 ``docs/superpowers/plans/2026-11-10-journal-conflicts-and-research.md`` §3.3 / §4.2:

- 編纂応答の ``conflicts`` / ``questions`` は追加 LLM 呼び出しなしで処理する
- ``resolved=false`` と ``questions`` は ``open-question`` タグの記憶になる（重複は 1 件）
- 記憶層の掃除は候補抽出が純関数（LLM 0 回）、判定は ``memory_conflict_max_pairs`` で打ち切る

このファイルは**ネットワークに出ない**。矛盾判定の provider は必ず fake。
"""

from __future__ import annotations

import json
from dataclasses import replace
from types import SimpleNamespace
from typing import Any

import pytest

from nous.application.wiki.conflict_sweep import find_candidate_pairs, jaccard, numbers, tokens
from nous.application.workers.wiki_worker import WikiWorker
from nous.config.settings import WikiConfig
from nous.domain.memory.entities import Memory
from nous.domain.shared.result import Failure
from nous.domain.shared.time_utils import get_now
from nous.infrastructure.llm.base import TextDeltaEvent
from nous.infrastructure.sqlite.connection import SQLiteConnection
from nous.infrastructure.sqlite.memory_repo import SQLiteMemoryRepository

# ----------------------------------------------------------------------
# ヘルパ
# ----------------------------------------------------------------------


class FakeProvider:
    """``stream()`` だけを持つ fake provider。呼ばれた回数と応答を差し替えられる。"""

    def __init__(self, reply: str = "", *, fail: bool = False) -> None:
        self.reply = reply
        self.fail = fail
        self.calls = 0

    async def stream(self, **_: Any):  # noqa: ANN201 — テスト用の最小実装
        self.calls += 1
        if self.fail:
            raise RuntimeError("boom")
        if self.reply:
            yield TextDeltaEvent(content=self.reply)


def _contradictory_reply(key: str) -> str:
    return json.dumps({"type": "CONTRADICTORY", "existing_key": key, "explanation": "数値が違う"})


class FakeMemoryService:
    """``create_memory`` を repo へ直書きする最小実装（重複検索などの重い経路は踏まない）。"""

    def __init__(self, repo: SQLiteMemoryRepository, *, fail: Exception | None = None) -> None:
        self._repo = repo
        self._fail = fail
        self.calls = 0

    async def create_memory(self, content: str = "", tags=None, **kwargs):  # noqa: ANN001, ANN201
        self.calls += 1
        if self._fail is not None:
            return Failure(self._fail)
        now = get_now()
        memory = Memory(
            key=f"q{self.calls}_{abs(hash(content)) % 100000}",
            content=content,
            created_at=now,
            updated_at=now,
            importance=0.6,
            kind="semantic",
            source_type="user_stated",
            lifecycle_status="active",
            tags=list(tags or []),
        )
        result = self._repo.save(memory)
        return result


def _mem(
    key: str,
    content: str,
    *,
    tags: list[str] | None = None,
    lifecycle: str = "active",
    created_at=None,
) -> Memory:
    now = created_at or get_now()
    return Memory(
        key=key,
        content=content,
        created_at=now,
        updated_at=now,
        importance=0.6,
        kind="semantic",
        source_type="user_stated",
        lifecycle_status=lifecycle,
        tags=tags or [],
    )


def _settings(tmp_path, **wiki_update) -> SimpleNamespace:
    """本物の WikiConfig を持つ settings stub。

    既定で ``conflict_sweep_enabled=False`` にして、wiki 層のテストから週次掃除の
    LLM 経路を踏まないようにする（掃除のテストは明示的に有効化する）。
    """
    params = {"enabled": True, "conflict_sweep_enabled": False, **wiki_update}
    wiki = WikiConfig(**params)
    s = SimpleNamespace(
        wiki=wiki,
        data_root=str(tmp_path),
        openrouter_api_key="",
        anthropic_api_key="",
        openai_api_key="",
        google_api_key="",
        opencode_go_api_key="",
    )
    return s


def _compile(tmp_path, memories: list[Memory], llm: str, *, settings=None, **cfg_update):
    """DB + worker を用意して ``_compile_persona`` を 1 回実行する。"""
    conn = SQLiteConnection(data_dir=str(tmp_path), persona="test_wc")
    conn.initialize_schema()
    repo = SQLiteMemoryRepository(conn)
    for m in memories:
        repo.save(m)
    ctx = SimpleNamespace(memory_repo=repo, connection=conn, memory_service=FakeMemoryService(repo))
    worker = WikiWorker(settings or _settings(tmp_path))
    if cfg_update:
        worker._cfg = worker._cfg.model_copy(update=cfg_update)
    worker.vector_enabled = False
    worker._ask_llm_for_test = llm  # type: ignore[attr-defined]
    worker._compile_persona(ctx, "test_wc")
    return conn, repo, worker


def _open_questions(repo: SQLiteMemoryRepository) -> list[Memory]:
    result = repo.find_all()
    return [m for m in result.value if "open-question" in (m.tags or [])]


def _events(conn, event_type: str | None = None) -> list[tuple[str, str, dict]]:
    rows = conn.get_memory_db().execute("SELECT event_type, summary, detail FROM session_events ORDER BY id").fetchall()
    out = [(r["event_type"], r["summary"], json.loads(r["detail"]) if r["detail"] else {}) for r in rows]
    if event_type is None:
        return out
    return [row for row in out if row[0] == event_type]


def _page(slug: str, sources: list[str], body: str | None = None) -> dict:
    return {
        "slug": slug,
        "title": slug.replace("-", " ").title(),
        "body": body or f"## 概要\n{slug} の本文。",
        "sources": sources,
    }


# ----------------------------------------------------------------------
# 候補抽出（純関数・LLM を呼ばない）
# ----------------------------------------------------------------------


def test_tokens_numbers_jaccard_helpers():
    assert "blender" in tokens("Blender 4.2 で作成")
    assert numbers("毎朝 30 分、最終 4.2 秒") == {"30", "4.2"}
    assert jaccard({"a", "b"}, {"b", "c"}) == 1 / 3


def test_numbers_ignore_dates():
    """日付や時刻は「食い違う数値」として扱わない（誤爆防止）。"""
    assert numbers("2026-11-09 に計測") == numbers("2026-11-10 に計測")


def test_candidate_pairs_need_same_project_and_number_conflict():
    base = "レンダリングは毎晩 30 分かかる設定で運用している"
    memories = [
        _mem("a1", base + "（blender 4.2）", tags=["project:headshrink"]),
        _mem("a2", base + "（blender 4.2、所要 45 分）", tags=["project:headshrink"]),
        # 数値が同じ → 候補外
        _mem("b1", "同じ内容 30 分（作業1）", tags=["project:headshrink"]),
        _mem("b2", "同じ内容 30 分（作業2）", tags=["project:headshrink"]),
        # project タグ無し → 候補外
        _mem("c1", "タグ無しの記憶 30 分"),
        _mem("c2", "タグ無しの記憶 45 分"),
    ]
    pairs = find_candidate_pairs(memories, min_jaccard=0.5)
    keys = {(newer.key, older.key) for newer, older, _sim in pairs}
    assert ("a2", "a1") in keys
    assert all(k != "c1" and k != "c2" for pair in keys for k in pair)


def test_candidate_pairs_include_archived_but_skip_tombstoned_and_closed():
    """編纂で sources 消化された ``archived`` は対象。tombstone と窓を閉じたものは除く。"""
    memories = [
        _mem("arch_a", "サーバーは 8 GB で運用している", tags=["project:x"], lifecycle="archived"),
        _mem("arch_b", "サーバーは 16 GB で運用している", tags=["project:x"], lifecycle="archived"),
        _mem("dead", "サーバーは 32 GB で運用している", tags=["project:x"], lifecycle="tombstoned"),
        _mem("open", "プールは 4 本で運用している", tags=["project:x"]),
        _mem("closed", "プールは 8 本で運用している", tags=["project:x"]),
    ]
    memories[4].valid_until = get_now()  # 既に閉じた窓
    pairs = find_candidate_pairs(memories, min_jaccard=0.4)
    keys = {(newer.key, older.key) for newer, older, _sim in pairs}
    # archived 同士は拾う
    assert ("arch_b", "arch_a") in keys or ("arch_a", "arch_b") in keys
    # tombstoned / 閉じた窓は候補に入らない
    assert all("dead" not in pair and "closed" not in pair for pair in keys)


def test_candidate_pairs_respect_limit():
    memories = [_mem(f"k{i}", f"同じ文面 30 分 その{i}番目の記録", tags=["project:y"]) for i in range(6)]
    pairs = find_candidate_pairs(memories, min_jaccard=0.3, limit=3)
    assert len(pairs) == 3


# ----------------------------------------------------------------------
# hermetic 性（本番エンドポイントに触らない）
# ----------------------------------------------------------------------


def test_compile_never_builds_a_provider(tmp_path, monkeypatch):
    """編纂経路は LLM を ``_ask_llm_for_test`` で差し替えるので provider を作らない。

    掃除の provider 構築も ``_provider_for_test`` で塞がっていることを、factory を
    例外にして確かめる（ここが通らなければテストが実ネットワークを叩いている）。
    """
    from nous.infrastructure.llm import factory as llm_factory

    def _boom(*args, **kwargs):
        raise AssertionError(f"get_provider must not be called from tests: {args}")

    monkeypatch.setattr(llm_factory, "get_provider", _boom)

    memories = [_mem(f"m{i}", f"記憶 {i} の本文（project nous の作業ログ）", tags=["project:nous"]) for i in range(3)]
    payload = {"pages": [_page("project-nous-arch", ["m0", "m1", "m2"])]}
    _compile(tmp_path, memories, json.dumps(payload, ensure_ascii=False))

    # 掃除は有効化したうえで provider を差し替え、factory を通らないことを確認
    worker, conn, repo = _sweep_worker(tmp_path / "sweep", provider=FakeProvider(_contradictory_reply("a")))
    pairs_memories = [
        _mem("a", "レンダリングは 30 分で回している", tags=["project:x"]),
        _mem("b", "レンダリングは 45 分で回している", tags=["project:x"]),
    ]
    for m in pairs_memories:
        repo.save(m)
    worker._sweep_memory_conflicts(
        SimpleNamespace(memory_repo=repo, connection=conn, memory_service=FakeMemoryService(repo)),
        "test_sw",
        pairs_memories,
        get_now(),
    )


# ----------------------------------------------------------------------
# wiki 層: conflicts / questions
# ----------------------------------------------------------------------


def test_open_conflict_and_question_recorded_once(tmp_path):
    memories = [_mem(f"m{i}", f"記憶 {i} の本文（project nous の作業ログ）", tags=["project:nous"]) for i in range(3)]
    payload = {
        "pages": [_page("project-nous-arch", ["m0", "m1", "m2"])],
        "conflicts": [
            {
                "a": "project-nous-arch",
                "b": "project-nous-arch",
                "kind": "value",
                "detail": "再試行回数が違う",
                "resolved": False,
            }
        ],
        "questions": [{"query": "litellm の上限は？", "why": "設計に効く", "topic": "project-nous-arch"}],
    }
    conn, repo, _ = _compile(tmp_path, memories, json.dumps(payload, ensure_ascii=False))

    questions = _open_questions(repo)
    assert len(questions) == 2  # 未解決の矛盾 1 件 + 問い 1 件
    tags = {t for m in questions for t in (m.tags or [])}
    assert "open-question" in tags
    assert "project:nous" in tags  # ページの frontmatter project から引く

    conflict_events = _events(conn, "wiki.conflict")
    assert any("conflict open" in s for _, s, _ in conflict_events)
    assert any("question recorded" in s for _, s, _ in conflict_events)


def test_resolved_conflict_records_no_memory(tmp_path):
    memories = [_mem(f"m{i}", f"記憶 {i} の本文（project nous の作業ログ）", tags=["project:nous"]) for i in range(3)]
    payload = {
        "pages": [_page("project-nous-arch", ["m0", "m1", "m2"])],
        "conflicts": [{"a": "project-nous-arch", "b": "project-nous-arch", "detail": "直した", "resolved": True}],
    }
    conn, repo, _ = _compile(tmp_path, memories, json.dumps(payload, ensure_ascii=False))
    assert _open_questions(repo) == []
    assert any("conflict resolved" in s for _, s, _ in _events(conn, "wiki.conflict"))


def test_persona_question_has_no_project_tag(tmp_path):
    """persona クラスタのページから来た問いに幻の ``project:persona`` を付けない。"""
    memories = [_mem(f"p{i}", f"記憶 {i} の本文（タグ無し）") for i in range(3)]
    payload = {
        "pages": [_page("persona-state", ["p0", "p1", "p2"])],
        "questions": [{"query": "今の課題は？", "topic": "persona-state"}],
    }
    _, repo, _ = _compile(tmp_path, memories, json.dumps(payload, ensure_ascii=False))
    questions = _open_questions(repo)
    assert len(questions) == 1
    assert [t for t in questions[0].tags if t.startswith("project:")] == []


def test_open_question_is_deduped_across_cycles(tmp_path):
    memories = [_mem(f"m{i}", f"記憶 {i} の本文（project nous の作業ログ）", tags=["project:nous"]) for i in range(3)]
    payload = {
        "pages": [_page("project-nous-arch", ["m0", "m1", "m2"])],
        "questions": [{"query": "同じ質問", "why": "同じ理由"}],
    }
    conn, repo, _ = _compile(tmp_path, memories, json.dumps(payload, ensure_ascii=False))
    assert len(_open_questions(repo)) == 1

    worker = WikiWorker(_settings(tmp_path))
    worker.vector_enabled = False
    worker._ask_llm_for_test = json.dumps(payload, ensure_ascii=False)  # type: ignore[attr-defined]
    ctx2 = SimpleNamespace(memory_repo=repo, connection=conn, memory_service=FakeMemoryService(repo))
    worker._compile_persona(ctx2, "test_wc")
    assert len(_open_questions(repo)) == 1


def test_question_failure_is_audited_not_swallowed(tmp_path):
    """``create_memory`` が Failure を返したら監査に理由を残す（無言にしない）。"""
    memories = [_mem(f"m{i}", f"記憶 {i} の本文（project nous の作業ログ）", tags=["project:nous"]) for i in range(3)]
    payload = {"pages": [_page("project-nous-arch", ["m0", "m1", "m2"])], "questions": [{"query": "失敗する問い"}]}

    conn = SQLiteConnection(data_dir=str(tmp_path), persona="test_wc")
    conn.initialize_schema()
    repo = SQLiteMemoryRepository(conn)
    for m in memories:
        repo.save(m)

    ctx = SimpleNamespace(
        memory_repo=repo,
        connection=conn,
        memory_service=FakeMemoryService(repo, fail=RuntimeError("DuplicateMemoryError: too similar")),
    )
    worker = WikiWorker(_settings(tmp_path))
    worker.vector_enabled = False
    worker._ask_llm_for_test = json.dumps(payload, ensure_ascii=False)  # type: ignore[attr-defined]
    worker._compile_persona(ctx, "test_wc")

    assert _open_questions(repo) == []
    warnings = [s for _, s, _ in _events(conn, "wiki.conflict") if s.startswith("warning: open question not recorded")]
    assert warnings, "failure must leave an audit trail"


def test_conflict_with_unknown_slug_is_dropped(tmp_path):
    memories = [_mem(f"m{i}", f"記憶 {i} の本文（project nous の作業ログ）", tags=["project:nous"]) for i in range(3)]
    payload = {
        "pages": [_page("project-nous-arch", ["m0", "m1", "m2"])],
        "conflicts": [{"a": "ghost-page", "b": "project-nous-arch", "detail": "幻覚", "resolved": False}],
    }
    conn, repo, _ = _compile(tmp_path, memories, json.dumps(payload, ensure_ascii=False))
    assert _open_questions(repo) == []
    assert any("unknown page ghost-page" in s for _, s, _ in _events(conn, "wiki.conflict"))


def test_conflict_referencing_page_deleted_in_same_cycle_is_dropped(tmp_path):
    """同サイクルで delete したページは known から外す。"""
    memories = [_mem(f"m{i}", f"記憶 {i} の本文（project nous の作業ログ）", tags=["project:nous"]) for i in range(3)]
    page = _page("project-nous-arch", ["m0", "m1", "m2"])
    page["delete"] = ["project-nous-old"]
    payload = {
        "pages": [page],
        "conflicts": [{"a": "project-nous-old", "b": "project-nous-arch", "detail": "消したページ", "resolved": False}],
    }
    conn, repo, _ = _compile(tmp_path, memories, json.dumps(payload, ensure_ascii=False))
    assert _open_questions(repo) == []
    assert any("unknown page project-nous-old" in s for _, s, _ in _events(conn, "wiki.conflict"))


def test_missing_conflicts_keys_are_backward_compatible(tmp_path):
    memories = [_mem(f"m{i}", f"記憶 {i} の本文（project nous の作業ログ）", tags=["project:nous"]) for i in range(3)]
    payload = {"pages": [_page("project-nous-arch", ["m0", "m1", "m2"])]}
    _, repo, _ = _compile(tmp_path, memories, json.dumps(payload, ensure_ascii=False))
    assert _open_questions(repo) == []


def test_broken_json_records_error_and_writes_nothing(tmp_path):
    memories = [_mem(f"m{i}", f"記憶 {i} の本文（project nous の作業ログ）", tags=["project:nous"]) for i in range(3)]
    conn, repo, _ = _compile(tmp_path, memories, '{"pages": [{"slug": "x", "title": "y"')
    assert any(s.startswith("error:") for _, s, _ in _events(conn, "wiki.compiled"))
    assert _open_questions(repo) == []


def test_compile_uses_exactly_one_llm_call(tmp_path):
    """conflicts/questions は同じ応答から拾う（追加呼び出しなし）という不変条件。"""
    memories = [_mem(f"m{i}", f"記憶 {i} の本文（project nous の作業ログ）", tags=["project:nous"]) for i in range(3)]
    payload = {
        "pages": [_page("project-nous-arch", ["m0", "m1", "m2"])],
        "conflicts": [{"a": "project-nous-arch", "b": "project-nous-arch", "detail": "x", "resolved": False}],
        "questions": [{"query": "q1"}, {"query": "q2"}],
    }

    conn = SQLiteConnection(data_dir=str(tmp_path), persona="test_wc")
    conn.initialize_schema()
    repo = SQLiteMemoryRepository(conn)
    for m in memories:
        repo.save(m)
    ctx = SimpleNamespace(memory_repo=repo, connection=conn, memory_service=FakeMemoryService(repo))

    worker = WikiWorker(_settings(tmp_path))
    worker.vector_enabled = False
    calls: list[str] = []

    def _fake_ask(topic, *_args, **_kwargs):
        calls.append(topic)
        return json.dumps(payload, ensure_ascii=False)

    worker._ask_llm = _fake_ask  # type: ignore[method-assign]
    worker._compile_persona(ctx, "test_wc")
    assert len([c for c in calls if c == "project-nous"]) == 1


# ----------------------------------------------------------------------
# 記憶層: 週次掃除
# ----------------------------------------------------------------------


def _sweep_worker(tmp_path, *, provider, **cfg_update) -> tuple[WikiWorker, SQLiteConnection, SQLiteMemoryRepository]:
    conn = SQLiteConnection(data_dir=str(tmp_path), persona="test_sw")
    conn.initialize_schema()
    repo = SQLiteMemoryRepository(conn)
    worker = WikiWorker(_settings(tmp_path, conflict_sweep_enabled=True))
    worker.vector_enabled = False
    worker._provider_for_test = provider
    if cfg_update:
        worker._cfg = worker._cfg.model_copy(update=cfg_update)
    return worker, conn, repo


def test_sweep_disabled_makes_no_llm_call(tmp_path):
    provider = FakeProvider(_contradictory_reply("a"))
    conn = SQLiteConnection(data_dir=str(tmp_path), persona="test_sw")
    conn.initialize_schema()
    repo = SQLiteMemoryRepository(conn)
    memories = [
        _mem("a", "レンダリングは 30 分で回している", tags=["project:x"]),
        _mem("b", "レンダリングは 45 分で回している", tags=["project:x"]),
    ]
    for m in memories:
        repo.save(m)
    worker = WikiWorker(_settings(tmp_path))  # conflict_sweep_enabled=False
    worker.vector_enabled = False
    worker._provider_for_test = provider
    worker._sweep_memory_conflicts(
        SimpleNamespace(memory_repo=repo, connection=conn, memory_service=FakeMemoryService(repo)),
        "test_sw",
        memories,
        get_now(),
    )
    assert provider.calls == 0


def test_sweep_caps_llm_calls_exactly(tmp_path):
    """本物の ``sweep()`` に通し、classify の呼び出しが ``max_pairs`` ちょうどであること。"""
    memories = [_mem(f"k{i}", f"同じ文面 30 分 その{i}番目の記録", tags=["project:y"]) for i in range(6)]
    provider = FakeProvider(_contradictory_reply("k0"))
    worker, conn, repo = _sweep_worker(
        tmp_path, provider=provider, memory_conflict_max_pairs=2, memory_conflict_min_jaccard=0.3
    )
    for m in memories:
        repo.save(m)
    worker._sweep_memory_conflicts(
        SimpleNamespace(memory_repo=repo, connection=conn, memory_service=FakeMemoryService(repo)),
        "test_sw",
        memories,
        get_now(),
    )

    assert provider.calls == 2
    stats = [d for _, _, d in _events(conn, "wiki.conflict_sweep") if "checked" in d][-1]
    assert stats["checked"] == 2
    assert stats["capped"] is True


def test_sweep_interval_gate_uses_successful_event_only(tmp_path):
    """直近の掃除が成功していれば LLM 0 回。``error:`` 行は掃除済みと数えない。"""
    provider = FakeProvider(_contradictory_reply("a"))
    worker, conn, repo = _sweep_worker(tmp_path, provider=provider)
    memories = [
        _mem("a", "レンダリングは 30 分で回している", tags=["project:x"]),
        _mem("b", "レンダリングは 45 分で回している", tags=["project:x"]),
    ]
    for m in memories:
        repo.save(m)

    worker._record_event(
        SimpleNamespace(connection=conn),
        "test_sw",
        "warning: conflict sweep failed: boom",
        {"candidates": 1},
        event_type="wiki.conflict_sweep",
    )
    assert worker._last_sweep_at(SimpleNamespace(connection=conn), "test_sw") is None

    worker._record_event(
        SimpleNamespace(connection=conn),
        "test_sw",
        "conflict sweep: checked 1 closed 0",
        {"candidates": 1, "checked": 1, "closed": 0, "closed_keys": [], "capped": False},
        event_type="wiki.conflict_sweep",
    )
    assert worker._last_sweep_at(SimpleNamespace(connection=conn), "test_sw") is not None


def test_sweep_closes_contradicted_memory(tmp_path):
    """矛盾と判定されたら古い側の窓が閉じ、superseded_by で鎖が繋がる（削除なし）。"""
    from datetime import timedelta

    older = _mem(
        "old", "レンダリングは毎晩 30 分で回している", tags=["project:x"], created_at=get_now() - timedelta(days=3)
    )
    newer = _mem("new", "レンダリングは毎晩 45 分で回している", tags=["project:x"])
    provider = FakeProvider(_contradictory_reply("old"))
    worker, conn, repo = _sweep_worker(tmp_path, provider=provider, memory_conflict_min_jaccard=0.3)
    repo.save(older)
    repo.save(newer)

    worker._sweep_memory_conflicts(
        SimpleNamespace(memory_repo=repo, connection=conn, memory_service=FakeMemoryService(repo)),
        "test_sw",
        [older, newer],
        get_now(),
    )

    closed = repo.find_by_key("old").value
    assert closed is not None
    assert closed.valid_until is not None
    assert (closed.superseded_by or "") == "new"
    assert repo.find_by_key("new").value.lifecycle_status == "active"

    stats = [d for _, _, d in _events(conn, "wiki.conflict_sweep") if "closed" in d][-1]
    assert stats["closed"] == 1
    assert stats["closed_keys"] == [["old", "new"]]


def test_close_failure_is_not_counted_as_closed(tmp_path):
    from datetime import timedelta

    older = _mem(
        "old", "レンダリングは毎晩 30 分で回している", tags=["project:x"], created_at=get_now() - timedelta(days=3)
    )
    newer = _mem("new", "レンダリングは毎晩 45 分で回している", tags=["project:x"])
    provider = FakeProvider(_contradictory_reply("old"))
    worker, conn, repo = _sweep_worker(tmp_path, provider=provider, memory_conflict_min_jaccard=0.3)
    repo.save(older)
    repo.save(newer)

    def _fail(*_args, **_kwargs):
        return Failure(RuntimeError("db is locked"))

    repo.update_validity_window = _fail  # type: ignore[method-assign]
    worker._sweep_memory_conflicts(
        SimpleNamespace(memory_repo=repo, connection=conn, memory_service=FakeMemoryService(repo)),
        "test_sw",
        [older, newer],
        get_now(),
    )

    stats = [d for _, _, d in _events(conn, "wiki.conflict_sweep") if "closed" in d][-1]
    assert stats["closed"] == 0
    assert stats["closed_keys"] == []
    # close 失敗は「判定不能」と同じく失敗として数える（成功サマリを名乗らせない）。
    assert stats["failed"] == 1


def test_sweep_provider_failure_becomes_warning_not_error(tmp_path):
    """provider 構築〜sweep の失敗は ``warning:``（30 分再挑戦を誘発しない）。"""
    provider = FakeProvider(fail=True)
    worker, conn, repo = _sweep_worker(tmp_path, provider=provider)
    memories = [
        _mem("a", "レンダリングは 30 分で回している", tags=["project:x"]),
        _mem("b", "レンダリングは 45 分で回している", tags=["project:x"]),
    ]
    for m in memories:
        repo.save(m)
    worker._sweep_memory_conflicts(
        SimpleNamespace(memory_repo=repo, connection=conn, memory_service=FakeMemoryService(repo)),
        "test_sw",
        memories,
        get_now(),
    )

    rows = _events(conn, "wiki.conflict_sweep")
    assert rows and all(not s.startswith("error:") for _, s, _ in rows)


@pytest.mark.parametrize("closed_enabled", [True, False])
def test_sweep_flag_off_skips_everything(tmp_path, closed_enabled):
    provider = FakeProvider(_contradictory_reply("a"))
    worker, conn, repo = _sweep_worker(tmp_path, provider=provider, conflict_sweep_enabled=closed_enabled)
    memories = [
        _mem("a", "レンダリングは 30 分で回している", tags=["project:x"]),
        _mem("b", "レンダリングは 45 分で回している", tags=["project:x"]),
    ]
    for m in memories:
        repo.save(m)
    worker._sweep_memory_conflicts(
        SimpleNamespace(memory_repo=repo, connection=conn, memory_service=FakeMemoryService(repo)),
        "test_sw",
        memories,
        get_now(),
    )
    assert provider.calls == (1 if closed_enabled else 0)


def test_sweep_all_failed_does_not_rearm_the_week_gate(tmp_path):
    """全件判定不能なら ``warning:`` で記録し、168h ゲートを閉じない（次サイクルで再挑戦）。"""
    provider = FakeProvider(fail=True)
    worker, conn, repo = _sweep_worker(tmp_path, provider=provider, memory_conflict_min_jaccard=0.3)
    memories = [
        _mem("a", "レンダリングは 30 分で回している", tags=["project:x"]),
        _mem("b", "レンダリングは 45 分で回している", tags=["project:x"]),
    ]
    for m in memories:
        repo.save(m)
    ctx = SimpleNamespace(memory_repo=repo, connection=conn)
    worker._sweep_memory_conflicts(ctx, "test_sw", memories, get_now())

    rows = _events(conn, "wiki.conflict_sweep")
    assert rows, "sweep must leave a trace"
    summary, detail = rows[-1][1], rows[-1][2]
    assert summary.startswith("warning:")
    assert detail["checked"] >= 1 and detail["failed"] == detail["checked"]
    # 失敗を成功として数えない = ゲートが開いたまま（次サイクルで再挑戦できる）
    assert worker._last_sweep_at(ctx, "test_sw") is None


def test_sweep_success_rearms_the_week_gate(tmp_path):
    """1 件でも判定できたら成功として記録し、168h ゲートを閉じる。"""
    provider = FakeProvider(json.dumps({"type": "INDEPENDENT", "existing_key": None, "explanation": "無関係"}))
    worker, conn, repo = _sweep_worker(tmp_path, provider=provider, memory_conflict_min_jaccard=0.3)
    memories = [
        _mem("a", "レンダリングは 30 分で回している", tags=["project:x"]),
        _mem("b", "レンダリングは 45 分で回している", tags=["project:x"]),
    ]
    for m in memories:
        repo.save(m)
    ctx = SimpleNamespace(memory_repo=repo, connection=conn)
    worker._sweep_memory_conflicts(ctx, "test_sw", memories, get_now())

    rows = _events(conn, "wiki.conflict_sweep")
    assert not rows[-1][1].startswith(("warning:", "error:"))
    assert worker._last_sweep_at(ctx, "test_sw") is not None


def test_candidate_pairs_are_ordered_by_similarity(tmp_path):
    """似ている順に返す（``max_pairs`` で切る側が質の高い候補から処理できる）。"""
    base = "レンダリングは毎晩 30 分かかる設定で運用している"
    memories = [
        _mem("a1", base, tags=["project:x"]),
        _mem("a2", base + "（45 分に変更）", tags=["project:x"]),
        _mem("b1", "サーバーの CPU は 8 コアで回している", tags=["project:x"]),
        _mem("b2", "サーバーの CPU は 16 コアで回している", tags=["project:x"]),
    ]
    pairs = find_candidate_pairs(memories, min_jaccard=0.3)
    similarities = [sim for *_pair, sim in pairs]
    assert similarities == sorted(similarities, reverse=True)
    keys = {(newer.key, older.key) for newer, older, _sim in pairs}
    assert ("a2", "a1") in keys


def test_group_cap_bounds_quadratic_work():
    """1 プロジェクトが肥大しても総当たりの対象は ``_GROUP_CAP`` 件まで。"""
    from nous.application.wiki.conflict_sweep import _GROUP_CAP

    memories = [_mem(f"k{i:04d}", f"同じ文面 30 分 その{i}番目", tags=["project:big"]) for i in range(_GROUP_CAP + 40)]
    pairs = find_candidate_pairs(memories, min_jaccard=0.3, limit=1000)
    # 上限内の組合せ数（200*199/2）を超えない
    assert len(pairs) <= _GROUP_CAP * (_GROUP_CAP - 1) // 2


def test_conflict_check_disabled_uses_off_prompt(tmp_path):
    """``conflict_check_enabled`` のゲートが本番の ``_build_prompt`` に効く。"""
    from nous.application.workers import wiki_worker as wiki_worker_mod

    def _prompt(enabled: bool) -> str:
        worker, conn, _repo = _sweep_worker(tmp_path, provider=FakeProvider("{}"), conflict_check_enabled=enabled)
        try:
            return worker._build_prompt("project-x", [], [], get_now())
        finally:
            conn.close()

    off, on = _prompt(False), _prompt(True)
    assert wiki_worker_mod._CONFLICT_OFF in off
    assert "既存ページ同士で内容が食い違っている箇所を見つけたら" not in off
    assert "既存ページ同士で内容が食い違っている箇所を見つけたら" in on


def test_order_key_normalizes_mixed_offsets():
    """offset 混在でも辞書順が時系列になる（文字列比較では逆転していた）。"""
    from datetime import UTC, datetime

    from nous.application.wiki.conflict_sweep import _order_key

    newer = SimpleNamespace(key="b", created_at=datetime.fromisoformat("2026-11-09T02:00:00+00:00"))
    older = SimpleNamespace(key="a", created_at=datetime.fromisoformat("2026-11-09T10:00:00+09:00"))
    assert _order_key(newer) > _order_key(older)
    assert _order_key(SimpleNamespace(key="c", created_at="2026-11-09T02:00:00+00:00")) > _order_key(older)
    assert _order_key(SimpleNamespace(key="d", created_at=None))[0] == datetime.min.replace(tzinfo=UTC)


def test_candidate_pairs_pick_true_newer_with_mixed_offsets():
    """混在 offset でも新しい側が newer として返る（閉じる側を取り違えない）。"""
    from datetime import datetime

    from nous.application.wiki.conflict_sweep import find_candidate_pairs

    # 実時刻は newer が 1 時間新しいが、文字列比較では older("10:00+09:00") > newer("02:00+00:00")
    newer = _mem("b", "レンダリングは毎晩 45 分で回している", tags=["project:x"])
    newer = replace(newer, created_at=datetime.fromisoformat("2026-11-09T02:00:00+00:00"))
    older = _mem("a", "レンダリングは毎晩 30 分で回している", tags=["project:x"])
    older = replace(older, created_at=datetime.fromisoformat("2026-11-09T10:00:00+09:00"))

    pairs = find_candidate_pairs([older, newer], min_jaccard=0.3)
    assert pairs
    assert pairs[0][0].key == "b"
    assert pairs[0][1].key == "a"
