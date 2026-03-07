"""
PAD (Pleasure-Arousal-Dominance) 3次元感情モデル。

旧 EmotionalState (3層モデル) を PADState に置き換える。
ContextBuilder が参照する surface_emotion / surface_intensity / mood は
PADState の後方互換プロパティとして維持する。
"""
from __future__ import annotations

import json
import logging
import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from psychology.appraisal import AppraisalResult

logger = logging.getLogger(__name__)


@dataclass
class EmotionConfig:
    """PAD感情モデルの設定パラメータ。"""
    emotional_inertia: float = 0.7    # 慣性（高いほど変化しにくい）
    pleasure_baseline: float = 0.0    # Pleasure 次元の中立値
    arousal_baseline: float = 0.0     # Arousal 次元の中立値
    dominance_baseline: float = 0.0   # Dominance 次元の中立値


class PADState:
    """PAD 3次元感情状態。

    Pleasure-Arousal-Dominance 各次元は -1.0〜1.0 の範囲をとる。
    ContextBuilder との後方互換のため、surface_emotion / surface_intensity / mood
    プロパティを提供する。
    """

    def __init__(
        self,
        pleasure: float = 0.0,
        arousal: float = 0.0,
        dominance: float = 0.0,
    ) -> None:
        self.pleasure = pleasure    # -1.0 (不快) 〜 1.0 (快)
        self.arousal = arousal      # -1.0 (眠い) 〜 1.0 (興奮)
        self.dominance = dominance  # -1.0 (従属) 〜 1.0 (支配)

    # ── ContextBuilder 後方互換プロパティ ────────────────────────────────────

    @property
    def surface_emotion(self) -> str:
        """ContextBuilder が参照する表面感情ラベル。to_emotion_label() と同値。"""
        return self.to_emotion_label()

    @property
    def surface_intensity(self) -> float:
        """ContextBuilder が参照する感情強度。PAD ベクトルのノルム（0〜1）で近似。"""
        # L∞ノルムで最大次元の絶対値を強度とする
        return max(abs(self.pleasure), abs(self.arousal), abs(self.dominance))

    @property
    def mood(self) -> str:
        """ContextBuilder が参照する気分ラベル。surface_emotion と同値。"""
        return self.to_emotion_label()

    @property
    def mood_valence(self) -> float:
        """後方互換プロパティ: pleasure 次元 (-1.0〜1.0) を返す。"""
        return self.pleasure

    @property
    def mood_arousal(self) -> float:
        """後方互換プロパティ: arousal を 0.0〜1.0 スケールに変換して返す。"""
        return (self.arousal + 1.0) / 2.0

    # ── 座標演算 ─────────────────────────────────────────────────────────────

    def to_emotion_label(self) -> str:
        """PAD座標から感情ラベル（16種類）を返す。

        判定は閾値の大きい順から評価する優先度順ルール。
        """
        p, a, d = self.pleasure, self.arousal, self.dominance

        if p > 0.5 and a > 0.3 and d > 0.0:
            return "excited"
        if p > 0.5 and d > 0.3 and a <= 0.3:
            return "confident"
        if p > 0.3 and a <= 0.2 and d > 0.2:
            return "content"
        if p > 0.3 and a <= 0.0 and d <= 0.0:
            return "serene"
        if p > 0.5 and a > 0.5:
            return "happy"
        if p < -0.3 and a > 0.5 and d > 0.0:
            return "angry"
        if p < -0.3 and a > 0.3 and d < 0.0:
            return "frustrated"
        if p < -0.3 and a < -0.3 and d < 0.0:
            return "bored"
        if p < -0.3 and a < -0.2 and d > 0.0:
            return "sad"
        if p < -0.2 and a > 0.2 and d < -0.2:
            return "anxious"
        if p > 0.2 and a > 0.4 and d < 0.0:
            return "curious"
        if p < -0.1 and a > 0.5 and d > 0.4:
            return "determined"
        if p > 0.6 and a < -0.2:
            return "relaxed"
        if p < -0.5 and a < -0.4:
            return "depressed"
        if p > 0.1 and a > 0.2:
            return "interested"
        return "neutral"

    def lerp(self, target: PADState, alpha: float) -> PADState:
        """線形補間 (self → target を alpha の割合で移動)。"""
        return PADState(
            pleasure=self.pleasure + (target.pleasure - self.pleasure) * alpha,
            arousal=self.arousal + (target.arousal - self.arousal) * alpha,
            dominance=self.dominance + (target.dominance - self.dominance) * alpha,
        )

    def clamp(self) -> PADState:
        """各次元を [-1.0, 1.0] にクランプして返す。"""
        return PADState(
            pleasure=max(-1.0, min(1.0, self.pleasure)),
            arousal=max(-1.0, min(1.0, self.arousal)),
            dominance=max(-1.0, min(1.0, self.dominance)),
        )

    def to_dict(self) -> dict:
        """JSON シリアライズ用 dict を返す。"""
        return {
            "pleasure": self.pleasure,
            "arousal": self.arousal,
            "dominance": self.dominance,
        }


