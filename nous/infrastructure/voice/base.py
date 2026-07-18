from __future__ import annotations

from abc import ABC, abstractmethod


class VoiceEngine(ABC):
    """音声合成エンジンの抽象基底クラス"""

    @abstractmethod
    async def synthesize(
        self,
        text: str,
        emotion: str,
        speech_style: str | None = None,
        caption: str | None = None,
    ) -> bytes:
        """音声合成してWAVバイト列を返す"""
        ...

    @abstractmethod
    async def health_check(self) -> bool:
        """エンジンが利用可能か確認する"""
        ...
