"""矛盾整理（#39）のテスト。

計画書 ``docs/archive/superpowers/plans/2026-11-10-journal-conflicts-and-research.md`` §3.3 / §4.2:

- 編纂応答の ``conflicts`` / ``questions`` は追加 LLM 呼び出しなしで処理する
- ``resolved=false`` と ``questions`` は ``open-question`` タグの記憶になる（重複は 1 件）
- 記憶層の掃除は候補抽出が純関数（LLM 0 回）、判定は ``memory_conflict_max_pairs`` で打ち切る

このファイルは**ネットワークに出ない**。矛盾判定の provider は必ず fake。
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

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

    ``research_enabled`` は既定 False（#53）なので、wiki 層のテストから
    外部 MCP へ出る経路は踏まない。
    """
    # 日記は既定で止める。窓が run_at_hour 基準なので、有効なままだと実行時刻
    # （00:00〜03:00）で材料が日記に食われ、topic 編纂のテストが時刻依存で落ちる。
    params = {"enabled": True, "journal_enabled": False, **wiki_update}
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


def test_conflict_check_disabled_uses_off_prompt(tmp_path):
    """``conflict_check_enabled`` のゲートが本番の ``_build_prompt`` に効く。"""
    from nous.application.workers import wiki_worker as wiki_worker_mod

    def _prompt(enabled: bool) -> str:
        conn = SQLiteConnection(data_dir=str(tmp_path), persona=f"test_cc_{int(enabled)}")
        conn.initialize_schema()
        worker = WikiWorker(_settings(tmp_path, conflict_check_enabled=enabled))
        try:
            return worker._build_prompt("project-x", [], [], get_now())
        finally:
            conn.close()

    off, on = _prompt(False), _prompt(True)
    assert wiki_worker_mod._CONFLICT_OFF in off
    assert "既存ページ同士で内容が食い違っている箇所を見つけたら" not in off
    assert "既存ページ同士で内容が食い違っている箇所を見つけたら" in on
