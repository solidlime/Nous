"""FreshnessWorker tests — LLM 鮮度評価の SELECT・verdict 適用・監査記録。

計画書 §5 (2026-11-07-active-memory-pi-hook-and-llm-freshness.md):
- SELECT: gist / consolidated / 期限切れを除外、prospective 無期限・30日未アクセスを収録
- verdict 適用: expire → archived / reschedule → valid_until / demote → importance
- importance >= 0.8 は protected（importance 変更を拒否し、valid_until 系のみ適用）
- LLM 失敗・不正 JSON → 例外が外に漏れず memory 無変化、session_events に error 行
- verdict 毎に session_events へ 1 行（type=freshness.verdict）

NOTE: repo.save() は updated_at を get_now() で上書きするため、stale 判定に必要な
過去時刻は INSERT 後に直接 UPDATE SQL で設定する。
"""

from __future__ import annotations

import json
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from nous.application.workers.freshness_worker import FreshnessWorker
from nous.domain.memory.entities import Memory
from nous.domain.shared.time_utils import get_now
from nous.infrastructure.sqlite.connection import SQLiteConnection
from nous.infrastructure.sqlite.memory_repo import SQLiteMemoryRepository


def _rec(
    key: str,
    *,
    kind: str = "semantic",
    importance: float = 0.6,
    valid_until="keep_none",  # "keep_none" = 指定なし / None or datetime = SQL で上書き
    updated: timedelta | None = None,
    accessed: timedelta | None = None,
    source_type: str = "user_stated",
    lifecycle: str = "active",
) -> dict:
    """テスト記憶のレコード指定（save 後に SQL で時刻を上書きする仕様）。"""
    now = get_now()
    mem = Memory(
        key=key,
        content=f"{key} のテスト記憶内容。鮮度評価の対象となる本文。",
        created_at=now,
        updated_at=now - (updated or timedelta(0)) if updated is not None else now,
        importance=importance,
        kind=kind,
        source_type=source_type,
        lifecycle_status=lifecycle,
    )
    rec: dict = {"mem": mem}
    if updated is not None:
        rec["updated"] = updated
    if accessed is not None:
        rec["accessed"] = accessed
    if valid_until != "keep_none":
        rec["valid_until"] = valid_until
    return rec


class _FakeService:
    """update_memory を記録するだけの stub（verdict 適用の検証用）。"""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    def update_memory(self, key: str, **updates: object):
        self.calls.append((key, updates))
        return SimpleNamespace(is_ok=True, value=None)


def _settings() -> MagicMock:
    """本物の FreshnessConfig を持つ settings stub（其余は未使用を MagicMock で埋める）。"""
    from nous.config.settings import FreshnessConfig

    s = MagicMock()
    s.freshness = FreshnessConfig()
    return s


def _setup_db(tmp_path, records: list[dict]) -> tuple[SQLiteConnection, SQLiteMemoryRepository]:
    conn = SQLiteConnection(data_dir=str(tmp_path), persona="test_fw")
    conn.initialize_schema()
    repo = SQLiteMemoryRepository(conn)
    now = get_now()
    db = conn.get_memory_db()
    for rec in records:
        mem = rec["mem"]
        repo.save(mem)
        sets, params = [], []
        if rec.get("updated") is not None:
            sets.append("updated_at = ?")
            params.append((now - rec["updated"]).isoformat())
        if rec.get("accessed") is not None:
            sets.append("last_accessed = ?")
            params.append((now - rec["accessed"]).isoformat())
        if "valid_until" in rec:
            sets.append("valid_until = ?")
            params.append(rec["valid_until"].isoformat() if rec["valid_until"] else None)
        if sets:
            db.execute(f"UPDATE memories SET {', '.join(sets)} WHERE key = ?", (*params, mem.key))
    db.commit()
    return conn, repo


def _run_eval(tmp_path, records: list[dict], llm_result: str | None, *, raise_exc: Exception | None = None):
    """DB セットアップ → _evaluate_persona 実行 → (conn, service, worker) を返す。"""
    conn, repo = _setup_db(tmp_path, records)
    try:
        service = _FakeService()
        ctx = SimpleNamespace(memory_repo=repo, memory_service=service, connection=conn)
        worker = FreshnessWorker(_settings())
        worker._ask_llm_for_test = llm_result  # type: ignore[attr-defined]
        worker._ask_llm_raise = raise_exc  # type: ignore[attr-defined]
        worker._evaluate_persona(ctx, "test")
        return conn, service, worker
    except BaseException:
        conn.close()
        raise


