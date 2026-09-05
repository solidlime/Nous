"""IrodoriEngine.stream_speech (SSE) の単体テスト — test_voice.py の mock 流儀に合わせる."""

from __future__ import annotations

import base64
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nous.config.settings import IrodoriConfig

pytestmark = pytest.mark.unit


@pytest.fixture
def config() -> IrodoriConfig:
    return IrodoriConfig(url="http://irodori:8088", voice="kiritan", timeout_seconds=30)


def _make_engine(config: IrodoriConfig):
    from nous.infrastructure.voice.irodori import IrodoriEngine

    return IrodoriEngine(config)


def _wire_stream_mock(mock_cls, lines: list[str]):
    """httpx.AsyncClient → client.stream() が lines を返すよう配線。client を返す。"""
    mock_client = MagicMock()
    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()

    async def _aiter():
        for ln in lines:
            yield ln

    mock_resp.aiter_lines = MagicMock(return_value=_aiter())
    mock_stream_ctx = MagicMock()
    mock_stream_ctx.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_stream_ctx.__aexit__ = AsyncMock(return_value=False)
    mock_client.stream = MagicMock(return_value=mock_stream_ctx)
    mock_cls.return_value.__aenter__.return_value = mock_client
    return mock_client


@pytest.mark.asyncio
async def test_stream_speech_yields_chunks_and_sends_sse_params(config):
    """SSE正常系: 2チャンクyield＋stream_format/first_sentence送信。"""
    c1 = base64.b64encode(b"wav1").decode()
    c2 = base64.b64encode(b"wav2").decode()
    lines = [
        f'data: {{"type": "audio_chunk", "audio_base64": "{c1}"}}',
        f'data: {{"type": "audio_chunk", "audio_base64": "{c2}"}}',
        'data: {"type": "done"}',
    ]
    with patch("httpx.AsyncClient") as mock_cls:
        mock_client = _wire_stream_mock(mock_cls, lines)
        engine = _make_engine(config)
        got = [chunk async for chunk in engine.stream_speech("こんにちは", emotion="neutral")]
        assert got == [b"wav1", b"wav2"]

        call_args = mock_client.stream.call_args
        assert call_args[0][0] == "POST"
        assert call_args[0][1] == "http://irodori:8088/v1/audio/speech"
        sent_json = call_args[1]["json"]
        assert sent_json["stream_format"] == "sse"
        assert sent_json["irodori"]["first_sentence_chunk_min_chars"] == 1
        assert sent_json["irodori"]["chunk_min_chars"] == 40


@pytest.mark.asyncio
async def test_stream_speech_skips_noise_and_bad_chunks(config):
    """非data行・壊れたJSON・空b64は無視し、有効チャンクのみyield。"""
    good = base64.b64encode(b"ok").decode()
    lines = [
        ": keep-alive",
        "",
        "not a data line",
        "data: not-json{",
        'data: {"type": "audio_chunk", "audio_base64": "!!!"}',
        f'data: {{"type": "audio_chunk", "audio_base64": "{good}"}}',
        'data: {"type": "done"}',
    ]
    with patch("httpx.AsyncClient") as mock_cls:
        _wire_stream_mock(mock_cls, lines)
        engine = _make_engine(config)
        got = [chunk async for chunk in engine.stream_speech("test", emotion="neutral")]
        assert got == [b"ok"]


@pytest.mark.asyncio
async def test_synthesize_does_not_send_stream_params(config):
    """synthesizeは単発形状のまま: stream_format/first_sentenceを送らない。"""
    with patch("httpx.AsyncClient") as mock_cls:
        mock_client = MagicMock()
        mock_resp = MagicMock(status_code=200, content=b"wav")
        mock_resp.raise_for_status = MagicMock()
        mock_client.post = AsyncMock(return_value=mock_resp)
        mock_cls.return_value.__aenter__.return_value = mock_client

        engine = _make_engine(config)
        await engine.synthesize("hello", emotion="neutral")

        sent_json = mock_client.post.call_args[1]["json"]
        assert "stream_format" not in sent_json
        assert "first_sentence_chunk_min_chars" not in sent_json["irodori"]
