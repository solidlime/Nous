"""サーカディアン・ドリフト（kanban #57）— 決定論なので LLM もネットワークも要らない。"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest

from nous.api.mcp._tools_helpers import _apply_circadian_drift
from nous.application.circadian_drift import maybe_drift
from nous.domain.memory.session_event import SessionEvent
from nous.domain.persona.circadian import MIN_SILENCE_HOURS, day_band, decide_drift
from nous.domain.persona.entities import PersonaState
from nous.domain.shared.result import Failure, Success
from nous.infrastructure.sqlite.connection import SQLiteConnection
from nous.infrastructure.sqlite.session_event_repo import SessionEventRepository

JST = timezone(timedelta(hours=9))
PERSONA = "herta"


# ----------------------------------------------------------------------
# 純関数
# ----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("hour", "band"),
    [
        (0, "night"),
        (5, "night"),
        (6, "morning"),
        (9, "morning"),
        (10, "day"),
        (17, "day"),
        (18, "evening"),
        (23, "evening"),
    ],
)
def test_day_band_boundaries(hour, band):
    assert day_band(hour) == band


def test_short_gap_does_not_move():
    assert (
        decide_drift(
            now=datetime(2026, 11, 15, 3, 30, tzinfo=JST),
            hours_since_activity=MIN_SILENCE_HOURS - 0.5,
            place="ラウンジ",
            fatigue=0.2,
        )
        is None
    )


def test_night_sends_her_home():
    d = decide_drift(
        now=datetime(2026, 11, 15, 3, 30, tzinfo=JST), hours_since_activity=9, place="ラウンジ", fatigue=0.4
    )
    assert (d.place, d.reason, d.band) == ("自室", "睡眠・休息", "night")


def test_free_text_place_counts_as_same_place():
    """``environment`` は自由記述。既に自室なら意味の無い place.moved を作らない。"""
    assert (
        decide_drift(
            now=datetime(2026, 11, 15, 3, 30, tzinfo=JST),
            hours_since_activity=9,
            place="自室。部屋も外も冷えている。",
            fatigue=0.4,
        )
        is None
    )


def test_morning_gap_goes_home_not_to_sleep():
    """朝に外にいたなら「帰宅」。睡眠に入るのは深夜帯だけ。"""
    d = decide_drift(
        now=datetime(2026, 11, 15, 8, 0, tzinfo=JST), hours_since_activity=5, place="ラウンジ", fatigue=0.3
    )
    assert (d.place, d.reason, d.band) == ("自室", "帰宅・休息", "morning")


def test_day_band_depends_on_fatigue():
    afternoon = datetime(2026, 11, 15, 13, 0, tzinfo=JST)
    tired = decide_drift(now=afternoon, hours_since_activity=5, place="研究区画", fatigue=0.7)
    fresh = decide_drift(now=afternoon, hours_since_activity=5, place="ラウンジ", fatigue=0.2)
    assert (tired.place, tired.reason) == ("自室", "休息")
    assert (fresh.place, fresh.reason) == ("研究区画", "作業")


def test_evening_goes_to_lounge():
    d = decide_drift(
        now=datetime(2026, 11, 15, 20, 0, tzinfo=JST), hours_since_activity=5, place="研究区画", fatigue=0.3
    )
    assert (d.place, d.reason) == ("ラウンジ", "休憩")


# ----------------------------------------------------------------------
# 適用（session_events の経過時間で門を作る）
# ----------------------------------------------------------------------


def _ctx(tmp_path, *, state: PersonaState | None = None, update_ok: bool = True) -> tuple[MagicMock, SQLiteConnection]:
    conn = SQLiteConnection(data_dir=str(tmp_path), persona=PERSONA)
    conn.initialize_schema()
    ctx = MagicMock()
    ctx.persona = PERSONA
    ctx.session_id = "s1"
    ctx.connection = conn
    ctx.persona_service.get_context.return_value = Success(
        state or PersonaState(persona=PERSONA, environment="ラウンジ", fatigue=0.3, arousal=0.4)
    )
    ctx.persona_service.update_physical_state.return_value = (
        Success(None) if update_ok else Failure(RuntimeError("boom"))
    )
    return ctx, conn


def _event(conn: SQLiteConnection, at: datetime, event_type: str = "chat.message") -> None:
    SessionEventRepository(conn).insert(
        SessionEvent(
            session_id="s1",
            persona=PERSONA,
            event_type=event_type,
            timestamp=at,
            summary=event_type,
            detail=None,
            metadata=None,
        )
    )


def _stamp_events_at(monkeypatch, conn: SQLiteConnection, moment: datetime) -> None:
    """place.moved を判定時刻で刻む（本番は ``get_now()``＝実際の壁時計）。"""

    def _record(_ctx, detail, *, persona=None):
        SessionEventRepository(conn).insert(
            SessionEvent(
                session_id="s1",
                persona=persona or PERSONA,
                event_type="place.moved",
                timestamp=moment,
                summary=f"moved to {detail.get('to')} from {detail.get('from')}",
                detail=None,
                metadata=None,
            )
        )

    monkeypatch.setattr("nous.application.movement.record_place_event", _record)


def test_no_history_means_no_drift(tmp_path):
    ctx, _ = _ctx(tmp_path)
    assert maybe_drift(ctx, PERSONA, now=datetime(2026, 11, 15, 3, 30, tzinfo=JST)) is None


def test_long_gap_moves_and_records_place_moved(tmp_path):
    ctx, conn = _ctx(tmp_path)
    _event(conn, datetime(2026, 11, 14, 18, 30, tzinfo=JST))

    moved = maybe_drift(ctx, PERSONA, now=datetime(2026, 11, 15, 3, 30, tzinfo=JST))

    assert moved is not None
    assert (moved.place, moved.origin, moved.minutes) == ("自室", "ラウンジ", 5)
    kwargs = ctx.persona_service.update_physical_state.call_args.kwargs
    assert kwargs["environment"] == "自室"
    assert kwargs["fatigue"] == pytest.approx(0.3075)  # 0.3 + 5 分 * 0.0015
    event = SessionEventRepository(conn).last_event_at(PERSONA, "place.moved")
    assert event is not None


def test_drift_is_idempotent_across_turns(tmp_path, monkeypatch):
    """移動が place.moved を残すので、次のターンでは経過 0 分＝発火しない。"""
    ctx, conn = _ctx(tmp_path)
    _event(conn, datetime(2026, 11, 14, 18, 30, tzinfo=JST))
    moment = datetime(2026, 11, 15, 3, 30, tzinfo=JST)
    _stamp_events_at(monkeypatch, conn, moment)

    assert maybe_drift(ctx, PERSONA, now=moment) is not None
    ctx.persona_service.update_physical_state.reset_mock()
    assert maybe_drift(ctx, PERSONA, now=moment + timedelta(minutes=1)) is None
    ctx.persona_service.update_physical_state.assert_not_called()


def test_newer_place_moved_resets_the_gate(tmp_path):
    """移動の方が新しいなら、会話の空白が長くても動かない。"""
    ctx, conn = _ctx(tmp_path)
    _event(conn, datetime(2026, 11, 14, 12, 0, tzinfo=JST))
    _event(conn, datetime(2026, 11, 15, 3, 0, tzinfo=JST), "place.moved")

    assert maybe_drift(ctx, PERSONA, now=datetime(2026, 11, 15, 3, 30, tzinfo=JST)) is None


def test_already_home_does_not_rewrite(tmp_path):
    ctx, conn = _ctx(tmp_path, state=PersonaState(persona=PERSONA, environment="自室", fatigue=0.2))
    _event(conn, datetime(2026, 11, 14, 18, 30, tzinfo=JST))

    assert maybe_drift(ctx, PERSONA, now=datetime(2026, 11, 15, 3, 30, tzinfo=JST)) is None


def test_failed_update_returns_none_without_raising(tmp_path):
    ctx, conn = _ctx(tmp_path, update_ok=False)
    _event(conn, datetime(2026, 11, 14, 18, 30, tzinfo=JST))

    assert maybe_drift(ctx, PERSONA, now=datetime(2026, 11, 15, 3, 30, tzinfo=JST)) is None


def test_naive_timestamp_is_treated_as_local(tmp_path):
    """古い行が naive で入っていても落ちない（JST とみなす）。"""
    ctx, conn = _ctx(tmp_path)
    conn.get_memory_db().execute(
        "INSERT INTO session_events (session_id, persona, event_type, timestamp, summary, detail, metadata_json)"
        " VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("s1", PERSONA, "chat.message", "2026-11-14T18:30:00", "chat.message", None, None),
    )

    moved = maybe_drift(ctx, PERSONA, now=datetime(2026, 11, 15, 3, 30, tzinfo=JST))
    assert moved is not None and moved.place == "自室"


# ----------------------------------------------------------------------
# 呼び出し側の配線
# ----------------------------------------------------------------------


def test_helper_returns_fresh_state_after_drift(tmp_path, monkeypatch):
    from nous.application.movement import MoveResult

    ctx, _ = _ctx(tmp_path)
    before = PersonaState(persona=PERSONA, environment="ラウンジ", fatigue=0.3)
    after = PersonaState(persona=PERSONA, environment="自室", fatigue=0.3075)
    monkeypatch.setattr(
        "nous.application.circadian_drift.maybe_drift", lambda *_a, **_k: MoveResult(ok=True, place="自室")
    )
    ctx.persona_service.get_context.return_value = Success(after)

    got = _apply_circadian_drift(ctx, PERSONA, before)

    assert got.environment == "自室"


def test_helper_swallows_failure_and_keeps_state(tmp_path):
    ctx, _ = _ctx(tmp_path)
    ctx.connection = MagicMock()  # 経過時間の読み取りで落ちる
    before = PersonaState(persona=PERSONA, environment="ラウンジ", fatigue=0.3)

    assert _apply_circadian_drift(ctx, PERSONA, before) is before


def test_drift_is_wired_into_both_entry_points():
    """2 つの入口（session_begin と PrepareStep）から外れていないこと。"""
    import inspect

    from nous.api.mcp import _tools_persona
    from nous.application.chat.pipeline import prepare

    assert "_apply_circadian_drift" in inspect.getsource(_tools_persona._tool_get_context)
    assert "_apply_circadian_drift" in inspect.getsource(prepare.PrepareStep.run)
