"""Synapse fire event feed — thread-safe ring buffer for UI visualization.

Kinds: ``link_fire`` (Hebbian co-activation), ``recall_boost``
(strength boost on recall), ``ppr_hit`` (PPR top seeds with scores),
``replay_fire`` (offline reactivation / memory enrichment / decay-cycle
stability update), ``novelty_gate`` (novelty-gated stability boost from
the EnrichmentWorker), ``decision_pass`` / ``decision_reject`` (Jev 型判定
ゲートの per-candidate 判定), ``hop_start`` / ``hop_stop`` (multi-hop 検索の
hop 境界)、``propagate`` / ``converge`` (multi-hop の拡散 / 収束)。
``decision_bypass`` は fail-open で judge を適用しなかった事実。

meta 契約（暗黙にしない）:

- ``{persona, hop, request_id, turn_id}`` が hop / decision 系の共通形。
  decision 系は更に ``threshold``（+ 生値 ``cosine`` / ``jev`` /
  ``time_weight``）、``hop_stop`` と ``converge`` は ``reason``
  （``sufficiency`` / ``max_hops`` / ``no_progress`` / ``no_candidates``）。
- ``decision_bypass``: ``{persona, reason, request_id, hop, turn_id}``。
  ``reason`` は ``no_candidates`` / ``judge_unavailable`` / ``parse_failed`` /
  ``no_api_key``。
- ``propagate``: ``source`` = 手がかり記憶キー、``target`` = 新規獲得キー、
  ``meta`` = ``{persona, hop, request_id, turn_id, via}``。エッジ遍歴ではなく
  **クエリ媒介の拡散**（hop N の採用記憶を手がかりに hop N+1 が新規記憶を獲得）。
  1 hop につき新規キー 1 件 = 1 イベント（ペア全数 emit はしない）。
- ``converge``: ``source`` = 最終出力のキー、``target`` = 出力の主座 (top-1)。
  発火点は終端 2 箇所のみ（hop ループ脱出点と単発経路の ``_finalize``）。
- ``request_id`` は **省くと沈黙する**: 発火モードの消費側は
  ``meta.request_id`` が自分の UUID と一致しないイベントを捨てる。相関 ID を
  持つ経路（REST ``/api/search`` / MCP ``memory_search`` / chat recall）では
  必須。``turn_id`` は発話単位の相関（連鎖の境界は kind ではなくこの変わり目）。
- ``hop_start`` に ``seeds`` は**無い**（契約に存在しない）: hop_start は
  retrieve **前** に emit されるため engine は seed を知り得ない。seed 点灯は
  ``ppr_hit`` と ``propagate`` が担う。

Emitters must never break main flows: wrap :func:`emit` in try/except
at call sites (debug log, always continue).
"""

from __future__ import annotations

import itertools
import logging
import threading
from collections import deque
from dataclasses import asdict, dataclass, field
from typing import Any

from nous.domain.shared.time_utils import format_iso, get_now

logger = logging.getLogger(__name__)

WIRING_KINDS = frozenset(
    [
        "link_fire",
        "recall_boost",
        "ppr_hit",
        "replay_fire",
        "novelty_gate",
        "monologue",
        "decision_pass",
        "decision_reject",
        "decision_bypass",
        "hop_start",
        "hop_stop",
        "propagate",
        "converge",
    ]
)
# 1 リクエストの消費量（実測見積）: decision_pass/reject が候補数 × hops で発火する
# （5 hop × 30 候補 = 150 件）うえ、enrich_service の replay_fire / novelty_gate が
# 同一 deque に常時流入する。200 では 1 リクエストで連鎖の頭が消える。
# TODO(drive-by): 根本対策は per-candidate → per-hop サマリへの集約（契約変更を伴う別件）。
WIRING_BUFFER_SIZE = 4096
# リングバッファ溢れで頭から消えた累計。連鎖の頭が欠けている事実を実測するための計器
# （100 件ごとに warn を出す。per-hop 集約は実測で欠損が観測されてから立案する）。
_dropped_from_head = 0


@dataclass(frozen=True)
class WiringEvent:
    """A single synapse-fire event."""

    seq: int
    kind: str
    source: str
    target: str
    weight: float
    meta: dict[str, Any] = field(default_factory=dict)
    ts: str = ""


_lock = threading.Lock()
_buffer: deque[WiringEvent] = deque(maxlen=WIRING_BUFFER_SIZE)
_seq = itertools.count(1)


def emit(
    kind: str,
    source: str = "",
    target: str = "",
    weight: float = 0.0,
    meta: dict[str, Any] | None = None,
) -> bool:
    """Append an event to the ring buffer. Returns False when dropped."""
    if kind not in WIRING_KINDS:
        logger.debug("wiring: unknown kind %r dropped", kind)
        return False
    try:
        event = WiringEvent(
            seq=0,
            kind=kind,
            source=source,
            target=target,
            weight=float(weight),
            meta=dict(meta or {}),
            ts=format_iso(get_now()),
        )
    except (TypeError, ValueError):
        logger.debug("wiring: bad payload dropped", exc_info=True)
        return False
    with _lock:
        event = WiringEvent(
            seq=next(_seq),
            kind=event.kind,
            source=event.source,
            target=event.target,
            weight=event.weight,
            meta=event.meta,
            ts=event.ts,
        )
        # 既に満杯なら append で最古が落ちる（満杯にした append 自身は落とさない）。
        full = len(_buffer) == _buffer.maxlen
        _buffer.append(event)
        if full:
            global _dropped_from_head
            _dropped_from_head += 1
            if _dropped_from_head == 1 or _dropped_from_head % 100 == 0:
                logger.warning(
                    "wiring buffer full (%d): %d events dropped from the head — chain heads will be missing",
                    _buffer.maxlen,
                    _dropped_from_head,
                )
    return True


def snapshot_after(last_seq: int = 0, persona: str | None = None) -> list[dict[str, Any]]:
    """Ordered event dicts with seq greater than *last_seq* (no thinning).

    ``persona`` filters on ``meta["persona"]``; None returns everything
    (backward compatible, legacy events included).
    """
    with _lock:
        events = [e for e in _buffer if e.seq > last_seq]
    if persona is None:
        return [asdict(e) for e in events]
    return [asdict(e) for e in events if e.meta.get("persona") == persona]


def repo_persona(repo: Any) -> str | None:
    """Best-effort persona from a repo's connection (None when unavailable)."""
    try:
        persona = getattr(getattr(repo, "_conn", None), "persona", None)
        return persona if isinstance(persona, str) else None
    except Exception:
        return None


def clear() -> None:
    """Drop all buffered events (tests / persona switch)."""
    global _dropped_from_head
    with _lock:
        _buffer.clear()
        _dropped_from_head = 0
