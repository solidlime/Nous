"""TTS キャッシュキーの単体テスト — voice_override 差分でキャッシュヒントが変わること。"""

import pytest

from nous.api.http.routers.tts import _tts_cache_key

pytestmark = pytest.mark.unit


def _key(voice: str | None) -> str:
    return _tts_cache_key(
        text="こんにちは",
        emotion="neutral",
        caption=None,
        voice_speed=1.0,
        voice_override=voice,
    )


def test_voice_override_changes_cache_key():
    """声が違えばキャッシュキーも違う（旧声の音声を返さない）"""
    assert _key("voice_a") != _key("voice_b")


def test_none_and_missing_voice_share_key():
    """voice_override None と空文字は同一キー（後方互換）"""
    assert _key(None) == _key("")


def test_same_voice_same_key():
    assert _key("voice_a") == _key("voice_a")
