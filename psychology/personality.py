import json
import os
from dataclasses import dataclass, asdict
from datetime import datetime


@dataclass
class PersonalityTraits:
    # Big5 インスパイア（ヘルタ固有値）
    openness:          float = 0.95  # 開放性
    conscientiousness: float = 0.7   # 誠実性
    extraversion:      float = 0.6   # 外向性
    agreeableness:     float = 0.3   # 協調性（低め = 傲慢さの根拠）
    neuroticism:       float = 0.2   # 神経症的傾向（低め = 感情安定）
    # ヘルタ固有特性
    intellectual_arrogance: float = 0.9   # 知的傲慢さ
    wonder_sensitivity:     float = 0.95  # 驚異への感受性


class PersonalityManager:
    # 1回の nudge で変化できる最大値（パーソナリティは非常に緩やかに変化する）
    MAX_DELTA: float = 0.001

    def __init__(self, persona: str, config_path: str):
        self.persona = persona
        self.config_path = config_path
        os.makedirs(os.path.dirname(config_path), exist_ok=True)

    def load(self) -> PersonalityTraits:
        if not os.path.exists(self.config_path):
            return PersonalityTraits()
        with open(self.config_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        valid_fields = PersonalityTraits.__dataclass_fields__
        return PersonalityTraits(**{k: v for k, v in data.items() if k in valid_fields})

    def save(self, traits: PersonalityTraits) -> None:
        with open(self.config_path, "w", encoding="utf-8") as f:
            json.dump(asdict(traits), f, ensure_ascii=False, indent=2)

    def nudge(self, trait: str, delta: float) -> None:
        """非常に緩やかなパーソナリティ変化（1セッションで目立つ変化は起きない）"""
        traits = self.load()
        if not hasattr(traits, trait):
            return
        clamped_delta = max(-self.MAX_DELTA, min(self.MAX_DELTA, delta))
        current = getattr(traits, trait)
        setattr(traits, trait, max(0.0, min(1.0, current + clamped_delta)))
        self.save(traits)
