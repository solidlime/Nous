"""
ペルソナコンテキスト管理 (Nous 版)。

MemoryMCP の persona_context.py を PersonaContext クラスとして再設計。
JSON ファイルへの読み書きを担当し、アトミック書き込みでデータ破損を防ぐ。
"""

import json
import os
import shutil
import threading
from typing import Any, Dict, Optional


# デフォルトのコンテキスト構造
_DEFAULT_CONTEXT: Dict[str, Any] = {
    "user_info": {
        "name": "User",
        "nickname": None,
        "preferred_address": None,
    },
    "persona_info": {
        "name": None,  # ロード時にペルソナ名で埋める
        "nickname": None,
        "preferred_address": None,
    },
    "last_conversation_time": None,
    "current_emotion": "neutral",
    "current_emotion_intensity": None,
    "physical_state": "normal",
    "mental_state": "calm",
    "environment": "unknown",
    "relationship_status": "normal",
    "current_action_tag": None,
    "physical_sensations": {
        "fatigue": 0.0,
        "warmth": 0.5,
        "arousal": 0.0,
        "touch_response": "normal",
        "heart_rate_metaphor": "calm",
    },
}


class PersonaContext:
    """ペルソナコンテキストの読み書きを管理するクラス。

    Args:
        config_path: コンテキスト JSON ファイルのフルパス
                     (例: data/herta/persona_context.json)
    """

    def __init__(self, config_path: str) -> None:
        self.config_path = config_path
        self._lock = threading.Lock()

    def load(self, persona: str) -> Dict[str, Any]:
        """コンテキストを JSON ファイルから読み込む。

        ファイルが存在しない場合はデフォルトを作成して返す。

        Args:
            persona: ペルソナ名 (デフォルトの persona_info.name に使用)

        Returns:
            コンテキスト dict
        """
        try:
            if os.path.exists(self.config_path):
                with open(self.config_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            else:
                # ファイルが存在しない場合はデフォルトを作成
                default = _make_default(persona)
                self.save(default)
                return default
        except Exception as e:
            print(f"PersonaContext.load failed ({self.config_path}): {e}")
            return _make_default(persona)

    def save(self, context: Dict[str, Any]) -> bool:
        """コンテキストを JSON ファイルにアトミックに保存する。

        一時ファイルへ書き込み → バックアップ作成 → os.replace で原子的に置換する。
        中途半端な状態でのファイル破損を防ぐ。

        Args:
            context: 保存するコンテキスト dict

        Returns:
            保存に成功した場合 True
        """
        os.makedirs(os.path.dirname(self.config_path), exist_ok=True)
        tmp_path = f"{self.config_path}.tmp"

        with self._lock:
            try:
                with open(tmp_path, "w", encoding="utf-8") as f:
                    json.dump(context, f, indent=2, ensure_ascii=False)

                # 最後の正常ファイルをバックアップとして保持
                if os.path.exists(self.config_path):
                    shutil.copy2(self.config_path, f"{self.config_path}.backup")

                os.replace(tmp_path, self.config_path)
                return True
            except Exception as e:
                print(f"PersonaContext.save failed ({self.config_path}): {e}")
                return False

    def update_last_conversation_time(self, persona: str) -> None:
        """last_conversation_time を現在時刻に更新する。

        全ツール操作の冒頭で呼ぶことを想定。

        Args:
            persona: ペルソナ名
        """
        from datetime import datetime
        from zoneinfo import ZoneInfo
        from config import load_config

        cfg = load_config()
        tz = cfg.get("timezone", "Asia/Tokyo")
        now = datetime.now(ZoneInfo(tz)).isoformat()

        context = self.load(persona)
        context["last_conversation_time"] = now
        self.save(context)


def _make_default(persona: str) -> Dict[str, Any]:
    """デフォルトコンテキストのコピーを作成し、persona 名を埋める。"""
    import copy
    ctx = copy.deepcopy(_DEFAULT_CONTEXT)
    ctx["persona_info"]["name"] = persona
    return ctx
