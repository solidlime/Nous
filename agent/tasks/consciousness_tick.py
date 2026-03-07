"""
意識ティック関連のユーティリティ。

時刻を日本語の文脈文字列（深夜・朝・昼など）に変換するヘルパーを提供する。
ContextBuilder から呼ばれ、意識ティックプロンプトの time_context フィールドを埋める。
"""

from datetime import datetime


def get_time_context(now: datetime | None = None) -> str:
    """時刻を日本語の文脈文字列に変換する。

    Args:
        now: 変換する datetime（省略時は現在時刻）。

    Returns:
        時間帯を表す日本語文字列。
        例: 0〜3時 → "深夜", 6〜8時 → "朝", 12〜13時 → "昼", 20〜22時 → "夜"
    """
    if now is None:
        now = datetime.now()
    hour = now.hour
    if 0 <= hour < 4:
        return "深夜"
    if 4 <= hour < 6:
        return "夜明け前"
    if 6 <= hour < 9:
        return "朝"
    if 9 <= hour < 12:
        return "午前中"
    if 12 <= hour < 14:
        return "昼"
    if 14 <= hour < 17:
        return "午後"
    if 17 <= hour < 20:
        return "夕方"
    if 20 <= hour < 23:
        return "夜"
    # 23 時台
    return "深夜"
