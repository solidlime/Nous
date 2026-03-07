"""
Ebbinghaus 忘却曲線ワーカー (Nous 版)。

MemoryMCP の forgetting.py を移植し、設定参照先を config.py に変更。

忘却モデル:
    R(t) = e^(-t / S)

    R = retention (0.0–1.0)
    t = 最終アクセスからの経過日数
    S = stability (想起するたびに増加)

strength = importance * R(t)

`importance` は作成時に固定。`strength` は memory_strength テーブルが保持し、
バックグラウンドの decay ワーカーが定期更新する。
想起時は boost_on_recall() で strength をリセットし stability を増加させる。
"""

import math
import os
import sqlite3
import threading
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

from config import load_config, get_db_path, get_data_dir

# ── チューニング定数 ──────────────────────────────────────────────────────────
STABILITY_GROWTH_FACTOR = 1.5   # 想起ごとに stability を掛けるファクタ
STABILITY_MAX = 365.0           # stability の上限 (約 1 年半減期)
STABILITY_EMOTION_BONUS: Dict[str, float] = {
    "high": 10.0,   # emotion_intensity > 0.7
    "mid": 5.0,     # emotion_intensity > 0.5
    "low": 1.0,     # それ以外
}
DECAY_WORKER_INTERVAL_HOURS = 6  # decay パスの実行間隔

_decay_thread: Optional[threading.Thread] = None
_decay_stop_event = threading.Event()


# ── Ebbinghaus コア関数 ───────────────────────────────────────────────────────

def ebbinghaus_retention(days_since_access: float, stability: float) -> float:
    """R(t) = e^(-t / S) を計算する。

    Args:
        days_since_access: 最終アクセスからの経過日数
        stability: 現在の stability 値 (高いほど減衰が遅い)

    Returns:
        retention スコア 0.0–1.0
    """
    if days_since_access <= 0:
        return 1.0
    s = max(stability, 0.01)
    return math.exp(-days_since_access / s)


def initial_stability(emotion_intensity: float = 0.0) -> float:
    """作成時の感情強度をもとに初期 stability を決定する。

    感情的な記憶は初期から忘れにくい。

    Args:
        emotion_intensity: 感情強度 (0.0–1.0)

    Returns:
        初期 stability 値
    """
    if emotion_intensity > 0.7:
        return STABILITY_EMOTION_BONUS["high"]
    elif emotion_intensity > 0.5:
        return STABILITY_EMOTION_BONUS["mid"]
    return STABILITY_EMOTION_BONUS["low"]


def compute_strength(importance: float, retention: float) -> float:
    """strength = importance * retention (0.0–1.0 にクランプ)。"""
    return max(0.0, min(1.0, importance * retention))


# ── DB ヘルパー ───────────────────────────────────────────────────────────────

def _now_iso(tz: str = "Asia/Tokyo") -> str:
    return datetime.now(ZoneInfo(tz)).isoformat()


def _days_since(ts: Optional[str], tz: str = "Asia/Tokyo") -> float:
    """ISO タイムスタンプから現在までの経過日数を返す (0.0 以上)。"""
    if not ts:
        return 0.0
    try:
        dt = datetime.fromisoformat(ts)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=ZoneInfo(tz))
        delta = datetime.now(ZoneInfo(tz)) - dt
        return max(0.0, delta.total_seconds() / 86400.0)
    except Exception:
        return 0.0


# ── 想起ブースト ──────────────────────────────────────────────────────────────

def boost_on_recall(key: str, db_path: str) -> None:
    """記憶アクセス時に stability を増加させ、strength をリセットする。

    decay クロックを再スタートさせる効果がある。

    Args:
        key: 対象記憶キー
        db_path: SQLite DB ファイルパス
    """
    now = _now_iso()
    try:
        with sqlite3.connect(db_path) as conn:
            row = conn.execute(
                "SELECT stability FROM memory_strength WHERE key = ?", (key,)
            ).fetchone()
            if row is None:
                return

            new_stability = min(row[0] * STABILITY_GROWTH_FACTOR, STABILITY_MAX)

            imp_row = conn.execute(
                "SELECT importance FROM memories WHERE key = ?", (key,)
            ).fetchone()
            # 想起直後は strength を importance (最大値) にリセット
            new_strength = imp_row[0] if imp_row else 0.5

            conn.execute("""
                UPDATE memory_strength
                SET stability = ?, strength = ?, last_decay_at = ?
                WHERE key = ?
            """, (new_stability, new_strength, now, key))
            conn.commit()
    except Exception as e:
        print(f"boost_on_recall failed ({key}): {e}")


