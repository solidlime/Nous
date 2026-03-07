"""
OCC 認知評価エンジン（Ortony, Clore & Collins モデル）。

イベント種別に基づく5次元評価（goal_relevance/goal_congruence/ego_involvement/
coping_potential/novelty）を計算し、PAD感情モデルへの入力として使用する。
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class PersonalityConfig:
    """Big5 パーソナリティ特性（0.0〜1.0）。"""
    openness: float = 0.7
    conscientiousness: float = 0.6
    extraversion: float = 0.5
    agreeableness: float = 0.5
    neuroticism: float = 0.4


@dataclass
class AppraisalConfig:
    """評価エンジンの重み係数。"""
    novelty_weight: float = 1.0
    social_weight: float = 1.0
    mastery_weight: float = 1.0


@dataclass
class AppraisalResult:
    """OCC 評価の5次元結果。"""
    goal_relevance: float = 0.0    # 目標との関連度 (0.0〜1.0)
    goal_congruence: float = 0.0   # 目標との一致度 (-1.0〜1.0)
    ego_involvement: float = 0.0   # 自己関与度 (0.0〜1.0)
    coping_potential: float = 0.5  # 対処可能性 (0.0〜1.0)
    novelty: float = 0.0           # 新奇性 (0.0〜1.0)


# イベント種別ごとの評価テンプレート値。
# 各フィールドはパーソナリティ補正前のベースライン。
EVENT_TEMPLATES: dict[str, dict] = {
    "discord_message":      {"goal_relevance": 0.3, "goal_congruence": 0.2,  "ego_involvement": 0.2, "coping_potential": 0.8, "novelty": 0.1},
    "new_user_message":     {"goal_relevance": 0.5, "goal_congruence": 0.3,  "ego_involvement": 0.3, "coping_potential": 0.8, "novelty": 0.3},
    "discovery":            {"goal_relevance": 0.7, "goal_congruence": 0.8,  "ego_involvement": 0.5, "coping_potential": 0.9, "novelty": 0.9},
    "interesting_topic":    {"goal_relevance": 0.8, "goal_congruence": 0.7,  "ego_involvement": 0.6, "coping_potential": 0.9, "novelty": 0.7},
    "boring_topic":         {"goal_relevance": 0.1, "goal_congruence": -0.5, "ego_involvement": 0.1, "coping_potential": 0.9, "novelty": 0.0},
    "positive_interaction": {"goal_relevance": 0.4, "goal_congruence": 0.6,  "ego_involvement": 0.3, "coping_potential": 0.8, "novelty": 0.2},
    "negative_interaction": {"goal_relevance": 0.3, "goal_congruence": -0.4, "ego_involvement": 0.2, "coping_potential": 0.7, "novelty": 0.1},
    "task_completed":       {"goal_relevance": 0.8, "goal_congruence": 0.9,  "ego_involvement": 0.7, "coping_potential": 1.0, "novelty": 0.2},
    "task_failed":          {"goal_relevance": 0.7, "goal_congruence": -0.7, "ego_involvement": 0.8, "coping_potential": 0.4, "novelty": 0.1},
    "memory_elevation":     {"goal_relevance": 0.6, "goal_congruence": 0.5,  "ego_involvement": 0.4, "coping_potential": 0.8, "novelty": 0.4},
    "consciousness_tick":   {"goal_relevance": 0.2, "goal_congruence": 0.1,  "ego_involvement": 0.1, "coping_potential": 0.9, "novelty": 0.1},
}

# テンプレートに存在しないイベント用のフォールバック値
_DEFAULT_TEMPLATE: dict = {
    "goal_relevance": 0.3,
    "goal_congruence": 0.1,
    "ego_involvement": 0.2,
    "coping_potential": 0.7,
    "novelty": 0.2,
}

# 習熟感・社会性でドライブ重みを変えるイベント種別セット
_MASTERY_EVENT_TYPES: tuple[str, ...] = ("task_completed", "task_failed", "discovery")
_SOCIAL_EVENT_TYPES: tuple[str, ...] = (
    "discord_message", "new_user_message",
    "positive_interaction", "negative_interaction",
)


class AppraisalEngine:
    """OCC 認知評価エンジン。

    パーソナリティ特性に基づいてイベントを5次元評価し、AppraisalResult を返す。
    """

    def __init__(
        self,
        personality: PersonalityConfig,
        appraisal_cfg: AppraisalConfig,
    ) -> None:
        self.personality = personality
        self.cfg = appraisal_cfg

    def appraise(
        self,
        event_type: str,
        content: str = "",
        meta: dict | None = None,
    ) -> AppraisalResult:
        """イベントを認知評価して AppraisalResult を返す。

        パーソナリティ補正の順序:
        1. novelty × openness で goal_congruence を加算補正
        2. agreeableness で negative な gc を緩和
        3. conscientiousness で高関連度かつ不一致なイベントの ego_involvement を増加
        4. neuroticism で coping_potential を低下
        5. 重み係数（mastery_weight / social_weight）を goal_relevance に乗算

        Args:
            event_type: イベント種別文字列（EVENT_TEMPLATES のキー）。
            content: イベント本文テキスト（現在は未使用、将来の拡張用）。
            meta: 追加メタデータ（現在は未使用、将来の拡張用）。

        Returns:
            クランプ済みの AppraisalResult。
        """
        meta = meta or {}
        t = EVENT_TEMPLATES.get(event_type, _DEFAULT_TEMPLATE)

        gr: float = t["goal_relevance"]
        gc: float = t["goal_congruence"]
        ei: float = t["ego_involvement"]
        cp: float = t["coping_potential"]
        nv: float = t["novelty"]

        # novelty が高い場合、openness に応じて goal_congruence を上方補正
        nv_boost = nv * self.personality.openness * self.cfg.novelty_weight
        if nv > 0.5:
            gc = gc + (self.personality.openness - 0.5) * 0.4

        # 不快なイベント (gc < 0) は agreeableness が高いほど和らぐ
        if gc < 0:
            gc = gc * (1.0 - (1.0 - self.personality.agreeableness) * 0.5)

        # 不一致かつ高関連度なら、conscientiousness に応じて ego_involvement 増加
        if gc < 0 and t["goal_relevance"] > 0.5:
            ei = min(1.0, ei + self.personality.conscientiousness * 0.3)

        # neuroticism が高いほど対処可能性が低下する
        cp = cp * (1.0 - self.personality.neuroticism * 0.3)

        # ドライブ重み係数を goal_relevance に適用
        if event_type in _MASTERY_EVENT_TYPES:
            gr = min(1.0, gr * self.cfg.mastery_weight)
        elif event_type in _SOCIAL_EVENT_TYPES:
            gr = gr * self.cfg.social_weight

        return AppraisalResult(
            goal_relevance=max(0.0, min(1.0, gr)),
            goal_congruence=max(-1.0, min(1.0, gc)),
            ego_involvement=max(0.0, min(1.0, ei)),
            coping_potential=max(0.0, min(1.0, cp)),
            novelty=max(0.0, min(1.0, nv_boost)),
        )
