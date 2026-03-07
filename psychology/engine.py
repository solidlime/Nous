"""
PsychologyEngine — 心理モジュール統合ファサード（sync版）。

AppraisalEngine / EmotionalModel / DriveSystem / GoalManager を束ねて
process_event() 一呼び出しで認知評価 → 感情更新 → ドライブ更新を実行する。
"""
from __future__ import annotations

import json
import logging
import os
import sqlite3
from datetime import datetime
from typing import Optional

from config import load_config
from psychology.appraisal import (
    AppraisalConfig,
    AppraisalEngine,
    AppraisalResult,
    PersonalityConfig,
)
from psychology.drive_system import DriveSystem
from psychology.emotional_model import EmotionConfig, EmotionalModel
from psychology.goal_manager import GoalManager

logger = logging.getLogger(__name__)

# イベント種別 → (ドライブ名, delta) のマッピング。
# delta が正なら増加 (boredom 蓄積等)、負なら消費 (curiosity 充足等)。
_DRIVE_DELTA: dict[str, tuple[str, float]] = {
    "discovery":            ("curiosity",   -0.3),
    "interesting_topic":    ("curiosity",   -0.3),
    "boring_topic":         ("boredom",     +0.2),
    "discord_message":      ("connection",  -0.2),
    "new_user_message":     ("connection",  -0.2),
    "positive_interaction": ("connection",  -0.2),
    "task_completed":       ("mastery",     -0.4),
}