def _verdicts_json(*items: dict) -> str:
    return json.dumps({"results": list(items)}, ensure_ascii=False)


def _event_rows(conn) -> list[tuple]:
    db = conn.get_memory_db()
    rows = db.execute("SELECT event_type, summary FROM session_events ORDER BY id").fetchall()
    return [(r["event_type"], r["summary"]) for r in rows]


# ---------------------------------------------------------------------------
# SELECT 条件
# ---------------------------------------------------------------------------


class TestSelectCandidates:
    def test_excludes_gist_and_consolidated(self, tmp_path) -> None:
        """gist（consolidated 派生）と source_type=consolidated は評価対象外。"""
        now = get_now()
        records = [
            _rec("stale1", updated=timedelta(days=40)),
            _rec("gist", source_type="consolidated", updated=timedelta(days=40)),
        ]
        conn, repo = _setup_db(tmp_path, records)
        try:
            ctx = SimpleNamespace(memory_repo=repo, memory_service=_FakeService(), connection=conn)
            candidates = FreshnessWorker(_settings())._select_candidates(ctx, now)
            assert [c.key for c in candidates] == ["stale1"]
        finally:
            conn.close()

    def test_excludes_expired_and_non_active(self, tmp_path) -> None:
        """valid_until が過去（既に期限切れ）と lifecycle != active は対象外。"""
        now = get_now()
        records = [
            _rec("stale1", updated=timedelta(days=40)),
            _rec("expired", valid_until=now - timedelta(days=1), updated=timedelta(days=40)),
            _rec("archived", updated=timedelta(days=40), lifecycle="archived"),
            _rec("tombstoned", updated=timedelta(days=40), lifecycle="tombstoned"),
        ]
        conn, repo = _setup_db(tmp_path, records)
        try:
            ctx = SimpleNamespace(memory_repo=repo, memory_service=_FakeService(), connection=conn)
            candidates = FreshnessWorker(_settings())._select_candidates(ctx, now)
            assert [c.key for c in candidates] == ["stale1"]
        finally:
            conn.close()

    def test_includes_prospective_no_expiry_and_near_expiry(self, tmp_path) -> None:
        """無期限 prospective（30日+未更新）と 7日以内期限の記憶は対象に含まれる。"""
        now = get_now()
        records = [
            _rec("pros_no_expiry", kind="prospective", updated=timedelta(days=35), valid_until=None),
            _rec("near_expiry", kind="prospective", updated=timedelta(days=1), valid_until=now + timedelta(days=3)),
            _rec("fresh_untouched", updated=timedelta(days=1)),  # 最近 → 対象外
        ]
        conn, repo = _setup_db(tmp_path, records)
        try:
            ctx = SimpleNamespace(memory_repo=repo, memory_service=_FakeService(), connection=conn)
            candidates = FreshnessWorker(_settings())._select_candidates(ctx, now)
            assert sorted(c.key for c in candidates) == ["near_expiry", "pros_no_expiry"]
        finally:
            conn.close()


# ---------------------------------------------------------------------------
# verdict 適用
# ---------------------------------------------------------------------------


