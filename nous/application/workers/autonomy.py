"""自立活動の共有ゲート — 深夜・疲労・痛み・覚醒で自発を止める（kanban #152）。

``ProactiveWorker``（発言）と ``ActivityWorker``（行動）は、どちらも
``SessionConfig.autonomy_enabled`` 1 本で起動し、この ``quiet_reason`` で
「今やってよいか」を共有する。None なら活動してよい。

止める条件（順に判定。最初に当たった理由を返す）:

1. ``autonomy_quiet_hours``（既定 01:00-08:00、日跨ぎ可）
2. ``fatigue >= autonomy_fatigue_limit`
3. ``pain >= autonomy_pain_limit`
4. ``arousal <= autonomy_arousal_floor`

体調は読むだけ（DB 書き込みなし）。取れない時は素通し（None）— 状態が不明なだけで
人形を止める理由にはならない。ユーザー発言への応答はこのゲートを通らない（自発だけ止める）。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from nous.domain.config.session_config import SessionConfig, parse_quiet_hours
from nous.domain.shared.result import Success
from nous.infrastructure.logging.structured import get_logger

if TYPE_CHECKING:
    from datetime import datetime, time

    from nous.application.use_cases import AppContext

logger = get_logger(__name__)


def quiet_reason(ctx: AppContext, now: datetime) -> str | None:
    """自発活動を止める理由（日本語）。None なら活動してよい。"""
    session_config = getattr(getattr(ctx, "config", None), "session_config", None) or SessionConfig()
    hours = parse_quiet_hours(session_config.autonomy_quiet_hours)
    if hours is not None and _in_range(now, hours[0], hours[1]):
        return "深夜の就寝時間"

    state = _body_state(ctx)
    if state is None:
        return None
    fatigue = _as_float(getattr(state, "fatigue", None))
    if fatigue is not None and fatigue >= session_config.autonomy_fatigue_limit:
        return "疲労が高い"
    pain = _as_float(getattr(state, "pain", None))
    if pain is not None and pain >= session_config.autonomy_pain_limit:
        return "痛みが強い"
    # floor=0.0 は「覚醒を見ない」の意（判定は <= なので 0 を素通しさせない）。
    # 平常時の arousal は 0% で、床を立てると常時止まってしまう。
    arousal = _as_float(getattr(state, "arousal", None))
    floor = session_config.autonomy_arousal_floor
    if floor > 0.0 and arousal is not None and arousal <= floor:
        return "覚醒が低い"
    return None


def _in_range(now: datetime, start: time, end: time) -> bool:
    """``now`` の時刻が [start, end) に入るか。start > end は日跨ぎ。"""
    t = now.timetz().replace(tzinfo=None)
    if start == end:  # 開始 == 終了は 24 時間停止（parse_quiet_hours の宣言どおり）
        return True
    if start <= end:
        return start <= t < end
    return t >= start or t < end


def _body_state(ctx: AppContext):
    """現在の persona state（fatigue/pain/arousal を持つ）。取れなければ None。

    activity_worker.``_state_text`` と同じ経路（persona_service.get_context）。
    """
    try:
        result = ctx.persona_service.get_context(ctx.persona)
    except Exception:
        logger.debug("autonomy: body state unavailable", exc_info=True)
        return None
    return result.value if isinstance(result, Success) else None


def _as_float(value: object) -> float | None:
    """int/float だけ通す（bool と None は未設定扱い）。"""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)
