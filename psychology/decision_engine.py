from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from psychology.drive_system import DriveState
from psychology.emotional_model import PADState
from psychology.goal_manager import Goal


@dataclass
class DecisionResult:
    action_type: str  # "react_to_event" | "pursue_goal" | "satisfy_drive" | "idle"
    priority: float
    context: Dict[str, Any] = field(default_factory=dict)
    reason: str = ""


class DecisionEngine:
    """ドライブ状態 + 目標 + 感情 → 「今何をすべきか/したいか」を決定。

    意思決定の優先順位:
    1. pending_events > 0 → react_to_event
    2. 閾値超えのドライブがある → satisfy_drive
    3. 活性化ゴールがある → pursue_goal
    4. 全てなし → idle
    """

    def decide(
        self,
        drive_state: DriveState,
        emotional_state: PADState,
        active_goals: List[Goal],
        pending_events: int,
        triggered_drives: Optional[List[str]] = None,
    ) -> DecisionResult:
        # 優先1: 外部イベントへの反応が最優先
        if pending_events > 0:
            return DecisionResult(
                action_type="react_to_event",
                priority=0.9,
                context={"pending_count": pending_events},
                reason="外部イベントへの反応が最優先だよ",
            )

        # 優先2: 閾値を超えたドライブを満たす
        if triggered_drives:
            highest_drive = triggered_drives[0]
            drive_val = getattr(drive_state, highest_drive, 0.0)
            return DecisionResult(
                action_type="satisfy_drive",
                priority=0.7 + drive_val * 0.2,
                context={"drive": highest_drive, "value": drive_val},
                reason=f"{highest_drive}が高まってるから、満たしてあげないとね",
            )

        # 優先3: アクティブゴールを追求
        if active_goals:
            top_goal = max(active_goals, key=lambda g: g.priority)
            return DecisionResult(
                action_type="pursue_goal",
                priority=0.5 + top_goal.priority * 0.3,
                context={"goal_id": top_goal.id, "goal_title": top_goal.title},
                reason=f"目標「{top_goal.title}」に取り組む時間だよ",
            )

        # 全て満たされている場合は待機
        return DecisionResult(
            action_type="idle",
            priority=0.0,
            reason="今は特にやりたいことはないね",
        )

    def should_consciousness_tick(
        self,
        emotional_state: PADState,
        drive_state: DriveState,
    ) -> bool:
        """意識ティックを発火すべきか判定。

        PADState の pleasure 次元を旧 mood_valence の代替として使う。
        """
        # pleasure が強い（正負どちらでも）場合はティック
        if abs(emotional_state.pleasure) > 0.5:
            return True
        # 主要ドライブの平均が高いならティック
        drives = [drive_state.curiosity, drive_state.boredom, drive_state.expression]
        if sum(drives) / len(drives) > 0.6:
            return True
        return False