class EmotionalModel:
    """PAD感情モデルのメインクラス。SQLite に状態を永続化する（sync）。

    Args:
        persona: ペルソナ名（DB の主キーとして使用）。
        db_path: psychology.db のパス。
        config: EmotionConfig インスタンス（None の場合はデフォルト値）。
    """

    def __init__(
        self,
        persona: str,
        db_path: str,
        config: Optional[EmotionConfig] = None,
    ) -> None:
        self.persona = persona
        self.db_path = db_path
        self._config = config or EmotionConfig()
        self.inertia = self._config.emotional_inertia

        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self._init_db()

        # PAD 中立点（ベースライン）から開始
        self.state: PADState = PADState(
            pleasure=self._config.pleasure_baseline,
            arousal=self._config.arousal_baseline,
            dominance=self._config.dominance_baseline,
        )
        self.load()

    def _init_db(self) -> None:
        """emotional_state / emotion_events テーブルを作成する。旧スキーマは自動マイグレート。"""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            # 旧スキーマ検出: state_json カラムがあれば DROP して新スキーマで再作成
            cols = {row[1] for row in conn.execute("PRAGMA table_info(emotional_state)").fetchall()}
            if cols and "pad_json" not in cols:
                conn.execute("DROP TABLE emotional_state")
                conn.commit()
            # pad_json カラムで PAD 座標を保存する新スキーマ
            conn.execute("""
                CREATE TABLE IF NOT EXISTS emotional_state (
                    persona TEXT PRIMARY KEY,
                    pad_json TEXT NOT NULL,
                    surface_emotion TEXT DEFAULT 'neutral',
                    updated_at TEXT NOT NULL
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS emotion_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    persona TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    surface_emotion TEXT,
                    pad_pleasure REAL,
                    pad_arousal REAL,
                    timestamp TEXT NOT NULL
                )
            """)
            conn.commit()

    def update(self, appraisal: AppraisalResult) -> PADState:
        """AppraisalResult を受け取り PAD 座標を更新して返す（sync）。

        計算式:
          Δpleasure  = goal_relevance × goal_congruence × 0.4
          Δarousal   = goal_relevance × |goal_congruence| × 0.3 + novelty × 0.3
          Δdominance = coping_potential × 0.3 − (1 − coping_potential) × 0.2

        慣性モデル: target = current + delta → state = lerp(state, target, 1−inertia)

        Args:
            appraisal: AppraisalEngine.appraise() の返り値。

        Returns:
            更新後の PADState。
        """
        gr = appraisal.goal_relevance
        gc = appraisal.goal_congruence
        cp = appraisal.coping_potential
        nv = appraisal.novelty

        d_pleasure = gr * gc * 0.4
        d_arousal = gr * abs(gc) * 0.3 + nv * 0.3
        d_dominance = cp * 0.3 - (1.0 - cp) * 0.2

        target = PADState(
            pleasure=self.state.pleasure + d_pleasure,
            arousal=self.state.arousal + d_arousal,
            dominance=self.state.dominance + d_dominance,
        ).clamp()

        alpha = 1.0 - self.inertia
        self.state = self.state.lerp(target, alpha).clamp()
        self.save()
        return self.state

    def decay(self, decay_rate: float = 0.05) -> PADState:
        """時間経過による感情の自然減衰（neutral 原点へ引き寄せる）。

        AgentLoop のティックから定期的に呼ぶ。

        Args:
            decay_rate: 1ティックあたりの減衰係数（0.0〜1.0）。

        Returns:
            減衰後の PADState。
        """
        # decay_rate × 0.3 の割合で neutral (0,0,0) へ線形補間
        alpha = decay_rate * 0.3
        neutral = PADState(0.0, 0.0, 0.0)
        self.state = self.state.lerp(neutral, alpha).clamp()
        self.save()
        return self.state

    def get_display_emotion(self) -> str:
        """アバター表示・LLMプロンプト用の代表感情ラベルを返す（後方互換）。"""
        return self.state.to_emotion_label()

    def save(self) -> None:
        """現在の PAD 状態を DB に書き込む。"""
        now = datetime.now().isoformat()
        label = self.state.to_emotion_label()
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO emotional_state
                    (persona, pad_json, surface_emotion, updated_at)
                VALUES (?, ?, ?, ?)
                """,
                (self.persona, json.dumps(self.state.to_dict()), label, now),
            )
            conn.commit()

    def load(self) -> None:
        """DB から PAD 状態を読み込む。

        旧スキーマ (state_json + mood_valence/mood_arousal) も変換して読み込む。
        """
        with sqlite3.connect(self.db_path) as conn:
            try:
                # 新スキーマ: pad_json カラムを読む
                row = conn.execute(
                    "SELECT pad_json FROM emotional_state WHERE persona = ?",
                    (self.persona,),
                ).fetchone()
                if row:
                    data = json.loads(row[0])
                    if "pleasure" in data:
                        # 新形式: pleasure/arousal/dominance
                        self.state = PADState(
                            pleasure=data["pleasure"],
                            arousal=data["arousal"],
                            dominance=data["dominance"],
                        )
                    elif "mood_valence" in data:
                        # 旧形式: mood_valence (−1〜1) / mood_arousal (0〜1) → PAD 変換
                        self.state = PADState(
                            pleasure=data.get("mood_valence", 0.0),
                            # 旧 arousal は 0〜1 スケール → −1〜1 に変換
                            arousal=data.get("mood_arousal", 0.5) * 2.0 - 1.0,
                            dominance=0.0,
                        )
            except Exception as e:
                # 読み込みに失敗した場合はベースライン状態を維持する
                logger.debug(f"emotional_state load skipped: {e}")
