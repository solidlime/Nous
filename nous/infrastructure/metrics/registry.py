"""プロセス内メトリクス（kanban #10）.

ダッシュボードに出す数字を集めるだけの軽量レジストリ。DB には書かない:

- 検索の letancy と zero-result は毎クエリ書くとイベント表が膨らむのでリングバッファ。
- ツール呼び出しは名前別のカウンタ。
- **プロセス再起動で消える**（恒久記録は ``session_events`` 側が持つ）。
"""

from __future__ import annotations

import threading
from collections import Counter, deque

#: persona ごとに保持する検索サンプル数。p95 を出すには十分で、メモリは小さい。
MAX_SAMPLES = 500

_lock = threading.Lock()
_search_ms: dict[str, deque[float]] = {}
_search_total: Counter[str] = Counter()
_search_zero: Counter[str] = Counter()
_tools: dict[str, Counter[str]] = {}


def observe_search(persona: str, took_ms: float, result_count: int) -> None:
    """検索 1 回分を記録する。"""
    with _lock:
        samples = _search_ms.setdefault(persona, deque(maxlen=MAX_SAMPLES))
        samples.append(float(took_ms))
        _search_total[persona] += 1
        if result_count == 0:
            _search_zero[persona] += 1


def observe_tool(persona: str, name: str) -> None:
    """ツール呼び出し 1 回分を記録する。"""
    with _lock:
        _tools.setdefault(persona, Counter())[name] += 1


def _percentile(values: list[float], ratio: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    idx = min(len(ordered) - 1, max(0, int(round(ratio * (len(ordered) - 1)))))
    return round(ordered[idx], 1)


def snapshot(persona: str) -> dict:
    """1 persona 分の現在値。呼ぶと値が返るだけでリセットはしない。"""
    with _lock:
        samples = list(_search_ms.get(persona, ()))
        total = int(_search_total.get(persona, 0))
        zero = int(_search_zero.get(persona, 0))
        tools = dict(_tools.get(persona, Counter()))
    return {
        "search": {
            "count": total,
            "zero_result": zero,
            "zero_result_rate": round(zero / total, 3) if total else 0.0,
            "p50_ms": _percentile(samples, 0.5),
            "p95_ms": _percentile(samples, 0.95),
            "samples": len(samples),
        },
        "tools": dict(sorted(tools.items(), key=lambda kv: kv[1], reverse=True)[:20]),
    }


def reset(persona: str | None = None) -> None:
    """テスト用。``persona`` を省くと全部消す。"""
    with _lock:
        targets = [persona] if persona is not None else list(_search_ms)
        for p in targets:
            _search_ms.pop(p, None)
            _search_total.pop(p, None)
            _search_zero.pop(p, None)
            _tools.pop(p, None)
