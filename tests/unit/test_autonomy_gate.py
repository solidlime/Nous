"""自発活動の共有ゲート quiet_reason と SessionConfig.autonomy_* のテスト。

自律活動は「体調・時間帯で休む」を 1 箇所（quiet_reason）に集約する。None なら活動して
よい。ここが壊れると深夜や疲労時に人形が起き続けるので、境界値も固定する。
"""

from __future__ import annotations

import logging
from datetime import datetime
from unittest.mock import MagicMock
from zoneinfo import ZoneInfo

import pytest

from nous.application.workers.autonomy import quiet_reason
from nous.domain.config.session_config import SessionConfig
from nous.domain.shared.result import Failure, Success

TZ = ZoneInfo("Asia/Tokyo")


def _state(*, fatigue: float | None = 0.2, pain: float | None = 0.0, arousal: float | None = 0.5):
    state = MagicMock()
    state.fatigue = fatigue
    state.pain = pain
    state.arousal = arousal
    return state


def _ctx(state=None, *, raises: bool = False, **config) -> MagicMock:
    ctx = MagicMock()
    ctx.persona = "test"
    cfg = MagicMock()
    cfg.session_config = SessionConfig(**config)
    ctx.config = cfg
    if raises:
        ctx.persona_service.get_context.side_effect = RuntimeError("db down")
    else:
        ctx.persona_service.get_context.return_value = Success(state or _state())
    return ctx


def _at(hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 11, 28, hour, minute, tzinfo=TZ)


# --- 時間帯 ---------------------------------------------------------------


@pytest.mark.parametrize("hour", [1, 3, 7])
def test_midnight_quiet_hours_is_quiet(hour: int) -> None:
    """既定の 01:00-08:00 は休む。"""
    assert quiet_reason(_ctx(), _at(hour)) == "深夜の就寝時間"


def test_daytime_is_not_quiet() -> None:
    assert quiet_reason(_ctx(), _at(12)) is None


@pytest.mark.parametrize("hour", [23, 0, 5])
def test_quiet_hours_wrapping_midnight(hour: int) -> None:
    """日跨ぎ (22:00-06:00) は両側の端を含めて休む。"""
    assert quiet_reason(_ctx(autonomy_quiet_hours="22:00-06:00"), _at(hour)) == "深夜の就寝時間"


@pytest.mark.parametrize("hour", [6, 12, 21])
def test_quiet_hours_wrapping_midnight_outside(hour: int) -> None:
    """日跨ぎの外側は活動してよい（終端の 06:00 は含まない）。"""
    assert quiet_reason(_ctx(autonomy_quiet_hours="22:00-06:00"), _at(hour)) is None


@pytest.mark.parametrize("hour", [3, 7, 8, 12, 23])
def test_quiet_hours_start_equals_end_stops_all_day(hour: int) -> None:
    """開始 == 終了は 24 時間停止（parse_quiet_hours の宣言に合わせる）。"""
    assert quiet_reason(_ctx(autonomy_quiet_hours="08:00-08:00"), _at(hour)) == "深夜の就寝時間"


def test_empty_quiet_hours_disables_the_night_gate() -> None:
    assert quiet_reason(_ctx(autonomy_quiet_hours=""), _at(3)) is None


# --- 体調 ---------------------------------------------------------------


def test_high_fatigue_is_quiet() -> None:
    assert quiet_reason(_ctx(_state(fatigue=0.8)), _at(12)) == "疲労が高い"


def test_fatigue_boundary_inclusive() -> None:
    """しきい値ちょうどは休む（>=）。"""
    assert quiet_reason(_ctx(_state(fatigue=0.7)), _at(12)) == "疲労が高い"


def test_pain_is_quiet() -> None:
    assert quiet_reason(_ctx(_state(pain=0.6)), _at(12)) == "痛みが強い"


def test_low_arousal_is_quiet() -> None:
    assert quiet_reason(_ctx(_state(arousal=0.01)), _at(12)) == "覚醒が低い"


def test_arousal_boundary_inclusive() -> None:
    assert quiet_reason(_ctx(_state(arousal=0.05)), _at(12)) == "覚醒が低い"


def test_unset_metrics_pass_through() -> None:
    """未設定 (None) は判定しない（素通し）。"""
    assert quiet_reason(_ctx(_state(fatigue=None, pain=None, arousal=None)), _at(12)) is None


def test_body_state_unavailable_passes_through() -> None:
    assert quiet_reason(_ctx(raises=True), _at(12)) is None


def test_body_state_failure_passes_through() -> None:
    ctx = _ctx()
    ctx.persona_service.get_context.return_value = Failure("nope")
    assert quiet_reason(ctx, _at(12)) is None


def test_night_gate_wins_over_body_state() -> None:
    """深夜は体調を見るまでもなく休む（順序の固定）。"""
    assert quiet_reason(_ctx(_state(fatigue=0.9), autonomy_quiet_hours="01:00-08:00"), _at(3)) == "深夜の就寝時間"


# --- SessionConfig -------------------------------------------------------


def test_quiet_hours_invalid_value_falls_back_with_warning(caplog: pytest.LogCaptureFixture) -> None:
    """不正値は例外で落とさず既定値に戻す。"""
    with caplog.at_level(logging.WARNING):
        config = SessionConfig(autonomy_quiet_hours="25:00-8:00")
    assert config.autonomy_quiet_hours == "01:00-08:00"
    assert "autonomy_quiet_hours" in caplog.text


def test_autonomy_defaults() -> None:
    config = SessionConfig()
    assert config.autonomy_enabled is False
    assert config.autonomy_fatigue_limit == 0.7
    assert config.autonomy_pain_limit == 0.5
    assert config.autonomy_arousal_floor == 0.05
