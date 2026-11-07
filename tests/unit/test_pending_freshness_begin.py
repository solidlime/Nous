"""session_begin（get_context）の「期限が近い予定・約束」先出し tests。

計画書 §6 (2026-11-07-active-memory-pi-hook-and-llm-freshness.md):
- 対象: kind=prospective / lifecycle_status=active / valid_until が now+7日以内（過去含む）
- 期限切れ（valid_until < now）も「期限切れに見える」として一覧に含める（expired_but_active）
- 期限順（近い／切れた順）・max 5 件・通常 semantic と gist(consolidated) は出さない
- 記憶が無ければセクション自体を出さない

NOTE: repo.save() は updated_at を get_now() で上書きするため、valid_until は
INSERT 後に直接 UPDATE SQL で設定する（tests/unit/test_freshness_worker.py と同手法）。
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from nous.api.mcp._tools_helpers import _format_lightweight_response
from nous.domain.memory.entities import Memory
from nous.domain.memory.query_service import MemoryQueryService
from nous.domain.persona.entities import PersonaState
from nous.domain.shared.time_utils import get_now
from nous.infrastructure.sqlite.connection import SQLiteConnection
from nous.infrastructure.sqlite.memory_repo import SQLiteMemoryRepository

_HEADING = "【期限が近い予定・約束】"


def _rec(
    key: str,
    *,
    kind: str = "semantic",
    valid_until: datetime | None = None,
    source_type: str = "user_stated",
    lifecycle: str = "active",
) -> tuple[Memory, datetime | None]:
    now = get_now()
    mem = Memory(
        key=key,
        content=f"{key} のテスト記憶内容。",
        created_at=now,
        updated_at=now,
        kind=kind,
        source_type=source_type,
        lifecycle_status=lifecycle,
    )
    return mem, valid_until


def _setup_db(tmp_path, records) -> SQLiteMemoryRepository:
    conn = SQLiteConnection(data_dir=str(tmp_path), persona="test_pending")
    conn.initialize_schema()
    repo = SQLiteMemoryRepository(conn)
    db = conn.get_memory_db()
    for mem, valid_until in records:
        repo.save(mem)
        if valid_until is not None:
            db.execute(
                "UPDATE memories SET valid_until = ? WHERE key = ?",
                (valid_until.isoformat(), mem.key),
            )
    db.commit()
    return repo


def _pending_keys(repo: SQLiteMemoryRepository) -> list[str]:
    result = MemoryQueryService(repo).get_pending_prospective()
    assert result.is_ok, result.error
    return [m.key for m in result.value]


def _render(pending) -> str:
    return _format_lightweight_response(
        PersonaState(persona="test_pending"),
        [],
        [],
        {},
        [],
        pending_freshness=pending,
    )


class TestPendingProspectiveSelect:
    def test_expired_prospective_listed_first(self, tmp_path) -> None:
        """期限切れ prospective 2 件が先頭側（期限順）に出る。"""
        now = get_now()
        repo = _setup_db(
            tmp_path,
            [
                _rec("near2", kind="prospective", valid_until=now + timedelta(days=2)),
                _rec("old1", kind="prospective", valid_until=now - timedelta(days=1)),
                _rec("old3", kind="prospective", valid_until=now - timedelta(days=3)),
            ],
        )
        keys = _pending_keys(repo)
        assert keys == ["old3", "old1", "near2"]

        text = _render(MemoryQueryService(repo).get_pending_prospective().value)
        assert _HEADING in text
        assert "期限切れに見える" in text
        # 期限切れの 2 件が一覧の先頭側（見出し直後）に並ぶ
        lines = [ln for ln in text.splitlines() if ln.startswith("  ⏳")]
        assert "old3 のテスト記憶内容。" in lines[0]
        assert "old1 のテスト記憶内容。" in lines[1]

    def test_semantic_not_listed(self, tmp_path) -> None:
        """通常 semantic は期限が近くても一覧に入らない。"""
        now = get_now()
        repo = _setup_db(
            tmp_path,
            [
                _rec("plain", kind="semantic", valid_until=now + timedelta(days=2)),
                _rec("promise", kind="prospective", valid_until=now + timedelta(days=2)),
            ],
        )
        assert _pending_keys(repo) == ["promise"]

    def test_within_seven_days_listed(self, tmp_path) -> None:
        """期限まで 7 日以内の prospective は一覧に出る。"""
        now = get_now()
        repo = _setup_db(
            tmp_path,
            [_rec("soon", kind="prospective", valid_until=now + timedelta(days=7))],
        )
        assert _pending_keys(repo) == ["soon"]
        assert "soon のテスト記憶内容。" in _render(MemoryQueryService(repo).get_pending_prospective().value)

    def test_beyond_seven_days_not_listed(self, tmp_path) -> None:
        """期限が 7 日を超える prospective は一覧に出ない。"""
        now = get_now()
        repo = _setup_db(
            tmp_path,
            [_rec("later", kind="prospective", valid_until=now + timedelta(days=8))],
        )
        assert _pending_keys(repo) == []

    def test_no_valid_until_and_archived_excluded(self, tmp_path) -> None:
        """valid_until 無し（半永続）と lifecycle != active は対象外。"""
        now = get_now()
        repo = _setup_db(
            tmp_path,
            [
                _rec("eternal", kind="prospective", valid_until=None),
                _rec("archived", kind="prospective", valid_until=now + timedelta(days=1), lifecycle="archived"),
            ],
        )
        assert _pending_keys(repo) == []

    def test_consolidated_excluded_and_max_five(self, tmp_path) -> None:
        """gist（consolidated 派生）は除外し、一覧は max 5 件。"""
        now = get_now()
        records = [_rec("gist", kind="prospective", valid_until=now + timedelta(days=1), source_type="consolidated")]
        records += [_rec(f"p{i}", kind="prospective", valid_until=now + timedelta(days=1, hours=i)) for i in range(6)]
        repo = _setup_db(tmp_path, records)
        keys = _pending_keys(repo)
        assert "gist" not in keys
        assert len(keys) == 5

    def test_no_section_when_empty(self, tmp_path) -> None:
        """記憶が無ければセクション自体を出さない。"""
        repo = _setup_db(tmp_path, [_rec("plain", kind="semantic")])
        pending = MemoryQueryService(repo).get_pending_prospective().value
        assert pending == []
        assert _HEADING not in _render(pending)


@pytest.mark.parametrize("has_pending", [True, False])
def test_section_only_with_pending(has_pending: bool) -> None:
    """pending があるときだけ見出しが出る（formatter 単体）。"""
    now = get_now()
    pending = (
        [Memory(key="p", content="予定", created_at=now, updated_at=now, kind="prospective", valid_until=now)]
        if has_pending
        else []
    )
    assert (_HEADING in _render(pending)) is has_pending
