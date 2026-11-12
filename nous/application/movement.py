"""現在地の変更を 1 経路に集約する。

場所を書く経路は ``move``（chat ツール）、``update_context(environment=...)``
（chat / MCP 共有）、記憶抽出の state 適用（``chat/memory_extractor.py`` と
``hooks/memory_extraction.py``）の 3 つ。書き手が分かれると ``place.moved`` が
一部にしか残らず、ダッシュボードの滞在時間（直近の ``place.moved``）が嘘になる。
**これらの経路は必ずここを通す**（移動 = 生理コスト + ``place.moved`` 1 行）。
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from nous.domain.persona.body import body_action_hint
from nous.domain.persona.entities import PersonaState
from nous.domain.persona.places import find_place, same_place, travel_minutes
from nous.domain.shared.result import Success
from nous.infrastructure.logging.structured import get_logger

if TYPE_CHECKING:
    from nous.application.use_cases import AppContext


logger = get_logger(__name__)

#: 移動 1 分あたりの生理コスト。上限は 1 回の移動で 0.15 / 0.03（長距離でも飽和させる）。
FATIGUE_PER_MINUTE = 0.0015
AROUSAL_PER_MINUTE = 0.0006
MAX_FATIGUE_DELTA = 0.15
MAX_AROUSAL_DELTA = 0.03


@dataclass(frozen=True)
class MoveResult:
    ok: bool
    place: str = ""
    origin: str | None = None
    minutes: int = 0
    fatigue: float | None = None
    arousal: float | None = None
    fatigue_delta: float = 0.0
    arousal_delta: float = 0.0
    known: bool = True
    body: str | None = None
    error: str | None = None
    extra: dict = field(default_factory=dict)


def apply_move(
    ctx: AppContext,
    persona: str,
    target: str,
    *,
    minutes: int | None = None,
    reason: str | None = None,
    environment_text: str | None = None,
    charge_if_unknown: bool = True,
) -> MoveResult:
    """``target`` へ移動する。コストを課し、``place.moved`` を 1 行残す。

    ``environment_text`` を渡すと、状態の ``environment`` にはその文字列を書く
    （``update_context`` の自由記述を保つため）。省略時はカタログの正式名。
    ``minutes`` は所要分の上書き（テスト・外部見積り用）。省略時は場所から計算する。

    ``charge_if_unknown=False`` は「カタログに解決できない記述は移動とみなさない」
    （記憶抽出のように、同じ場所を散文で書き直すだけの経路が 10 分を払い続けるのを防ぐ）。

    同期関数: 呼び出し元はすべて async 文脈だが、内部に await は無い（sqlite は同期）。
    """
    place = (target or "").strip()
    if not place:
        return MoveResult(ok=False, error="place is required")

    state_result = ctx.persona_service.get_context(persona)
    if not isinstance(state_result, Success):
        # 読めない状態を 0.0 として書き込むと、実値（疲労・痛み）を静かに消す。
        return MoveResult(ok=False, error="現在の状態を読めないため移動を記録できない")
    state = state_result.value
    origin = getattr(state, "environment", None)

    known = find_place(place)
    if known is None and not charge_if_unknown and minutes is None:
        cost = 0
    else:
        cost = travel_minutes(origin, place) if minutes is None else max(0, int(minutes))
    old_fatigue = _as_float(getattr(state, "fatigue", None), 0.0)
    old_arousal = _as_float(getattr(state, "arousal", None), 0.0)
    if cost > 0:
        new_fatigue = min(1.0, old_fatigue + min(MAX_FATIGUE_DELTA, cost * FATIGUE_PER_MINUTE))
        new_arousal = min(1.0, old_arousal + min(MAX_AROUSAL_DELTA, cost * AROUSAL_PER_MINUTE))
    else:
        new_fatigue, new_arousal = old_fatigue, old_arousal

    label = known.name if known is not None else place
    origin_known = find_place(origin or "")
    origin_label = origin_known.name if origin_known is not None else origin
    # 同じ場所なら状態の自由記述を保ち、動いた時だけ正式名に揃える。
    moved = not same_place(origin, place)
    write_environment = environment_text or (label if moved else (origin or label))

    updates: dict[str, object] = {"environment": write_environment}
    if cost > 0:
        updates["fatigue"] = new_fatigue
        updates["arousal"] = new_arousal
    updated = ctx.persona_service.update_physical_state(persona, **updates)
    if not getattr(updated, "is_ok", False):
        error = getattr(updated, "error", None)
        return MoveResult(ok=False, error=str(error) if error else "状態を更新できなかった")

    if cost > 0:
        record_place_event(
            ctx,
            {
                "from": origin_label,
                "to": label,
                "minutes": cost,
                "known": known is not None,
                "reason": reason or None,
                "fatigue": round(new_fatigue, 3),
                "arousal": round(new_arousal, 3),
            },
            persona=persona,
        )

    body = body_action_hint(
        PersonaState(
            persona=persona,
            fatigue=new_fatigue,
            arousal=new_arousal,
            pain=getattr(state, "pain", None),
            warmth=getattr(state, "warmth", None),
        )
    )
    extra = {}
    if known is None and cost > 0:
        extra["note"] = f"「{label}」は新しい場所として記録した（以後の語彙になる）。"
    return MoveResult(
        ok=True,
        place=label,
        origin=origin_label,
        minutes=cost,
        fatigue=round(new_fatigue, 3),
        arousal=round(new_arousal, 3),
        fatigue_delta=round(new_fatigue - old_fatigue, 4),
        arousal_delta=round(new_arousal - old_arousal, 4),
        known=known is not None,
        body=body or None,
        extra=extra,
    )


def record_place_event(ctx: AppContext, detail: dict, *, persona: str | None = None) -> None:
    """``place.moved`` を session_events に残す（テーブルは増やさない）。"""
    try:
        from nous.domain.memory.session_event import SessionEvent
        from nous.domain.shared.time_utils import get_now
        from nous.infrastructure.sqlite.session_event_repo import SessionEventRepository

        SessionEventRepository(ctx.connection).insert(
            SessionEvent(
                session_id=getattr(ctx, "session_id", None) or "chat",
                persona=persona or ctx.persona,
                event_type="place.moved",
                timestamp=get_now(),
                summary=f"moved to {detail.get('to')} from {detail.get('from')}"[:200],
                detail=json.dumps(detail, ensure_ascii=False),
                metadata=None,
            )
        )
    except Exception:
        logger.exception("failed to record place.moved")


def _as_float(value: object, default: float) -> float:
    if value is None:
        return default
    try:
        number = float(str(value))
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default
