from __future__ import annotations

from typing import TYPE_CHECKING

from .irodori import IrodoriEngine

if TYPE_CHECKING:
    from nous.config.settings import IrodoriConfig

    from .base import VoiceEngine


def get_voice_engine(config: IrodoriConfig) -> VoiceEngine:
    """設定に基づいて VoiceEngine を生成する。

    呼び出し元が ChatConfig.irodori_enabled を事前チェックすること。
    """
    return IrodoriEngine(config)
