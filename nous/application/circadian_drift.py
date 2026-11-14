"""時間帯 × 無会話経過による場所の自律ドリフト（LLM 課金ゼロ）。

呼び出しは ``session_begin`` / チャットの PrepareStep の入口だけ。常駐ワーカーは
増やさない。移動そのものが ``place.moved`` を残すので、次の判定の基準時刻が
その場で前進する＝ターンを重ねても連続発火しない（冪等）。

身体の回復はここで足さない。既存の身体減衰（``body_decay``、疲労の半減期 4h）が
``last_conversation_time`` 基準で同じ空白を既に見ているので、二重に回復させない。
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

from nous.application.movement import MoveResult, apply_move
from nous.domain.persona.circadian import MIN_SILENCE_HOURS, DriftDecision, decide_drift
from nous.domain.shared.result import Success
from nous.domain.shared.time_utils import get_now
from nous.infrastructure.logging.structured import get_logger

if TYPE_CHECKING:
    from nous.application.use_cases import AppContext
    from nous.domain.persona.entities import PersonaState

logger = get_logger(__name__)


def _as_float(value: object) -> float | None:
    if value is None:
        return None
    try:
        number = float(str(value))
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _last_activity(ctx: AppContext, persona: str):
    """最後に「本人が動いた」時刻（会話 or 移動）。読めなければ None。"""
    from nous.infrastructure.sqlite.session_event_repo import SessionEventRepository

    repo = SessionEventRepository(ctx.connection)
    stamps = [
        stamp
        for stamp in (repo.last_activity_at(persona), repo.last_event_at(persona, "place.moved"))
        if stamp is not None
    ]
    return max(stamps) if stamps else None


def maybe_drift(
    ctx: AppContext,
    persona: str,
    *,
    now=None,
    min_hours: float = MIN_SILENCE_HOURS,
) -> MoveResult | None:
    """必要なら場所を移す。動いたら ``MoveResult``、動かない/失敗なら ``None``。"""
    state_result = ctx.persona_service.get_context(persona)
    if not isinstance(state_result, Success):
        return None
    state: PersonaState = state_result.value

    moment = now or get_now()
    last = _last_activity(ctx, persona)
    if last is None:
        return None
    if last.tzinfo is None:  # sqlite に naive で入った古い行を JST とみなす
        last = last.replace(tzinfo=moment.tzinfo)
    elapsed_hours = (moment - last).total_seconds() / 3600.0

    decision: DriftDecision | None = decide_drift(
        now=moment,
        hours_since_activity=elapsed_hours,
        place=getattr(state, "environment", None),
        fatigue=_as_float(getattr(state, "fatigue", None)),
    )
    if decision is None:
        return None

    result = apply_move(ctx, persona, decision.place, reason=decision.reason)
    if not result.ok:
        logger.warning("circadian drift failed: %s", result.error)
        return None
    logger.info(
        "circadian drift: %s -> %s (%s, elapsed=%.1fh)",
        result.origin,
        result.place,
        decision.band,
        elapsed_hours,
    )
    return result