class TestApplyVerdicts:
    def test_expire_verdict_archives_memory(self, tmp_path) -> None:
        """verdict=expire → update_memory(lifecycle_status="archived")。"""
        records = [_rec("stale1", updated=timedelta(days=40))]
        conn, service, _ = _run_eval(
            tmp_path,
            records,
            _verdicts_json({"key": "stale1", "verdict": "expire", "reason": "古い"}),
        )
        try:
            assert len(service.calls) == 1
            key, updates = service.calls[0]
            assert key == "stale1"
            assert updates.get("lifecycle_status") == "archived"
            rows = _event_rows(conn)
            assert len(rows) == 1 and rows[0][0] == "freshness.verdict"
        finally:
            conn.close()

    def test_reschedule_verdict_sets_valid_until(self, tmp_path) -> None:
        """verdict=reschedule + valid_until_suggestion → valid_until 更新。"""
        records = [_rec("pros1", kind="prospective", updated=timedelta(days=40), valid_until=None)]
        new_until = "2027-01-01T00:00:00+09:00"
        conn, service, _ = _run_eval(
            tmp_path,
            records,
            _verdicts_json(
                {"key": "pros1", "verdict": "reschedule", "valid_until_suggestion": new_until, "reason": "まだ有効"}
            ),
        )
        try:
            assert len(service.calls) == 1
            key, updates = service.calls[0]
            assert key == "pros1"
            assert updates.get("valid_until") is not None
            assert updates["valid_until"].isoformat() == new_until
        finally:
            conn.close()

    def test_reschedule_without_suggestion_is_noop(self, tmp_path) -> None:
        """reschedule でも suggestion が空なら valid_until は触らない。"""
        records = [_rec("pros1", kind="prospective", updated=timedelta(days=40), valid_until=None)]
        conn, service, _ = _run_eval(
            tmp_path,
            records,
            _verdicts_json({"key": "pros1", "verdict": "reschedule", "valid_until_suggestion": None}),
        )
        try:
            assert service.calls == []
        finally:
            conn.close()

    def test_demote_verdict_downgrades_importance(self, tmp_path) -> None:
        """verdict=demote → importance を suggestion に下げる。"""
        records = [_rec("stale1", importance=0.5, updated=timedelta(days=40))]
        conn, service, _ = _run_eval(
            tmp_path,
            records,
            _verdicts_json({"key": "stale1", "verdict": "demote", "importance_suggestion": 0.3}),
        )
        try:
            assert len(service.calls) == 1
            _, updates = service.calls[0]
            assert updates.get("importance") == pytest.approx(0.3)
        finally:
            conn.close()

    def test_protected_importance_is_not_demoted(self, tmp_path) -> None:
        """importance >= 0.8 は protected: demote 提案は無視される（valid_until 系のみ適用可）。"""
        records = [_rec("core1", importance=0.9, updated=timedelta(days=40))]
        conn, service, _ = _run_eval(
            tmp_path,
            records,
            _verdicts_json(
                {"key": "core1", "verdict": "demote", "importance_suggestion": 0.3, "valid_until_suggestion": None}
            ),
        )
        try:
            # importance 変更だけの提案は適用されない → 更新なし
            assert service.calls == []
        finally:
            conn.close()

    def test_keep_verdict_is_noop(self, tmp_path) -> None:
        """verdict=keep → 何も更新しない（session_events への記録のみ）。"""
        records = [_rec("stale1", updated=timedelta(days=40))]
        conn, service, _ = _run_eval(
            tmp_path,
            records,
            _verdicts_json({"key": "stale1", "verdict": "keep"}),
        )
        try:
            assert service.calls == []
            rows = _event_rows(conn)
            assert len(rows) == 1 and rows[0][0] == "freshness.verdict"
        finally:
            conn.close()


# ---------------------------------------------------------------------------
# LLM 失敗時の挙動
# ---------------------------------------------------------------------------


class TestLLMFailure:
    def test_invalid_json_leaves_memory_untouched(self, tmp_path) -> None:
        """不正 JSON → 例外が漏れず、memory 無変化、error が session_events に記録。"""
        records = [_rec("stale1", updated=timedelta(days=40))]
        conn, service, _ = _run_eval(tmp_path, records, "これはJSONではありません!!!")
        try:
            assert service.calls == []
            rows = _event_rows(conn)
            assert any(t == "freshness.verdict" and s.startswith("error:") for t, s in rows)
        finally:
            conn.close()

    def test_llm_exception_is_suppressed(self, tmp_path) -> None:
        """LLM 呼び出し例外 → _evaluate_persona 外に漏れない。memory 無変化。"""
        records = [_rec("stale1", updated=timedelta(days=40))]
        conn, service, _ = _run_eval(tmp_path, records, None, raise_exc=RuntimeError("provider boom"))
        try:
            assert service.calls == []
            rows = _event_rows(conn)
            assert any(s.startswith("error:") for _, s in rows)
        finally:
            conn.close()

    def test_unknown_key_in_verdict_is_ignored(self, tmp_path) -> None:
        """LLM が知らない key を返しても無視される（存在しない記憶への更新はしない）。"""
        records = [_rec("stale1", updated=timedelta(days=40))]
        conn, service, _ = _run_eval(
            tmp_path,
            records,
            _verdicts_json({"key": "ghost_key", "verdict": "expire"}),
        )
        try:
            assert service.calls == []
        finally:
            conn.close()
