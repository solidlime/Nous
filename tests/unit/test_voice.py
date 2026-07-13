"""VoiceEngine インフラ層の単体テスト"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from nous.config.settings import IrodoriConfig

# ============================================================
# EMOTION_EMOJI
# ============================================================


class TestEmotionEmoji:
    """EMOTION_EMOJI 定数のテスト"""

    def test_emoji_keys(self):
        from nous.domain.value_objects import EMOTION_EMOJI

        assert EMOTION_EMOJI["neutral"] == "😐"
        assert EMOTION_EMOJI["joy"] == "😊"
        assert EMOTION_EMOJI["sadness"] == "😢"
        assert EMOTION_EMOJI["anger"] == "😠"
        assert EMOTION_EMOJI["fear"] == "😨"
        assert EMOTION_EMOJI["surprise"] == "😲"

    def test_all_defined_emotions_have_entries(self):
        from nous.domain.value_objects import EMOTION_EMOJI

        expected_keys = {
            "neutral",
            "joy",
            "sadness",
            "anger",
            "fear",
            "surprise",
            "disgust",
            "excitement",
            "love",
            "curiosity",
            "anticipation",
            "grief",
        }
        assert set(EMOTION_EMOJI.keys()) == expected_keys


# ============================================================
# TestIrodoriEngine
# ============================================================


class TestIrodoriEngine:
    """IrodoriEngine の単体テスト（httpx モック）"""

    @pytest.fixture
    def config(self) -> IrodoriConfig:
        return IrodoriConfig(enabled=True, url="http://irodori:8088/v1", voice="kiritan", timeout_seconds=30)

    def _make_irodori(self, config: IrodoriConfig):
        from nous.infrastructure.voice.irodori import IrodoriEngine

        return IrodoriEngine(config)

    # ── synthesize ──

    @pytest.mark.asyncio
    async def test_synthesize_success(self, config):
        """正常系: WAV バイトが返る"""
        with patch("httpx.AsyncClient") as mock_cls:
            mock_client = MagicMock()
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.content = b"RIFF\x00\x00\x00\x00WAVE"
            mock_resp.raise_for_status = MagicMock()
            mock_client.post = AsyncMock(return_value=mock_resp)
            mock_cls.return_value.__aenter__.return_value = mock_client

            engine = self._make_irodori(config)
            result = await engine.synthesize("こんにちは", emotion="joy")

            assert result == b"RIFF\x00\x00\x00\x00WAVE"

            # POST /v1/audio/speech が正しく呼ばれたか
            call_args = mock_client.post.call_args
            assert call_args[0][0] == "http://irodori:8088/v1/audio/speech"
            sent_json = call_args[1]["json"]
            assert sent_json["input"] == "こんにちは"
            assert sent_json["voice"] == "kiritan"
            assert sent_json["response_format"] == "wav"
            assert sent_json["speed"] == 1.1  # joy

    @pytest.mark.asyncio
    async def test_synthesize_emotion_speed_mapping(self, config):
        """感情ごとに speed が変わる"""
        with patch("httpx.AsyncClient") as mock_cls:
            mock_client = MagicMock()
            mock_resp = MagicMock(status_code=200, content=b"wav")
            mock_resp.raise_for_status = MagicMock()
            mock_client.post = AsyncMock(return_value=mock_resp)
            mock_cls.return_value.__aenter__.return_value = mock_client

            engine = self._make_irodori(config)

            # sadness → 0.9
            await engine.synthesize("悲しい", emotion="sadness")
            assert mock_client.post.call_args[1]["json"]["speed"] == 0.9

            # anger → 1.2
            await engine.synthesize("怒り", emotion="anger")
            assert mock_client.post.call_args[1]["json"]["speed"] == 1.2

            # neutral → 1.0
            await engine.synthesize("普通", emotion="neutral")
            assert mock_client.post.call_args[1]["json"]["speed"] == 1.0

            # unknown → 1.0
            await engine.synthesize("未知", emotion="unknown")
            assert mock_client.post.call_args[1]["json"]["speed"] == 1.0

    @pytest.mark.asyncio
    async def test_synthesize_retries_on_connect_error(self, config):
        """接続エラー時に2回リトライする"""
        with patch("httpx.AsyncClient") as mock_cls:
            mock_client = MagicMock()
            mock_client.post = AsyncMock(side_effect=httpx.ConnectError("Connection refused"))
            mock_cls.return_value.__aenter__.return_value = mock_client

            engine = self._make_irodori(config)

            with pytest.raises(RuntimeError, match="Irodori TTS failed after 3 attempts"):
                await engine.synthesize("test", emotion="neutral")

            assert mock_client.post.call_count == 3  # 初回 + 2リトライ

    @pytest.mark.asyncio
    async def test_synthesize_retries_on_timeout(self, config):
        """タイムアウト時に2回リトライする"""
        with patch("httpx.AsyncClient") as mock_cls:
            mock_client = MagicMock()
            mock_client.post = AsyncMock(side_effect=httpx.TimeoutException("Timeout"))
            mock_cls.return_value.__aenter__.return_value = mock_client

            engine = self._make_irodori(config)

            with pytest.raises(RuntimeError, match="Irodori TTS failed after 3 attempts"):
                await engine.synthesize("test", emotion="neutral")

            assert mock_client.post.call_count == 3

    @pytest.mark.asyncio
    async def test_synthesize_retry_then_succeed(self, config):
        """1回目失敗、2回目成功"""
        with patch("httpx.AsyncClient") as mock_cls:
            mock_client = MagicMock()
            success_resp = MagicMock(status_code=200, content=b"success_wav")
            success_resp.raise_for_status = MagicMock()
            mock_client.post = AsyncMock(
                side_effect=[
                    httpx.ConnectError("fail"),
                    success_resp,
                ]
            )
            mock_cls.return_value.__aenter__.return_value = mock_client

            engine = self._make_irodori(config)
            result = await engine.synthesize("test", emotion="neutral")

            assert result == b"success_wav"
            assert mock_client.post.call_count == 2

    @pytest.mark.asyncio
    async def test_synthesize_raises_on_http_error(self, config):
        """HTTP エラー (400, 500) はリトライせず即座に例外"""
        with patch("httpx.AsyncClient") as mock_cls:
            mock_client = MagicMock()
            error_resp = MagicMock()
            error_resp.status_code = 500
            error_resp.text = "Internal Server Error"
            error_resp.raise_for_status.side_effect = httpx.HTTPStatusError(
                "500 error", request=MagicMock(), response=error_resp
            )
            mock_client.post = AsyncMock(return_value=error_resp)
            mock_cls.return_value.__aenter__.return_value = mock_client

            engine = self._make_irodori(config)

            with pytest.raises(RuntimeError, match="Irodori TTS returned HTTP 500"):
                await engine.synthesize("test", emotion="neutral")

            assert mock_client.post.call_count == 1  # リトライなし

    # ── health_check ──

    @pytest.mark.asyncio
    async def test_health_check_returns_true(self, config):
        """GET /models が200 → True"""
        with patch("httpx.AsyncClient") as mock_cls:
            mock_client = MagicMock()
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_client.get = AsyncMock(return_value=mock_resp)
            mock_cls.return_value.__aenter__.return_value = mock_client

            engine = self._make_irodori(config)
            result = await engine.health_check()

            assert result is True
            mock_client.get.assert_called_once_with("http://irodori:8088/v1/models")

    @pytest.mark.asyncio
    async def test_health_check_returns_false_on_connect_error(self, config):
        """接続エラー → False"""
        with patch("httpx.AsyncClient") as mock_cls:
            mock_client = MagicMock()
            mock_client.get = AsyncMock(side_effect=httpx.ConnectError("Connection refused"))
            mock_cls.return_value.__aenter__.return_value = mock_client

            engine = self._make_irodori(config)
            result = await engine.health_check()

            assert result is False

    @pytest.mark.asyncio
    async def test_health_check_returns_false_on_non_200(self, config):
        """200以外 → False"""
        with patch("httpx.AsyncClient") as mock_cls:
            mock_client = MagicMock()
            mock_resp = MagicMock()
            mock_resp.status_code = 503
            mock_client.get = AsyncMock(return_value=mock_resp)
            mock_cls.return_value.__aenter__.return_value = mock_client

            engine = self._make_irodori(config)
            result = await engine.health_check()

            assert result is False


# ============================================================
# TestVoiceFactory
# ============================================================


class TestVoiceFactory:
    """get_voice_engine のテスト"""

    def test_enabled_returns_engine(self):
        """enabled=True → IrodoriEngine インスタンス"""
        from nous.infrastructure.voice.factory import get_voice_engine
        from nous.infrastructure.voice.irodori import IrodoriEngine

        config = IrodoriConfig(enabled=True, url="http://localhost:8088/v1")
        engine = get_voice_engine(config)

        assert isinstance(engine, IrodoriEngine)

    def test_disabled_returns_none(self):
        """enabled=False → None"""
        from nous.infrastructure.voice.factory import get_voice_engine

        config = IrodoriConfig(enabled=False)
        engine = get_voice_engine(config)

        assert engine is None

    def test_default_config_is_disabled(self):
        """デフォルト設定では無効 (None)"""
        from nous.infrastructure.voice.factory import get_voice_engine

        config = IrodoriConfig()  # enabled=False
        engine = get_voice_engine(config)

        assert engine is None
