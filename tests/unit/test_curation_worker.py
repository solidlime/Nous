"""CurationWorker (B-6/B-7) — 状態機械・transcript・バリデータ・冪等性テスト.

fake LLM（同期 callable 注入）で 1 サイクルを回し、LLM 呼び出しの有無・
journal の二重化なし・curation_runs の記録を実 DB 上で検証する。
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from nous.application.workers.curation_worker import (
    CurationDecision,
    CurationWorker,
    curation_due,
    validate_curation_output,
)
from nous.domain.memory.entities import Memory
from nous.domain.shared.result import Success
from nous.domain.shared.time_utils import get_now
from nous.infrastructure.sqlite.connection import SQLiteConnection
from nous.infrastructure.sqlite.memory_repo import SQLiteMemoryRepository

PERSONA = "test_curation"


# ----------------------------------------------------------------------
# curation_due 境界
# ----------------------------------------------------------------------


class TestCurationDue:
    def _now(self) -> datetime:
        return datetime(2026, 9, 28, 4, 0, 0)

    def test_run_when_yesterday_unprocessed(self) -> None:
        """一昨日成功 → 前日（昨日）分が未整理なので run。"""
        decision = curation_due(
            last_done_at=datetime(2026, 9, 26, 4, 0, 0),
            last_failure_at=None,
            consecutive_failures=0,
            speech_count=3,
            now=self._now(),
        )
        assert decision is CurationDecision.RUN

    def test_skip_today_when_already_done_today(self) -> None:
        """本日分（＝昨日の会話）を整理済みなら skip_today。"""
        decision = curation_due(
            last_done_at=datetime(2026, 9, 28, 3, 0, 0),
            last_failure_at=None,
            consecutive_failures=0,
            speech_count=3,
            now=self._now(),
        )
        assert decision is CurationDecision.SKIP_TODAY

    def test_skip_today_when_failed_today(self) -> None:
        """本日失敗済みなら翌日まで再試行しない。"""
        decision = curation_due(
            last_done_at=datetime(2026, 9, 26, 4, 0, 0),
            last_failure_at=datetime(2026, 9, 28, 1, 0, 0),
            consecutive_failures=1,
            speech_count=3,
            now=self._now(),
        )
        assert decision is CurationDecision.SKIP_TODAY

    def test_skip_zero_speech(self) -> None:
        """対象日のユーザー発話ゼロはスキップ。"""
        decision = curation_due(
            last_done_at=datetime(2026, 9, 26, 4, 0, 0),
            last_failure_at=None,
            consecutive_failures=0,
            speech_count=0,
            now=self._now(),
        )
        assert decision is CurationDecision.SKIP_ZERO_SPEECH

    def test_halted_at_seven_consecutive_failures(self) -> None:
        """7 日連続失敗で halted。"""
        decision = curation_due(
            last_done_at=datetime(2026, 9, 20, 4, 0, 0),
            last_failure_at=datetime(2026, 9, 27, 4, 0, 0),
            consecutive_failures=7,
            speech_count=3,
            now=self._now(),
        )
        assert decision is CurationDecision.HALTED

    def test_not_halted_below_threshold(self) -> None:
        decision = curation_due(
            last_done_at=datetime(2026, 9, 26, 4, 0, 0),
            last_failure_at=None,
            consecutive_failures=6,
            speech_count=3,
            now=self._now(),
        )
        assert decision is CurationDecision.RUN

    def test_first_run_without_history(self) -> None:
        decision = curation_due(
            last_done_at=None,
            last_failure_at=None,
            consecutive_failures=0,
            speech_count=1,
            now=self._now(),
        )
        assert decision is CurationDecision.RUN


# ----------------------------------------------------------------------
# バリデータ
# ----------------------------------------------------------------------


def _valid_payload() -> dict:
    return {
        "profile_me": "私はテスト用の人形です。",
        "profile_user": "ユーザーはテストを好む。",
        "journal_heading": "2026-09-27",
        "journal_sections": [{"title": "テスト", "body": "テストを書いた。"}],
        "journal_self_today": "今日は静かな日だった。",
    }


class TestValidator:
    def test_accepts_fenced_json(self) -> None:
        raw = "```json\n" + json.dumps(_valid_payload(), ensure_ascii=False) + "\n```"
        out = validate_curation_output(raw)
        assert out is not None
        assert out.heading == "2026-09-27"
        assert "## テスト" in out.journal
        assert "## 今日の私" in out.journal

    def test_rejects_missing_key(self) -> None:
        payload = _valid_payload()
        del payload["journal_self_today"]
        assert validate_curation_output(json.dumps(payload)) is None

    def test_rejects_empty_sections(self) -> None:
        payload = _valid_payload()
        payload["journal_sections"] = []
        assert validate_curation_output(json.dumps(payload)) is None

    def test_rejects_non_json(self) -> None:
        assert validate_curation_output("これは JSON ではない") is None

    def test_rejects_oversized_journal(self) -> None:
        payload = _valid_payload()
        payload["journal_sections"] = [{"title": "長", "body": "あ" * 3000}]
        assert validate_curation_output(json.dumps(payload, ensure_ascii=False)) is None

    def test_trims_oversized_profile(self) -> None:
        payload = _valid_payload()
        payload["profile_me"] = "あ" * 5000
        out = validate_curation_output(json.dumps(payload, ensure_ascii=False))
        assert out is not None
        assert out.profile_me == ""


# ----------------------------------------------------------------------
# Worker 1 サイクル
# ----------------------------------------------------------------------


class _FakeService:
    """create_memory/update を repo 直書きで再現し、呼び出しを記録する。"""

    def __init__(self, repo: SQLiteMemoryRepository) -> None:
        self._repo = repo
        self.create_calls: list[dict] = []

    async def create_memory(self, **kwargs):
        self.create_calls.append(kwargs)
        now = get_now()
        mem = Memory(
            key=f"journal_{len(self.create_calls)}",
            content=kwargs["content"],
            created_at=now,
            updated_at=now,
            importance=kwargs.get("importance", 0.5),
            kind=kwargs.get("kind", "semantic"),
            source_type=kwargs.get("source_type", "user_stated"),
            tags=kwargs.get("tags", []),
        )
        self._repo.save(mem)
        return Success(mem)


def _make_env(tmp_path, *, with_speech: bool = True, llm_text: str | None = None):
    conn = SQLiteConnection(data_dir=str(tmp_path), persona=PERSONA)
    conn.initialize_schema()
    repo = SQLiteMemoryRepository(conn)
    service = _FakeService(repo)
    db = conn.get_memory_db()

    day = get_now().date() - timedelta(days=1)
    if with_speech:
        nodes = []
        parent = None
        for i, (role, content) in enumerate(
            [("user", "今日はテストの日だった。"), ("assistant", "そう、静かな日だね。")]
        ):
            node = {
                "id": f"n{i}",
                "parent_id": parent,
                "role": role,
                "content": content,
                "created_at": f"{day.isoformat()}T1{i}:00:00+09:00",
            }
            nodes.append(node)
            parent = f"n{i}"
        payload = {"root_id": "n0", "active_leaf_id": parent, "version": 1, "nodes": nodes}
        db.execute(
            "INSERT OR REPLACE INTO chat_sessions (persona, session_id, messages, timestamps, updated_at)"
            " VALUES (?, 'main', ?, '[]', ?)",
            (PERSONA, json.dumps(payload, ensure_ascii=False), get_now().isoformat()),
        )
        db.commit()

    calls: list[str] = []

    def _llm(prompt: str, persona: str) -> str | None:
        calls.append(prompt)
        return llm_text

    settings = MagicMock()
    settings.curation.enabled = True
    settings.curation.check_interval_seconds = 60
    settings.curation.max_backlog_days = 7
    settings.curation.journal_max_tokens = 1500
    settings.curation.profile_max_tokens = 3000

    ctx = SimpleNamespace(memory_repo=repo, memory_service=service, connection=conn, persona=PERSONA)
    worker = CurationWorker(settings, llm=_llm)
    return conn, repo, service, ctx, worker, calls


def _valid_llm_text() -> str:
    return "```json\n" + json.dumps(_valid_payload(), ensure_ascii=False) + "\n```"


class TestWorkerCycle:
    def test_success_cycle_writes_journal_and_run(self, tmp_path) -> None:
        conn, repo, service, ctx, worker, calls = _make_env(tmp_path, llm_text=_valid_llm_text())
        try:
            worker._curate_persona(ctx, PERSONA)
            assert len(calls) == 1
            # journal 記憶が 1 件、タグ契約を満たす
            assert len(service.create_calls) == 1
            call = service.create_calls[0]
            assert "journal" in call["tags"]
            assert call["kind"] == "episodic"
            # profile が書き込まれる
            blocks = repo.get_profile_blocks(PERSONA)
            assert blocks.is_ok and "me" in blocks.value
            # run が done で記録される
            rows = (
                conn.get_memory_db().execute("SELECT status FROM curation_runs WHERE persona=?", (PERSONA,)).fetchall()
            )
            assert [r["status"] for r in rows] == ["done"]
        finally:
            conn.close()

    def test_idempotent_rerun_does_not_duplicate_journal(self, tmp_path) -> None:
        conn, repo, service, ctx, worker, calls = _make_env(tmp_path, llm_text=_valid_llm_text())
        try:
            worker._curate_persona(ctx, PERSONA)
            # 同日再実行: due 判定が skip_today になり LLM を呼ばない
            worker._curate_persona(ctx, PERSONA)
            assert len(calls) == 1
            assert len(service.create_calls) == 1
        finally:
            conn.close()

    def test_forced_rerun_updates_journal_in_place(self, tmp_path) -> None:
        """due を迂回して再実行しても journal は二重化せず update される。"""
        conn, repo, service, ctx, worker, calls = _make_env(tmp_path, llm_text=_valid_llm_text())
        try:
            worker._curate_persona(ctx, PERSONA)
            worker._curate_persona(ctx, PERSONA, force=True)
            assert len(service.create_calls) == 1
            journals = repo.get_by_tags(["journal"])
            assert journals.is_ok and len(journals.value) == 1
        finally:
            conn.close()

    def test_invalid_llm_output_records_failed(self, tmp_path) -> None:
        conn, repo, service, ctx, worker, calls = _make_env(tmp_path, llm_text="not json at all")
        try:
            worker._curate_persona(ctx, PERSONA)
            rows = (
                conn.get_memory_db()
                .execute("SELECT status, error FROM curation_runs WHERE persona=?", (PERSONA,))
                .fetchall()
            )
            assert [r["status"] for r in rows] == ["failed"]
            assert rows[0]["error"]
            assert service.create_calls == []
        finally:
            conn.close()

    def test_failure_skips_same_day_rerun(self, tmp_path) -> None:
        conn, repo, service, ctx, worker, calls = _make_env(tmp_path, llm_text="not json at all")
        try:
            worker._curate_persona(ctx, PERSONA)
            worker._curate_persona(ctx, PERSONA)
            assert len(calls) == 1  # 再試行なし
        finally:
            conn.close()

    def test_zero_speech_day_skips_llm(self, tmp_path) -> None:
        conn, repo, service, ctx, worker, calls = _make_env(tmp_path, with_speech=False, llm_text=_valid_llm_text())
        try:
            worker._curate_persona(ctx, PERSONA)
            assert calls == []
            rows = (
                conn.get_memory_db().execute("SELECT status FROM curation_runs WHERE persona=?", (PERSONA,)).fetchall()
            )
            assert rows == []
        finally:
            conn.close()

    def test_seven_failures_halts(self, tmp_path) -> None:
        conn, repo, service, ctx, worker, calls = _make_env(tmp_path, llm_text="not json at all")
        try:
            db = conn.get_memory_db()
            base = get_now() - timedelta(days=8)
            for i in range(7):
                db.execute(
                    "INSERT INTO curation_runs (persona, status, error, started_at, finished_at)"
                    " VALUES (?, 'failed', 'boom', ?, ?)",
                    (PERSONA, (base + timedelta(days=i)).isoformat(), (base + timedelta(days=i)).isoformat()),
                )
            db.commit()
            worker._curate_persona(ctx, PERSONA)
            assert calls == []
        finally:
            conn.close()


class TestBacklogLimit:
    def test_old_unprocessed_days_are_abandoned(self, tmp_path) -> None:
        """7 日より前の未整理日は追いかけない（最終成功が 8 日前でも 1 回だけ run）。"""
        conn, repo, service, ctx, worker, calls = _make_env(tmp_path, llm_text=_valid_llm_text())
        try:
            db = conn.get_memory_db()
            old = (get_now() - timedelta(days=8)).isoformat()
            db.execute(
                "INSERT INTO curation_runs (persona, status, error, started_at, finished_at)"
                " VALUES (?, 'done', NULL, ?, ?)",
                (PERSONA, old, old),
            )
            db.commit()
            worker._curate_persona(ctx, PERSONA)
            assert len(calls) == 1
        finally:
            conn.close()


class TestTranscript:
    def test_line_truncated_at_500_chars(self, tmp_path) -> None:
        """1 行は 500 字でトランケートされ、超過分はプロンプトに載らない。"""
        conn, repo, service, ctx, worker, calls = _make_env(tmp_path, with_speech=False, llm_text=_valid_llm_text())
        try:
            db = conn.get_memory_db()
            day = get_now().date() - timedelta(days=1)
            payload = {
                "root_id": "y0",
                "active_leaf_id": "y0",
                "version": 1,
                "nodes": [
                    {
                        "id": "y0",
                        "parent_id": None,
                        "role": "user",
                        "content": "あ" * 600,
                        "created_at": f"{day.isoformat()}T12:00:00+09:00",
                    }
                ],
            }
            db.execute(
                "INSERT OR REPLACE INTO chat_sessions (persona, session_id, messages, timestamps, updated_at)"
                " VALUES (?, 'main', ?, '[]', ?)",
                (PERSONA, json.dumps(payload, ensure_ascii=False), get_now().isoformat()),
            )
            db.commit()
            worker._curate_persona(ctx, PERSONA)
            assert calls
            assert "あ" * 500 in calls[0]
            assert "あ" * 501 not in calls[0]
        finally:
            conn.close()


@pytest.mark.parametrize("decision_name", ["run", "skip_today", "skip_zero_speech", "halted"])
def test_decision_enum_surface(decision_name: str) -> None:
    assert CurationDecision(decision_name) == getattr(CurationDecision, decision_name.upper())