class PsychologyEngine:
    """AppraisalEngine + EmotionalModel + DriveSystem の統合ファサード。

    process_event() を呼ぶことで認知評価 → 感情更新 → ドライブ更新を一括実行する。
    get_state() で現在の全心理状態を dict として取得できる。

    Args:
        persona: ペルソナ名（DB 主キー）。
        db_path: psychology.db のパス。
        config: Nous 設定 dict（None の場合は load_config() を使用）。
    """

    def __init__(
        self,
        persona: str,
        db_path: str,
        config: Optional[dict] = None,
    ) -> None:
        self.persona = persona
        self._db_path = db_path

        cfg = config or load_config()
        psych_cfg = cfg.get("psychology", {})

        # PersonalityConfig: config["psychology"]["personality"] から読む
        p_cfg = psych_cfg.get("personality", {})
        personality = PersonalityConfig(
            openness=p_cfg.get("openness", 0.7),
            conscientiousness=p_cfg.get("conscientiousness", 0.6),
            extraversion=p_cfg.get("extraversion", 0.5),
            agreeableness=p_cfg.get("agreeableness", 0.5),
            neuroticism=p_cfg.get("neuroticism", 0.4),
        )

        # AppraisalConfig: config["psychology"]["appraisal"] から読む
        a_cfg = psych_cfg.get("appraisal", {})
        appraisal_cfg = AppraisalConfig(
            novelty_weight=a_cfg.get("novelty_weight", 1.0),
            social_weight=a_cfg.get("social_weight", 1.0),
            mastery_weight=a_cfg.get("mastery_weight", 1.0),
        )

        # EmotionConfig: config["psychology"]["emotion"] から読む
        # 旧形式の emotional_inertia トップレベルキーも参照する
        e_cfg = psych_cfg.get("emotion", {})
        emotion_cfg = EmotionConfig(
            emotional_inertia=e_cfg.get(
                "emotional_inertia",
                psych_cfg.get("emotional_inertia", 0.7),
            ),
            pleasure_baseline=e_cfg.get("pleasure_baseline", 0.0),
            arousal_baseline=e_cfg.get("arousal_baseline", 0.0),
            dominance_baseline=e_cfg.get("dominance_baseline", 0.0),
        )

        self.appraisal_engine = AppraisalEngine(personality, appraisal_cfg)
        self.emotional = EmotionalModel(persona, db_path, emotion_cfg)
        self.drives = DriveSystem(persona, db_path)
        self.goals = GoalManager(persona, db_path)

        self._init_events_table()

    def _init_events_table(self) -> None:
        """psychology_events テーブルを作成する（初回のみ）。"""
        os.makedirs(os.path.dirname(self._db_path), exist_ok=True)
        with sqlite3.connect(self._db_path) as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("""
                CREATE TABLE IF NOT EXISTS psychology_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    persona TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    appraisal_json TEXT,
                    emotional_delta TEXT,
                    drive_delta TEXT,
                    timestamp TEXT NOT NULL
                )
            """)
            conn.commit()

    def process_event(
        self,
        event_type: str,
        content: str = "",
        meta: dict | None = None,
    ) -> dict:
        """イベントを受理して心理状態を更新し、結果 dict を返す（sync）。

        処理順序:
          1. AppraisalEngine.appraise() で OCC 評価を実施
          2. EmotionalModel.update() で PAD 座標を更新
          3. DriveSystem.update() で対応ドライブを更新
          4. psychology_events テーブルにログを保存

        Args:
            event_type: イベント種別文字列。
            content: イベント本文（評価エンジンに渡すが現状は未使用）。
            meta: 追加メタデータ。

        Returns:
            {emotion, pad, delta, appraisal} を含む dict。
        """
        meta = meta or {}
        appraisal: AppraisalResult = self.appraisal_engine.appraise(
            event_type, content, meta
        )

        prev_pad = self.emotional.state.to_dict()
        new_pad = self.emotional.update(appraisal)
        delta = {
            "pleasure":  round(new_pad.pleasure  - prev_pad["pleasure"],  4),
            "arousal":   round(new_pad.arousal   - prev_pad["arousal"],   4),
            "dominance": round(new_pad.dominance - prev_pad["dominance"], 4),
        }

        # ドライブ更新（_DRIVE_DELTA に定義されているイベントのみ）
        drive_delta: dict[str, float] = {}
        if event_type in _DRIVE_DELTA:
            drive_name, dv = _DRIVE_DELTA[event_type]
            self.drives.update(drive_name, dv)
            drive_delta[drive_name] = dv

        # イベントログを psychology_events に保存
        now = datetime.now().isoformat()
        with sqlite3.connect(self._db_path) as conn:
            conn.execute(
                "INSERT INTO psychology_events"
                " (persona, event_type, appraisal_json, emotional_delta, drive_delta, timestamp)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (
                    self.persona,
                    event_type,
                    json.dumps({
                        "gr": appraisal.goal_relevance,
                        "gc": appraisal.goal_congruence,
                        "ei": appraisal.ego_involvement,
                        "cp": appraisal.coping_potential,
                        "nv": appraisal.novelty,
                    }),
                    json.dumps(delta),
                    json.dumps(drive_delta),
                    now,
                ),
            )
            conn.commit()

        return {
            "emotion":   new_pad.to_emotion_label(),
            "pad":       new_pad.to_dict(),
            "delta":     delta,
            "appraisal": {
                "goal_relevance":  appraisal.goal_relevance,
                "goal_congruence": appraisal.goal_congruence,
            },
        }

    def get_state(self) -> dict:
        """現在の全心理状態を dict で返す。

        Returns:
            {emotion, pad, drives, triggered_drives, active_goals} を含む dict。
        """
        drives_dict = {
            d: getattr(self.drives.state, d)
            for d in self.drives.DRIVES
        }
        active_goals = self.goals.get_active_goals()
        return {
            "emotion":   self.emotional.state.to_emotion_label(),
            "pad":       self.emotional.state.to_dict(),
            "drives":    drives_dict,
            "triggered_drives": self.drives.get_triggered_drives(),
            "active_goals": [
                {
                    "id":       g.id,
                    "title":    g.title,
                    "type":     g.goal_type,
                    "priority": g.priority,
                    "progress": g.progress,
                }
                for g in active_goals
            ],
        }

    def tick(self, elapsed_hours: float) -> list[str]:
        """ドライブティックを実行して、閾値超えドライブ名リストを返す。

        AgentLoop._tick_drives() から呼ばれる。

        Args:
            elapsed_hours: 前回ティックからの経過時間（時間単位）。

        Returns:
            閾値を超えたドライブ名のリスト。
        """
        self.drives.tick(elapsed_hours)
        return self.drives.get_triggered_drives()

    def decay(self, decay_rate: float = 0.03) -> None:
        """感情の自然減衰。AgentLoop から定期的に呼ぶ。

        Args:
            decay_rate: 1ティックあたりの減衰係数（0.0〜1.0）。
        """
        self.emotional.decay(decay_rate)
