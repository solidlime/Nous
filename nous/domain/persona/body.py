"""身体の数値から「行動の傾向」を 1〜2 文にする（助言専用・強制はしない）。

身体の数値（``fatigue`` 等）はそのまま状態ブロックに出ているが、LLM は数字を
読んでも行動に結びつけないことがある。閾値をまたいだ時だけ**短い助言**を添える。
制約ではないので、本人が無視しても何も起きない（移動を拒否したりはしない）。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from nous.domain.persona.entities import PersonaState

# (属性, 比較, 閾値, 助言) — 上から順に最大 2 件だけ採る（注入を膨らませない）
_RULES: tuple[tuple[str, str, float, str], ...] = (
    ("fatigue", ">=", 0.75, "強い疲労がある（長い移動や連続作業は重い）"),
    ("pain", ">=", 0.50, "痛みがある"),
    ("warmth", "<=", 0.30, "身体が冷えている"),
    ("arousal", ">=", 0.80, "覚醒が高く落ち着かない"),
    ("fatigue", ">=", 0.55, "疲れが溜まっている"),
)

_MAX_HINTS = 2


def body_action_hint(state: PersonaState | None) -> str | None:
    """閾値を超えた項目の助言を 1 行にまとめる。該当なしは ``None``。"""
    if state is None:
        return None
    hints: list[str] = []
    for key, op, threshold, text in _RULES:
        if len(hints) >= _MAX_HINTS:
            break
        try:
            value = getattr(state, key, None)
            if value is None:
                continue
            number = float(value)
        except (TypeError, ValueError):
            continue
        if (op == ">=" and number >= threshold) or (op == "<=" and number <= threshold):
            hints.append(text)
    return " / ".join(hints) if hints else None
