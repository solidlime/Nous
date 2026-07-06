from __future__ import annotations

from typing import TYPE_CHECKING

from .irodori import IrodoriEngine

if TYPE_CHECKING:
    from nous.config.settings import IrodoriConfig

    from .base import VoiceEngine


def get_voice_engine(config: IrodoriConfig) -> VoiceEngine | None:
    """設定に基づいて VoiceEngine を生成する。

    有効なエンジンがない場合は None を返す。
    """
    if config.enabled:
        return IrodoriEngine(config)
    return None
