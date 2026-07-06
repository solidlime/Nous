"""VoiceEngine インフラ層の単体テスト"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from nous.config.settings import IrodoriConfig
from nous.domain.persona.entities import PersonaState

# ============================================================
# TestEmotionCaption
# ============================================================


class TestEmotionCaption:
    """build_caption のテスト"""

    def _make_persona(
        self,
        emotion: str = "neutral",
        emotion_intensity: float = 0.0,
        speech_style: str | None = None,
        context_note: str | None = None,
    ) -> PersonaState:
        """PersonaState を簡易構築するヘルパー。"""
        # PersonaState は dataclass → context_note を持たないので getattr 経由
        ps = PersonaState(persona="test", emotion=emotion, emotion_intensity=emotion_intensity)
        ps.speech_style = speech_style
        if context_note is not None:
            object.__setattr__(ps, "context_note", context_note)
        return ps

    def test_neutral_no_style(self):
        """neutral + styleなし → '無表情で'"""
        from nous.infrastructure.voice.emotion import build_caption

        ps = self._make_persona("neutral")
        assert build_caption(ps) == "無表情で"

    def test_joy(self):
        """joy → '嬉しそうに'"""
        from nous.infrastructure.voice.emotion import build_caption

        ps = self._make_persona("joy")
        assert build_caption(ps) == "嬉しそうに"

    def test_sadness(self):
        from nous.infrastructure.voice.emotion import build_caption

        ps = self._make_persona("sadness")
        assert build_caption(ps) == "悲しそうに"

    def test_anger(self):
        from nous.infrastructure.voice.emotion import build_caption

        ps = self._make_persona("anger")
        assert build_caption(ps) == "怒ったように"

    def test_fear(self):
        from nous.infrastructure.voice.emotion import build_caption

        ps = self._make_persona("fear")
        assert build_caption(ps) == "怯えたように"

    def test_surprise(self):
        from nous.infrastructure.voice.emotion import build_caption

        ps = self._make_persona("surprise")
        assert build_caption(ps) == "驚いたように"

    def test_unknown_emotion_falls_back(self):
        """未定義の感情 → fallback '普通に'"""
        from nous.infrastructure.voice.emotion import build_caption

        ps = self._make_persona("unknown_emotion")
        assert build_caption(ps) == "普通に"

    def test_empty_emotion_falls_back(self):
        """空文字の感情 → fallback '普通に'"""
        from nous.infrastructure.voice.emotion import build_caption

        ps = self._make_persona("")
        assert build_caption(ps) == "普通に"

    def test_emotion_with_speech_style(self):
        """感情 + 口調が合成される"""
        from nous.infrastructure.voice.emotion import build_caption

        ps = self._make_persona("joy", speech_style="元気")
        result = build_caption(ps)
        assert "嬉しそうに" in result
        assert "元気" in result

    def test_speech_style_only(self):
        """emotionなし、speech_styleのみ"""
        from nous.infrastructure.voice.emotion import build_caption

        ps = self._make_persona("neutral", speech_style="優しい")
        result = build_caption(ps)
        assert "優しい" in result

    def test_with_context_note(self):
        """context_note が存在すれば追加される"""
        from nous.infrastructure.voice.emotion import build_caption

        ps = self._make_persona("joy", context_note="少し照れながら")
        result = build_caption(ps)
        assert "少し照れながら" in result
        assert "嬉しそうに" in result

    def test_all_fields(self):
        """emotion + speech_style + context_note 全て合成"""
        from nous.infrastructure.voice.emotion import build_caption

        ps = self._make_persona(
            emotion="anger",
            speech_style="低い",
            context_note="歯を食いしばりながら",
        )
        result = build_caption(ps)
        assert "怒ったように" in result
        assert "低い" in result
        assert "歯を食いしばりながら" in result


# ============================================================
# EMOTION_EMOJI
# ============================================================


class TestEmotionEmoji:
    """EMOTION_EMOJI 定数のテスト"""

    def test_emoji_keys(self):
        from nous.infrastructure.voice.emotion import EMOTION_EMOJI

        assert EMOTION_EMOJI["neutral"] == ""
        assert EMOTION_EMOJI["joy"] == "😊"
        assert EMOTION_EMOJI["sadness"] == "😢"
        assert EMOTION_EMOJI["anger"] == "😠"
        assert EMOTION_EMOJI["fear"] == "😨"
        assert EMOTION_EMOJI["surprise"] == "😲"

    def test_all_defined_emotions_have_entries(self):
        from nous.infrastructure.voice.emotion import EMOTION_EMOJI

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
