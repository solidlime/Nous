import json
import sqlite3
import os
import uuid
from dataclasses import dataclass, field
from typing import Optional, List
from datetime import datetime


@dataclass
class Goal:
    id: str
    title: str
    description: str
    goal_type: str  # "long_term" | "short_term"
    priority: float = 0.5
    progress: float = 0.0
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    target_date: Optional[str] = None
    status: str = "active"  # active | completed | abandoned
    related_memories: List[str] = field(default_factory=list)


class GoalManager:
    def __init__(self, persona: str, db_path: str):
        self.persona = persona
        self.db_path = db_path
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self._init_db()

    def _init_db(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("""
                CREATE TABLE IF NOT EXISTS goals (
                    id TEXT PRIMARY KEY,
                    persona TEXT NOT NULL,
                    title TEXT NOT NULL,
                    description TEXT NOT NULL,
                    goal_type TEXT NOT NULL,
                    priority REAL DEFAULT 0.5,
                    progress REAL DEFAULT 0.0,
                    created_at TEXT NOT NULL,
                    target_date TEXT,
                    status TEXT DEFAULT 'active',
                    related_memories TEXT DEFAULT '[]'
                )
            """)
            conn.commit()

    def _row_to_goal(self, row: tuple) -> Goal:
        return Goal(
            id=row[0],
            title=row[2],
            description=row[3],
            goal_type=row[4],
            priority=row[5],
            progress=row[6],
            created_at=row[7],
            target_date=row[8],
            status=row[9],
            related_memories=json.loads(row[10]) if row[10] else [],
        )

    def get_active_goals(self) -> List[Goal]:
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                "SELECT * FROM goals WHERE persona=? AND status='active' ORDER BY priority DESC",
                (self.persona,),
            ).fetchall()
        return [self._row_to_goal(r) for r in rows]

    def add_goal(
        self,
        title: str,
        description: str,
        goal_type: str,
        priority: float = 0.5,
    ) -> Goal:
        goal = Goal(
            id=str(uuid.uuid4()),
            title=title,
            description=description,
            goal_type=goal_type,
            priority=priority,
        )
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT INTO goals
                    (id, persona, title, description, goal_type, priority, progress, created_at, status, related_memories)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                goal.id, self.persona, goal.title, goal.description,
                goal.goal_type, goal.priority, goal.progress,
                goal.created_at, goal.status, json.dumps([]),
            ))
            conn.commit()
        return goal

    def update_goal(self, goal_id: str, **kwargs) -> Optional[Goal]:
        allowed = {"title", "description", "priority", "progress", "status", "target_date"}
        sets = {k: v for k, v in kwargs.items() if k in allowed}
        if not sets:
            return None
        set_clause = ", ".join(f"{k}=?" for k in sets)
        values = list(sets.values()) + [goal_id, self.persona]
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                f"UPDATE goals SET {set_clause} WHERE id=? AND persona=?",
                values,
            )
            conn.commit()
        return self.get_goal(goal_id)

    def get_goal(self, goal_id: str) -> Optional[Goal]:
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT * FROM goals WHERE id=? AND persona=?",
                (goal_id, self.persona),
            ).fetchone()
        return self._row_to_goal(row) if row else None

    def advance_progress(self, goal_id: str, delta: float) -> None:
        """目標の進捗を delta 分だけ増加（上限 1.0）"""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "UPDATE goals SET progress=MIN(1.0, progress+?) WHERE id=? AND persona=?",
                (delta, goal_id, self.persona),
            )
            conn.commit()

    def complete_goal(self, goal_id: str) -> None:
        """目標を完了状態にする"""
        self.update_goal(goal_id, status="completed", progress=1.0)
