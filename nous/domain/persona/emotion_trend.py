"""EmotionTrend: 感情推移のナラティブ生成（決定論的テンプレート・LLM不使用）。

#081 設計: 上限3句・予算 ≤120トークン目安。減衰通知が既に語った
context="time_decay" のレコードは列挙せずスキップする。
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from nous.domain.shared.time_utils import get_now

if TYPE_CHECKING:
    from datetime import datetime

    from nous.domain.persona.entities import EmotionRecord

_MAX_CONTEXT_CHARS = 40


def _truncate(s: str) -> str:
    return s[:_MAX_CONTEXT_CHARS] + "…" if len(s) > _MAX_CONTEXT_CHARS else s


def _format_elapsed(hours: float) -> str:
    """_tools_helpers._format_emotion_decay_note と同一仕様の経過時刻表記。

    重複はこの2箇所のみ。層を跨ぐ統合はしない。
    """
    if hours >= 24:
        return f"{hours / 24:.0f}日"
    if hours >= 1:
        return f"{hours:.0f}時間"
    return f"{hours * 60:.0f}分"


def _intensity_label(intensity: float) -> str:
    """既存3段階の再利用（context_loader.py:139 と同一の離散化）。"""
    return "強い" if intensity > 0.6 else "やや強い" if intensity > 0.3 else "弱い"


def clean_context(context: str | None) -> str | None:
    """Phase 0 が context に書いた {"va": [...]} 形JSONを表示から除去する。

    JSONで note キーがあればそれを使い（40字超「…」切り詰め）、
    JSONでnote無しは None。非JSONは s[:40] +（40字超なら）「…」。
    """
    if context is None:
        return None
    s = context.strip()
    if not s:
        return None
    try:
        data = json.loads(s)
    except ValueError:
        return _truncate(s)
    if isinstance(data, dict):
        note = data.get("note")
        if isinstance(note, str) and note:
            return _truncate(note)
        return None
    return None


def _point(emotion: str, context: str | None) -> str:
    cleaned = clean_context(context)
    return f"{emotion}（{cleaned}）" if cleaned else emotion


def build_emotion_trend_narrative(
    records: list[EmotionRecord],
    current_emotion: str,
    current_intensity: float,
) -> str:
    """get_emotion_history(limit=5) の戻りを受け取り感情の流れを1文で返す。

    空文字列ならセクション省略。3タイプ: 移行 / 減衰 / 一様。
    """
    pts: list[tuple[str, float, str | None, datetime]] = [
        (r.emotion, r.intensity, r.context, r.timestamp) for r in records if r.context != "time_decay"
    ]
    if len(pts) < 2:
        return ""

    # 履歴の末尾が現在状態と同一ラベルなら履歴側を落として現在値を最終点にする
    last_ctx: str | None = None
    if pts[-1][0] == current_emotion:
        last_ctx = pts[-1][2]
        pts = pts[:-1]
    pts.append((current_emotion, current_intensity, last_ctx, get_now()))

    prev, cur = pts[-2], pts[-1]
    prev_label = _intensity_label(prev[1])
    cur_label = _intensity_label(cur[1])

    if prev[0] == "neutral" and cur[0] != "neutral":
        # prev=neutral は update_context の normalize（calm→neutral 等）で到達可能。
        # 移行テンプレートの「まず neutralを感じ」破文を避ける neutral 起点テンプレート。
        return f"感情の流れ: 静かに落ち着いていたが、{_point(cur[0], cur[2])}へ移った。いまは {cur[0]}（{cur_label}）。"

    if prev[0] != cur[0] and (cur[0] == "neutral" or (cur_label == "弱い" and prev_label != "弱い")):
        elapsed_hours = max(0.0, (cur[3] - prev[3]).total_seconds() / 3600.0)
        t = _format_elapsed(elapsed_hours)
        if cur[0] == "neutral":
            return f"感情の流れ: {_point(prev[0], prev[2])}を感じていたが、{t}のうちに静かに薄れて落ち着いた。いまは落ち着いている。"
        return f"感情の流れ: {_point(prev[0], prev[2])}を感じていたが、{t}のうちに静かに薄れて落ち着いた。いまは {cur[0]}（{cur_label}）。"

    if prev[0] == cur[0]:
        if prev_label == cur_label:
            return ""
        direction = "深まっている" if cur[1] > prev[1] else "和らいでいる"
        return f"感情の流れ: {_point(cur[0], cur[2])}は続いており、{direction}（{prev_label}→{cur_label}）。"

    return (
        f"感情の流れ: まず {_point(prev[0], prev[2])}を感じ、その後 {_point(cur[0], cur[2])}へ移った。"
        f"いまは {cur[0]}（{cur_label}）が続いている。"
    )
