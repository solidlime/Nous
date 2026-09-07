"""TurnHub: persona 毎のターンイベント配信ハブ（E3 チャット分離）。

リリングバッファ（遅延接続のリプレイ用）＋クライアント毎 queue（drop-oldest）。
チャット delta は EventBus を通さずこのハブ専用（EventBus は低頻度用）。
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import uuid
from collections import deque


class TurnHub:
    """persona 毎のターンイベント配信。1 persona 同時 1 ターン。"""

    def __init__(self, buffer_size: int = 600, queue_size: int = 256) -> None:
        self._buffer_size = buffer_size
        self._queue_size = queue_size
        self._buffers: dict[str, deque[tuple[int, str]]] = {}
        self._seqs: dict[str, int] = {}
        self._subscribers: dict[str, list[asyncio.Queue]] = {}
        self._running: set[str] = set()

    def begin_turn(self, persona: str) -> str | None:
        """turn_id 発行。実行中なら None（409 用）。"""
        if persona in self._running:
            return None
        self._running.add(persona)
        return uuid.uuid4().hex

    def end_turn(self, persona: str) -> None:
        """実行フラグ解除。バッファは残置（遅延接続のリプレイ用）。"""
        self._running.discard(persona)

    def publish(self, persona: str, sse_str: str) -> None:
        """SSE 文字列（evt.to_sse() の戻り値）をバッファ（seq 付与）＋全 subscriber queue へ。

        queue は put_nowait・満杯なら最古を drop（drop-oldest）。
        """
        seq = self._seqs.get(persona, 0) + 1
        self._seqs[persona] = seq
        item = (seq, sse_str)
        self._buffers.setdefault(persona, deque(maxlen=self._buffer_size)).append(item)
        for q in self._subscribers.get(persona, []):
            if q.full():
                with contextlib.suppress(asyncio.QueueEmpty):
                    q.get_nowait()
            q.put_nowait(item)

    def publish_synthetic(self, persona: str, payload: dict) -> str:
        """{"type": "turn_started", ...} 等を合成発行し sse 文字列を返す。"""
        sse = f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
        self.publish(persona, sse)
        return sse

    def snapshot_after(self, persona: str, last_seq: int) -> list[tuple[int, str]]:
        """last_seq より新しい (seq, sse) を時系列順で返す。"""
        return [item for item in self._buffers.get(persona, ()) if item[0] > last_seq]

    def subscribe(self, persona: str) -> asyncio.Queue:
        """ライブ購読 queue を返す。要素は (seq, sse_str)。"""
        q: asyncio.Queue = asyncio.Queue(maxsize=self._queue_size)
        self._subscribers.setdefault(persona, []).append(q)
        return q

    def unsubscribe(self, persona: str, queue: asyncio.Queue) -> None:
        subs = self._subscribers.get(persona)
        if subs:
            self._subscribers[persona] = [q for q in subs if q is not queue]
