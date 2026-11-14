"""サーカディアン（時間帯 × 無会話経過）から現在地を決める純関数。

移動の記録（``place.moved`` と生理コスト）は :mod:`nous.application.movement` が
持つ。ここは「どこへ・なぜ動くか」だけを決める。LLM は呼ばない。

冪等性は呼び出し側の門（最後の活動から ``MIN_SILENCE_HOURS`` 以上）と、
移動そのものが ``place.moved`` を残すことで担保する。長時間の空白が 1 回の
移動に落ちるので、ターンを重ねても場所は飛び回らない。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from nous.domain.persona.places import find_place, same_place

if TYPE_CHECKING:
    from datetime import datetime

#: これ未満の空白では動かない（「数時間の空白」= EXTENDED_BREAK と同じ閾値）。
MIN_SILENCE_HOURS = 3.0

#: 昼間に家で寝ていると見なす疲労の閾値。
TIRED = 0.6


@dataclass(frozen=True)
class DriftDecision:
    """自律的に移る先と、その理由（``place.moved`` の ``reason`` に入る）。"""

    place: str
    reason: str
    band: str


def day_band(hour: int) -> str:
    """JST の時（0-23）を 4 つの帯に落とす。"""
    if 0 <= hour < 6:
        return "night"
    if 6 <= hour < 10:
        return "morning"
    if 10 <= hour < 18:
        return "day"
    return "evening"


def decide_drift(
    *,
    now: datetime,
    hours_since_activity: float,
    place: str | None,
    fatigue: float | None,
) -> DriftDecision | None:
    """時間帯と経過時間から移動先を決める。動かないときは ``None``。

    ``place`` は現在地（自由記述でもよい）。``fatigue`` は 0.0-1.0。
    同じ場所に落ちたときは ``None`` を返す（無意味な ``place.moved`` を増やさない）。

    昼も夜も、疲労が ``TIRED`` 以上なら自室へ帰す（本番で疲労 0.85 の個体を
    ラウンジへ「休憩」に送る事故があったので、帯より疲労を先に見る）。
    """
    if hours_since_activity < MIN_SILENCE_HOURS:
        return None

    band = day_band(now.hour)
    tired = fatigue is not None and fatigue >= TIRED

    if band == "night":
        target, reason = "自室", "睡眠・休息"
    elif band == "morning":
        target, reason = "自室", "帰宅・休息"
    elif band == "day":
        target, reason = ("自室", "休息") if tired else ("研究区画", "作業")
    else:
        target, reason = ("自室", "休息") if tired else ("ラウンジ", "休憩")

    known = find_place(target)
    if known is not None and same_place(place, known.name):
        return None
    return DriftDecision(place=target, reason=reason, band=band)