# ── decay パス ────────────────────────────────────────────────────────────────

def run_decay_pass(db_path: str, persona: str) -> int:
    """指定 DB の全記憶に Ebbinghaus 減衰を適用する。

    `importance` は変更せず、`memory_strength.strength` のみ更新する。

    Args:
        db_path: SQLite DB ファイルパス
        persona: ペルソナ名 (ログ用)

    Returns:
        更新した記憶の件数
    """
    cfg = load_config()
    tz = cfg.get("timezone", "Asia/Tokyo")
    now = _now_iso(tz)
    updated = 0

    try:
        with sqlite3.connect(db_path) as conn:
            rows = conn.execute("""
                SELECT m.key, m.importance, m.emotion_intensity, m.last_accessed, m.created_at,
                       ms.stability
                FROM memories m
                LEFT JOIN memory_strength ms ON m.key = ms.key
            """).fetchall()

            for key, importance, emotion_intensity, last_accessed, created_at, stability in rows:
                ref_ts = last_accessed or created_at
                days = _days_since(ref_ts, tz)
                s = stability if stability is not None else initial_stability(emotion_intensity or 0.0)
                retention = ebbinghaus_retention(days, s)
                new_strength = compute_strength(importance or 0.5, retention)

                conn.execute("""
                    INSERT INTO memory_strength (key, strength, stability, last_decay_at)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(key) DO UPDATE SET
                        strength = excluded.strength,
                        last_decay_at = excluded.last_decay_at
                """, (key, new_strength, s, now))
                updated += 1

            conn.commit()

        print(f"Ebbinghaus decay: updated {updated} memories (persona={persona})")
    except Exception as e:
        print(f"decay pass failed (persona={persona}): {e}")

    return updated


# ── バックグラウンドワーカー ──────────────────────────────────────────────────

def _get_all_persona_dbs() -> List[Tuple[str, str]]:
    """全ペルソナの (persona_name, db_path) リストを返す。"""
    data_dir = get_data_dir()
    result = []
    if not os.path.isdir(data_dir):
        return result
    for name in os.listdir(data_dir):
        db_path = os.path.join(data_dir, name, "memory.db")
        if os.path.isfile(db_path):
            result.append((name, db_path))
    return result


def _decay_worker_loop() -> None:
    interval_secs = DECAY_WORKER_INTERVAL_HOURS * 3600
    print(f"Ebbinghaus decay worker started (interval={DECAY_WORKER_INTERVAL_HOURS}h)")

    while not _decay_stop_event.is_set():
        try:
            for persona, db_path in _get_all_persona_dbs():
                run_decay_pass(db_path, persona)
        except Exception as e:
            print(f"Ebbinghaus worker error: {e}")

        _decay_stop_event.wait(interval_secs)

    print("Ebbinghaus decay worker stopped")


def start_forgetting_worker(db_path: str) -> threading.Thread:
    """忘却曲線のバックグラウンドスレッドを起動する (冪等)。

    Args:
        db_path: 起動トリガーとなる DB パス (実際は全ペルソナを巡回する)

    Returns:
        起動したスレッド (または既存のスレッド)
    """
    global _decay_thread

    if _decay_thread is not None and _decay_thread.is_alive():
        return _decay_thread

    _decay_stop_event.clear()
    _decay_thread = threading.Thread(
        target=_decay_worker_loop,
        name="nous-ebbinghaus-decay",
        daemon=True,
    )
    _decay_thread.start()
    print("Ebbinghaus decay worker thread started")
    return _decay_thread


def stop_forgetting_worker() -> None:
    """バックグラウンドスレッドに停止シグナルを送る。"""
    _decay_stop_event.set()
