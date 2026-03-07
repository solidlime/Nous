import json
import sqlite3
import os
from dataclasses import dataclass, field, asdict
from typing import List, Dict
from datetime import datetime


@dataclass
class DriveState:
    curiosity:  float = 0.5  # 好奇心: 新しい情報・謎への渇望
    boredom:    float = 0.2  # 退屈: 刺激のなさへの不満
    connection: float = 0.4  # 連帯感: 人や存在とのつながりへの欲求
    expression: float = 0.3  # 表現欲: 考えや発見を伝えたい欲求
    mastery:    float = 0.6  # 習熟欲: 何かをより深く理解したい欲求
    updated_at: str = field(default_factory=lambda: datetime.now().isoformat())


class DriveSystem:
    THRESHOLDS: Dict[str, float] = {
        "curiosity":   0.8,
        "boredom":     0.7,
        "connection":  0.75,
        "expression":  0.8,
        "mastery":     0.85,
    }
    TICK_RATE_PER_HOUR: float = 0.05  # 1時間あたりの自然増加量（homeostasis）
    DRIVES: List[str] = ["curiosity", "boredom", "connection", "expression", "mastery"]

    def __init__(self, persona: str, db_path: str):
        self.persona = persona
        self.db_path = db_path
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self._init_db()
        self._state = self.load()

    def _init_db(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("""
                CREATE TABLE IF NOT EXISTS drive_state (
                    persona TEXT PRIMARY KEY,
                    state_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS drive_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    persona TEXT NOT NULL,
                    drive TEXT NOT NULL,
                    value REAL NOT NULL,
                    delta REAL NOT NULL,
                    reason TEXT,
                    timestamp TEXT NOT NULL
                )
            """)
            conn.commit()

    @property
    def state(self) -> DriveState:
        return self._state

    def tick(self, elapsed_hours: float) -> DriveState:
        """時間経過によるドライブ自然増加 (homeostasis)"""
        increment = self.TICK_RATE_PER_HOUR * elapsed_hours
        for drive in self.DRIVES:
            current = getattr(self._state, drive)
            setattr(self._state, drive, min(1.0, current + increment))
        self._state.updated_at = datetime.now().isoformat()
        self.save()
        return self._state

    def consume(self, drive: str, amount: float) -> None:
        """行動によるドライブ消費"""
        if drive not in self.DRIVES:
            return
        current = getattr(self._state, drive)
        setattr(self._state, drive, max(0.0, current - amount))
        self._state.updated_at = datetime.now().isoformat()
        self.save()

    def boost(self, drive: str, amount: float) -> None:
        """外部イベントによるドライブ増加"""
        if drive not in self.DRIVES:
            return
        current = getattr(self._state, drive)
        setattr(self._state, drive, min(1.0, current + amount))
        self._state.updated_at = datetime.now().isoformat()
        self.save()

    def update(self, drive: str, delta: float) -> None:
        """特定ドライブの値を delta だけ変化させる（正=増加、負=減少）。0-1 にクランプ。

        PsychologyEngine.process_event() から呼ばれる。
        consume() / boost() を delta の正負で使い分ける代わりに、
        1メソッドで統一的に扱えるようにするためのラッパー。

        Args:
            drive: ドライブ名（self.DRIVES に存在しない場合は無視）。
            delta: 変化量（正で増加、負で減少）。
        """
        if drive not in self.DRIVES:
            return
        current = getattr(self._state, drive)
        setattr(self._state, drive, max(0.0, min(1.0, current + delta)))
        self._state.updated_at = datetime.now().isoformat()
        self.save()

    def get_triggered_drives(self) -> List[str]:
        """閾値を超えたドライブ一覧を返す → AgentLoop のトリガーに"""
        return [
            drive for drive, threshold in self.THRESHOLDS.items()
            if getattr(self._state, drive) >= threshold
        ]

    def to_dict(self) -> dict:
        return {d: getattr(self._state, d) for d in self.DRIVES}

    def save(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT OR REPLACE INTO drive_state (persona, state_json, updated_at)
                VALUES (?, ?, ?)
            """, (self.persona, json.dumps(asdict(self._state)), self._state.updated_at))
            conn.commit()

    def load(self) -> DriveState:
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT state_json FROM drive_state WHERE persona = ?",
                (self.persona,),
            ).fetchone()
        if row:
            data = json.loads(row[0])
            # updated_at フィールドを除いてから DriveState を構築
            state_data = {k: v for k, v in data.items() if k in self.DRIVES}
            state = DriveState(**state_data)
            state.updated_at = data.get("updated_at", datetime.now().isoformat())
            return state
        return DriveState()
