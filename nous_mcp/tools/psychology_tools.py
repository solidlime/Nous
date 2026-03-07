"""
Nous MCP 心理状態ツール。
感情状態・ドライブ値・目標の読み書きを提供する。
"""

import json
import logging
from typing import Dict, List, Optional

from nous_mcp.server import get_persona, get_psychology_db_path

logger = logging.getLogger(__name__)


def register_psychology_tools(mcp) -> None:
    """FastMCP に心理状態ツールを登録する。"""

    @mcp.tool()
    async def get_psychology_state() -> str:
        """
        現在の心理状態（感情・PAD座標・ドライブ・目標）を JSON で返す。
        """
        persona = get_persona()
        db_path = get_psychology_db_path(persona)
        try:
            from psychology.engine import PsychologyEngine

            engine = PsychologyEngine(persona, db_path)
            state = engine.get_state()
            state["persona"] = persona

            # 後方互換: emotion_detail に PAD 各次元を展開
            pad = state.get("pad", {})
            state["emotion_detail"] = {
                "label":     state.get("emotion", "neutral"),
                "pleasure":  pad.get("pleasure", 0.0),
                "arousal":   pad.get("arousal", 0.0),
                "dominance": pad.get("dominance", 0.0),
                # surface / intensity は PADState の後方互換プロパティから取得
                "surface":   state.get("emotion", "neutral"),
                "intensity": max(
                    abs(pad.get("pleasure", 0.0)),
                    abs(pad.get("arousal", 0.0)),
                    abs(pad.get("dominance", 0.0)),
                ),
            }

            return json.dumps(state, ensure_ascii=False)
        except Exception as e:
            logger.error(f"get_psychology_state error: {e}", exc_info=True)
            return json.dumps({"error": str(e)}, ensure_ascii=False)

    @mcp.tool()
    async def update_psychology(
        event_type: Optional[str] = None,
        emotion: Optional[str] = None,
        emotion_intensity: Optional[float] = None,
        drive_boosts: Optional[Dict[str, float]] = None,
        add_goal: Optional[Dict] = None,
    ) -> str:
        """
        心理状態を更新する。

        Args:
            event_type: OCC評価パイプラインを通すイベント種別 (discovery/positive_interaction 等)
            emotion: PAD座標に変換して直接設定する感情ラベル (joy/curiosity/neutral 等)
            emotion_intensity: 感情強度スケール係数 (0.0-1.0)
            drive_boosts: ドライブ増加量の辞書 {"curiosity": 0.2, ...}
            add_goal: 追加するゴール {"title": "...", "description": "...", "type": "short_term", "priority": 0.7}
        """
        persona = get_persona()
        db_path = get_psychology_db_path(persona)
        results = {}

        try:
            # event_type が指定された場合は PsychologyEngine.process_event() を通す
            if event_type is not None:
                from psychology.engine import PsychologyEngine
                engine = PsychologyEngine(persona, db_path)
                result = engine.process_event(event_type)
                results["event_processed"] = result

            # 感情ラベルを PAD 座標に変換して直接設定する（後方互換）
            if emotion is not None:
                from psychology.emotional_model import EmotionalModel, PADState
                # 代表的な感情ラベルから PAD 座標へのマッピング
                _LABEL_TO_PAD: Dict[str, tuple] = {
                    "joy":       (0.7,  0.5,  0.3),
                    "happy":     (0.8,  0.6,  0.3),
                    "curious":   (0.3,  0.6, -0.1),
                    "excited":   (0.7,  0.8,  0.2),
                    "sad":       (-0.5, -0.3, -0.2),
                    "angry":     (-0.4,  0.7,  0.4),
                    "neutral":   (0.0,  0.0,  0.0),
                    "calm":      (0.2, -0.3,  0.1),
                    "bored":     (-0.3, -0.5, -0.3),
                    "anxious":   (-0.3,  0.4, -0.4),
                    "confident": (0.6,  0.2,  0.5),
                    "content":   (0.4,  0.0,  0.3),
                }
                p, a, d = _LABEL_TO_PAD.get(emotion.lower(), (0.0, 0.0, 0.0))
                intensity = emotion_intensity if emotion_intensity is not None else 0.8
                em = EmotionalModel(persona, db_path)
                em.state = PADState(
                    pleasure=p * intensity,
                    arousal=a * intensity,
                    dominance=d * intensity,
                )
                em.save()
                results["emotion_updated"] = True

            if drive_boosts:
                from psychology.drive_system import DriveSystem
                ds = DriveSystem(persona, db_path)
                for drive, amount in drive_boosts.items():
                    ds.boost(drive, amount)
                results["drives_updated"] = list(drive_boosts.keys())

            if add_goal:
                from psychology.goal_manager import GoalManager
                gm = GoalManager(persona, db_path)
                goal = gm.add_goal(
                    title=add_goal.get("title", "Unnamed Goal"),
                    description=add_goal.get("description", ""),
                    goal_type=add_goal.get("type", "short_term"),
                    priority=add_goal.get("priority", 0.5),
                )
                results["goal_added"] = {"id": goal.id, "title": goal.title}

            return json.dumps({"success": True, "results": results}, ensure_ascii=False)

        except Exception as e:
            logger.error(f"update_psychology error: {e}", exc_info=True)
            return json.dumps({"error": str(e)}, ensure_ascii=False)
