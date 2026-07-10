"""BodyStateDecay: 時間経過による身体状態の自然な変化ロジック。"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from nous.domain.persona.body_state import extract_body_metrics

if TYPE_CHECKING:
    from nous.domain.persona.entities import PersonaState
    from nous.domain.persona.service import PersonaService

logger = logging.getLogger(__name__)


# 身体状態の減衰設定: decay_hours で目標値へ半減
# fatigue: 休息で徐々に回復 (0.0 へ)
# warmth: 常温へ (0.5 へ)
# arousal: 安静時へ (0.0 へ)
_BODY_DECAY_CFG = {
    "fatigue": {"target": 0.0, "half_life_hours": 4.0},
    "warmth": {"target": 0.5, "half_life_hours": 2.0},
    "arousal": {"target": 0.0, "half_life_hours": 1.5},
    "heart_rate": {"target": 0.5, "half_life_hours": 1.0},
    "pain": {"target": 0.0, "half_life_hours": 2.0},
}


def compute_body_decay(current_value: float, target: float, half_life_hours: float, elapsed_hours: float) -> float:
    """指数関数的減衰で目標値に近づける。"""
    if elapsed_hours <= 0:
        return current_value
    if abs(current_value - target) < 0.01:
        return current_value
    # 半減期ベースの減衰係数
    decay_factor = 0.5 ** (elapsed_hours / half_life_hours)
    new_value = target + (current_value - target) * decay_factor
    # 目標に十分近ければ目標値に固定
    if abs(new_value - target) < 0.01:
        return target
    return round(new_value, 4)


def compute_body_state_decay(state: PersonaState, elapsed_hours: float) -> dict[str, str]:
    """
    経過時間に基づいて body_state の減衰値を計算。
    {key: new_value_str} の形で返す。変化がないキーは含めない。
    """
    if elapsed_hours <= 0:
        return {}

    updates: dict[str, str] = {}

    # fatigue, warmth, arousal, heart_rate, pain が減衰対象
    for key in ("fatigue", "warmth", "arousal", "heart_rate", "pain"):
        current_raw = getattr(state, key, None)
        if current_raw is None:
            continue
        try:
            current = float(current_raw)
        except (ValueError, TypeError):
            continue

        cfg = _BODY_DECAY_CFG[key]
        new_value = compute_body_decay(current, cfg["target"], cfg["half_life_hours"], elapsed_hours)

        if abs(new_value - current) > 0.01:
            updates[key] = str(new_value)

    return updates


async def apply_body_decay_if_needed(
    persona_service: PersonaService,
    persona: str,
    state: PersonaState,
) -> bool:
    """
    PersonaState の last_conversation_time から経過時間を計算し、
    必要であれば身体状態を減衰させて SQLite に永続化する。
    変化があった場合は True を返す。
    """
    from nous.domain.shared.time_utils import get_now

    last_conv = state.last_conversation_time
    if last_conv is None:
        return False

    now = get_now()
    elapsed_hours = (now - last_conv).total_seconds() / 3600.0

    updates = compute_body_state_decay(state, elapsed_hours)
    if not updates:
        return False

    # Record body state BEFORE decay
    before_body = extract_body_metrics(state)
    persona_service.record_body_state(persona, before_body, context="before_body_decay")

    try:
        result = persona_service.update_physical_state(persona, **updates)
        if result.is_ok:
            logger.info(
                "BodyDecay: %s (elapsed=%.1fh)",
                ", ".join(f"{k}={v}" for k, v in updates.items()),
                elapsed_hours,
            )
            # Record body state AFTER decay (re-read fresh state)
            after_result = persona_service.get_context(persona)
            if after_result.is_ok:
                after_state = after_result.value  # type: ignore[union-attr]
                after_body = extract_body_metrics(after_state)
                persona_service.record_body_state(persona, after_body, context="after_body_decay")
            return True
        logger.warning("BodyDecay: update_physical_state failed: %s", result.error)
    except Exception as e:
        logger.warning("BodyDecay: unexpected error: %s", e)
    return False
