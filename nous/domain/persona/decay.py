"""Shared exponential decay utilities for persona state (body, emotion, etc.)."""

from __future__ import annotations


def compute_exponential_decay(
    current_value: float,
    target: float,
    half_life_hours: float,
    elapsed_hours: float,
    threshold: float = 0.005,
) -> float:
    """指数関数的減衰で current_value を target に近づける。

    Args:
        current_value: 現在の値。
        target: 収束先の目標値。
        half_life_hours: 半減期（時間）。
        elapsed_hours: 経過時間（時間）。
        threshold: 十分近いとみなす閾値（目標値に固定する判定に使う）。

    Returns:
        減衰後の値。目標値に十分近ければ目標値を返す。
    """
    if elapsed_hours <= 0:
        return current_value
    decay_factor = 0.5 ** (elapsed_hours / half_life_hours)
    new_value = target + (current_value - target) * decay_factor
    if abs(new_value - target) < threshold:
        return target
    return round(new_value, 4)
