"""添付アップロードのサイズ上限（kanban #76）。"""

from __future__ import annotations

import asyncio
from io import BytesIO
from typing import Any, cast

from starlette.datastructures import UploadFile

from nous.api.http.routers.chat import chat_management as cm
from nous.domain.config.chat_config import ChatConfig


class _ChunkedUpload:
    """read(n) を 1 チャンクずつ返す偽アップロード。size は申告なし。"""

    size = None

    def __init__(self, chunks: list[bytes]) -> None:
        self._chunks = chunks

    async def read(self, n: int) -> bytes:
        return self._chunks.pop(0) if self._chunks else b""


class _FakeRequest:
    def __init__(self, upload: UploadFile) -> None:
        self._upload = upload

    async def form(self) -> dict[str, object]:
        return {"file": self._upload}


def test_read_limited_stops_at_limit():
    """上限を超えたら None（読んだ分は捨てる）。"""
    chunks = [b"x" * 1024] * 4 + [b""]
    assert asyncio.run(cm._read_limited(_ChunkedUpload(chunks), 2048)) is None


def test_read_limited_returns_body_within_limit():
    chunks = [b"abc", b"de", b""]
    assert asyncio.run(cm._read_limited(_ChunkedUpload(chunks), 2048)) == b"abcde"


def test_read_limited_short_circuits_on_declared_size():
    """Content-Length 由来の size が上限超なら、1 バイトも読まない。"""
    limit = ChatConfig().max_attachment_bytes
    upload = UploadFile(file=BytesIO(b""), size=limit + 1, filename="big.bin")
    assert asyncio.run(cm._read_limited(upload, limit)) is None


def test_upload_returns_413_and_writes_nothing(monkeypatch):
    """上限超過は 413。保存処理（_do_attachment_upload）へは渡さない。"""
    monkeypatch.setattr(cm, "_resolve_request", lambda request: ("herta", object()))
    saved: list[tuple] = []

    async def _spy(*args):
        saved.append(args)
        return {"filename": "x"}

    monkeypatch.setattr(cm, "_do_attachment_upload", _spy)
    upload = UploadFile(file=BytesIO(b""), size=ChatConfig().max_attachment_bytes + 1, filename="big.bin")

    response = asyncio.run(cm.attachment_upload(cast("Any", _FakeRequest(upload))))

    assert response.status_code == 413
    assert saved == []
