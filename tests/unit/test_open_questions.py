"""未解決の問いの正規化キー・解消・上限（kanban #55）。

方針:
- キーは「何についての問いか」だけで決める（矛盾はペア + 種別、問いは topic + 本文の正規化ハッシュ）。
  文面が変わるたびに増殖させない。
- 上限 ``max_open_questions`` を超えたら新規作成しない。
- 解消したら閉じる（Zero Inbox: 閉じる = 消す）。
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import pytest

from nous.api.mcp import _tools_memory as memory_tools
from nous.application.wiki.questions import (
    dedupe_open_questions,
    find_open_questions,
    normalize_question_text,
    question_key_of,
    question_pair_key,
    question_query_key,
)
from nous.application.workers.wiki_worker import WikiWorker
from nous.config.settings import WikiConfig
from nous.domain.memory.entities import Memory
from nous.domain.shared.result import Success
from nous.domain.shared.time_utils import get_now
from nous.infrastructure.sqlite.connection import SQLiteConnection
from nous.infrastructure.sqlite.memory_repo import SQLiteMemoryRepository

PERSONA = "test_oq"


# ----------------------------------------------------------------------
# ヘルパ
# ----------------------------------------------------------------------


def _settings(tmp_path, **wiki_update) -> SimpleNamespace:
    params = {"enabled": True, **wiki_update}
    return SimpleNamespace(
        wiki=WikiConfig(**params),
        data_root=str(tmp_path),
        openrouter_api_key="",
        anthropic_api_key="",
        openai_api_key="",
        google_api_key="",
        opencode_go_api_key="",
    )


class FakeVectorStore:
    """``delete`` が呼ばれたキーを記録するだけのベクトル索引。"""

    def __init__(self) -> None:
        self.deleted: list[str] = []

    async def delete(self, persona: str, key: str) -> None:
        self.deleted.append(key)


class FakeMemoryService:
    """repo へ直書きする最小の memory_service（delete は本物と同じく物理削除）。"""

    def __init__(self, repo: SQLiteMemoryRepository) -> None:
        self._repo = repo
        self.create_calls = 0
        self.deleted: list[str] = []

    async def create_memory(self, content: str = "", tags=None, **kwargs: Any):
        self.create_calls += 1
        now = get_now()
        memory = Memory(
            key=f"q{self.create_calls}",
            content=content,
            created_at=now,
            updated_at=now,
            importance=0.5,
            kind="semantic",
            source_type="llm_inferred",
            lifecycle_status="active",
            tags=list(tags or []),
            source_context=kwargs.get("source_context"),
        )
        self._repo.save(memory)
        return Success(memory)

    def get_memory(self, key: str):
        return self._repo.find_by_key(key)

    def delete_memory(self, key: str):
        self.deleted.append(key)
        return self._repo.delete(key)


def _ctx(conn, repo, service, vector_store=None):
    return SimpleNamespace(
        memory_repo=repo, connection=conn, memory_service=service, vector_store=vector_store
    )


def _mem(key: str, content: str, *, tags: list[str] | None = None, lifecycle: str = "active") -> Memory:
    now = get_now()
    return Memory(
        key=key,
        content=content,
        created_at=now,
        updated_at=now,
        importance=0.5,
        kind="semantic",
        source_type="user_stated",
        lifecycle_status=lifecycle,
        tags=tags or [],
    )


def _page(slug: str, sources: list[str]) -> dict:
    return {"slug": slug, "title": slug.replace("-", " ").title(), "body": f"## 概要\n{slug}", "sources": sources}


def _compile(ctx, worker: WikiWorker, llm: str) -> None:
    worker._ask_llm_for_test = llm  # type: ignore[attr-defined]
    worker._compile_persona(ctx, PERSONA)


def _events(conn, event_type: str = "wiki.conflict") -> list[tuple[str, str, dict]]:
    rows = conn.get_memory_db().execute("SELECT event_type, summary, detail FROM session_events ORDER BY id").fetchall()
    return [
        (r["event_type"], r["summary"], json.loads(r["detail"]) if r["detail"] else {})
        for r in rows
        if r["event_type"] == event_type
    ]


# ----------------------------------------------------------------------
# 正規化キー（純関数）
# ----------------------------------------------------------------------


def test_pair_key_ignores_order_and_defaults_kind():
    assert question_pair_key("A-page", "b-page") == question_pair_key("b-page", "a-page", "fact")
    assert question_pair_key("a", "b", "VALUE") == question_pair_key("b", "a", "value")
    assert question_pair_key("a", "b", "value") != question_pair_key("a", "b", "scope")


def test_query_key_normalizes_width_case_and_punctuation():
    assert question_query_key("Topic", "litellm　の上限は？") == question_query_key("topic", "LiteLLM の上限は?")
    assert normalize_question_text("ＡＢＣ　テスト、です。") == normalize_question_text("abcテストです")


# ----------------------------------------------------------------------
# 編纂サイクルでの重複抑止・解消・上限
# ----------------------------------------------------------------------


def test_reworded_detail_keeps_one_open_question(tmp_path):
    """同じペア・同じ種別なら detail の文面が変わっても 1 件のまま。"""
    conn = SQLiteConnection(data_dir=str(tmp_path), persona=PERSONA)
    conn.initialize_schema()
    repo = SQLiteMemoryRepository(conn)
    for i in range(3):
        repo.save(_mem(f"m{i}", f"記憶 {i}（project nous の作業ログ）", tags=["project:nous"]))
    service = FakeMemoryService(repo)
    ctx = _ctx(conn, repo, service)
    worker = WikiWorker(_settings(tmp_path))
    worker.vector_enabled = False

    def payload(detail: str) -> str:
        return json.dumps(
            {
                "pages": [_page("project-nous-arch", ["m0", "m1", "m2"])],
                "conflicts": [
                    {
                        "a": "project-nous-arch",
                        "b": "project-nous-arch",
                        "kind": "value",
                        "detail": detail,
                        "resolved": False,
                    }
                ],
            },
            ensure_ascii=False,
        )

    _compile(ctx, worker, payload("再試行回数が違う"))
    _compile(ctx, worker, payload("再試行は 3 回と 5 回で食い違っている"))
    assert len(find_open_questions(ctx)) == 1


def test_resolved_conflict_closes_previous_open_question(tmp_path):
    conn = SQLiteConnection(data_dir=str(tmp_path), persona=PERSONA)
    conn.initialize_schema()
    repo = SQLiteMemoryRepository(conn)
    for i in range(3):
        repo.save(_mem(f"m{i}", f"記憶 {i}（project nous の作業ログ）", tags=["project:nous"]))
    service = FakeMemoryService(repo)
    ctx = _ctx(conn, repo, service)
    worker = WikiWorker(_settings(tmp_path))
    worker.vector_enabled = False

    def payload(resolved: bool) -> str:
        return json.dumps(
            {
                "pages": [_page("project-nous-arch", ["m0", "m1", "m2"])],
                "conflicts": [
                    {
                        "a": "project-nous-arch",
                        "b": "project-nous-arch",
                        "kind": "value",
                        "detail": "再試行回数が違う",
                        "resolved": resolved,
                    }
                ],
            },
            ensure_ascii=False,
        )

    _compile(ctx, worker, payload(False))
    assert len(find_open_questions(ctx)) == 1

    # 編纂で記憶が消えるので、次のサイクル用に候補を積み直す
    for i in range(3):
        repo.save(_mem(f"n{i}", f"新しい記憶 {i}（project nous の作業ログ）", tags=["project:nous"]))
    _compile(ctx, worker, json.dumps({"pages": [], "conflicts": []}))
    worker._ask_llm_for_test = payload(True)  # type: ignore[attr-defined]
    worker._compile_persona(ctx, PERSONA)

    assert find_open_questions(ctx) == []
    assert any("question closed" in summary for _, summary, _ in _events(conn))


def test_open_question_cap_blocks_new_questions(tmp_path):
    conn = SQLiteConnection(data_dir=str(tmp_path), persona=PERSONA)
    conn.initialize_schema()
    repo = SQLiteMemoryRepository(conn)
    for i in range(3):
        repo.save(_mem(f"m{i}", f"記憶 {i}（project nous の作業ログ）", tags=["project:nous"]))
    service = FakeMemoryService(repo)
    ctx = _ctx(conn, repo, service)
    worker = WikiWorker(_settings(tmp_path, max_open_questions=2))
    worker.vector_enabled = False

    payload = json.dumps(
        {
            "pages": [_page("project-nous-arch", ["m0", "m1", "m2"])],
            "questions": [
                {"query": "一つ目の問い", "topic": "project-nous-arch"},
                {"query": "二つ目の問い", "topic": "project-nous-arch"},
                {"query": "三つ目の問い", "topic": "project-nous-arch"},
            ],
        },
        ensure_ascii=False,
    )
    _compile(ctx, worker, payload)

    assert len(find_open_questions(ctx)) == 2
    assert any("cap reached" in summary for _, summary, _ in _events(conn))


def test_dedupe_pass_collapses_legacy_duplicates_and_enforces_cap(tmp_path):
    """旧形式（自由文ハッシュ）で溜まった重複を本文正規化で畳む。"""
    conn = SQLiteConnection(data_dir=str(tmp_path), persona=PERSONA)
    conn.initialize_schema()
    repo = SQLiteMemoryRepository(conn)
    service = FakeMemoryService(repo)
    ctx = _ctx(conn, repo, service)

    for i, text in enumerate(["A と B: 値が違う", "ＡとＢ: 値が違う。", "AとB：値が違う"]):
        memory = _mem(f"legacy{i}", text, tags=["open-question"])
        memory.source_context = f"open-question:{i}"  # 旧形式: 本文ハッシュ
        repo.save(memory)

    deleted, remaining = asyncio_run(dedupe_open_questions(ctx, PERSONA, cap=20))
    assert deleted == 2
    assert remaining == 1
    assert len(find_open_questions(ctx)) == 1
    rows = conn.get_memory_db().execute("SELECT COUNT(*) AS c FROM memories").fetchone()
    assert rows["c"] == 1
    # 畳む基準は qkey（本文が違っても同じ問い）。legacy 行なので本文正規化で畳まれる。
    kept = repo.find_all().value
    assert [m.key for m in kept] == ["legacy2"]


def asyncio_run(coro):
    import asyncio

    return asyncio.run(coro)


# ----------------------------------------------------------------------
# memory_update(resolved=True) — MCP 面の明示解消
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_memory_update_resolved_closes_question(tmp_path):
    conn = SQLiteConnection(data_dir=str(tmp_path), persona=PERSONA)
    conn.initialize_schema()
    repo = SQLiteMemoryRepository(conn)
    service = FakeMemoryService(repo)

    vector_store = FakeVectorStore()
    first = _mem("oq1", "a と b: 値が違う", tags=["open-question"])
    first.source_context = "open-question:qkey:pair:a|b:value"
    repo.save(first)
    second = _mem("oq2", "a と b: 値が違う（再掲）", tags=["open-question"])
    second.source_context = "open-question:qkey:pair:a|b:value"
    repo.save(second)

    class Bus:
        async def publish(self, *_args: Any, **_kwargs: Any) -> None:
            return None

    ctx = SimpleNamespace(
        memory_repo=repo,
        connection=conn,
        memory_service=service,
        vector_store=vector_store,
        event_bus=Bus(),
    )

    result = await memory_tools._tool_memory_update(ctx, PERSONA, memory_key="oq1", resolved=True)
    payload = json.loads(result)
    assert payload["ok"] is True
    assert payload["data"]["closed"] == 2
    assert find_open_questions(ctx) == []
    # tombstone ではなく行ごと消えていること（find_all は tombstone も隠すので直接見る）
    rows = conn.get_memory_db().execute(
        "SELECT COUNT(*) AS c FROM memories WHERE key IN ('oq1', 'oq2')"
    ).fetchone()
    assert rows["c"] == 0
    versions = conn.get_memory_db().execute(
        "SELECT COUNT(*) AS c FROM memory_versions WHERE memory_key IN ('oq1', 'oq2')"
    ).fetchone()
    assert versions["c"] == 0
    assert sorted(vector_store.deleted) == ["oq1", "oq2"]
    assert question_key_of(first) == "qkey:pair:a|b:value"


@pytest.mark.asyncio
async def test_memory_update_resolved_rejects_non_question(tmp_path):
    conn = SQLiteConnection(data_dir=str(tmp_path), persona=PERSONA)
    conn.initialize_schema()
    repo = SQLiteMemoryRepository(conn)
    repo.save(_mem("plain", "ただの記憶", tags=["misc"]))
    ctx = SimpleNamespace(
        memory_repo=repo,
        memory_service=FakeMemoryService(repo),
        vector_store=None,
        event_bus=SimpleNamespace(publish=lambda *a, **k: None),
    )

    payload = json.loads(await memory_tools._tool_memory_update(ctx, PERSONA, memory_key="plain", resolved=True))
    assert payload["ok"] is False
    assert "not an open question" in json.dumps(payload, ensure_ascii=False)
