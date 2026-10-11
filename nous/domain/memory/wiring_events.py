"""Synapse fire event feed — thread-safe ring buffer for UI visualization.

Kinds: ``link_fire`` (Hebbian co-activation), ``recall_boost``
(strength boost on recall), ``ppr_hit`` (PPR top seeds with scores),
``replay_fire`` (offline reactivation / memory enrichment / decay-cycle
stability update), ``novelty_gate`` (novelty-gated stability boost from
the EnrichmentWorker), ``decision_pass`` / ``decision_reject`` (Jev 型判定
ゲートの per-candidate 判定), ``hop_start`` / ``hop_stop`` (multi-hop 検索の
hop 境界)、``propagate`` / ``converge`` (multi-hop の拡散 / 収束)。
``decision_bypass`` は fail-open で judge を適用しなかった事実。
``prompt_inject`` は返答生成プロンプトへの記憶挿入の**確定**（使用の証明ではない）。
``decision_hop`` はバッファ枯渇時に decision 系 per-candidate を畳んだ per-hop サマリ。

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
- ``request_id`` は **省くと沈黙する**（``prompt_inject`` を除く）: 発火モードの
  消費側は ``meta.request_id`` が自分の UUID と一致しないイベントを捨てる。相関 ID を
  持つ経路（REST ``/api/search`` / MCP ``memory_search`` / chat recall）では
  必須。``turn_id`` は発話単位の相関（連鎖の境界は kind ではなくこの変わり目）。
- ``prompt_inject``: そのターンで実際に system プロンプトへ挿入された記憶 1 件 =
  1 イベント（``<related_memories>`` 分岐の成立時に emit、``source`` = 記憶の key）。
  ``meta`` は ``{persona, turn_id}`` を**必須**とし、任意で ``session_id`` /
  ``origin``（``note`` / ``episode``）を持つ。**``request_id`` は載せない**: 挿入は
  2 クエリ（+ episode fallback）の合成結果であり単一 request_id に還元できない。
  すなわち ``prompt_inject`` は ``turn_id`` 相関であり ``request_id`` 非依存 —
  消費側はこの kind に ``request_id`` 一致を要求してはならない。
  証明できるのは「プロンプトに入った」までで、LLM が実際にその記憶を使って
  応答を生成したかは**観測不能**（挿入の確定であって使用の証明ではない）。
- ``decision_hop``: バッファ枯渇時に oldest の per-candidate な ``decision_pass`` /
  ``decision_reject`` / ``decision_bypass`` を per-(persona, request_id, turn_id,
  hop) に畳んだサマリ。``meta`` = ``{persona, request_id, turn_id, hop, count,
  passed, rejected, bypass}``。``passed`` / ``rejected`` / ``bypass`` の各要素は
  元イベントの ``source`` と meta を保持するので候補明細は失われない（復元可能）。
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
        "prompt_inject",
        "decision_hop",
    ]
)
# 1 リクエストの消費量（実測見積）: decision_pass/reject が候補数 × hops で発火する
# （5 hop × 30 候補 = 150 件）うえ、enrich_service の replay_fire / novelty_gate が
# 同一 deque に常時流入する。10d(1025c762) で 200 → 1024 に増設（200 では 1 リクエストで
# 連鎖の頭が消える）。Phase 10(d67c4f17) で溢れ計器 _dropped_from_head を追加し 1024 → 4096。
# （Phase 13 で集約を実装済み: 溢れる前に _compact_locked が古い decision 系を decision_hop へ畳む）。
WIRING_BUFFER_SIZE = 4096
# リングバッファ溢れで頭から消えた累計。連鎖の頭が欠けている事実を実測するための計器
# （100 件ごとに warn を出す）。
_dropped_from_head = 0

# バッファ枯渇時に per-hop サマリ（decision_hop）へ畳む kind。連鎖の頭が消えるのを
# 防ぐ根本対策（per-candidate × hops × 2 クエリ/ターンで長セッション時に溢れる）。
_AGGREGATABLE_DECISION_KINDS = frozenset({"decision_pass", "decision_reject", "decision_bypass"})
# 満杯時に畳む対象として走査する「古い側」の件数。古い側のみ畳むのでライブな
# per-candidate イベント（グラフの発光アニメーションが使う）はそのまま流れる。
_COMPACT_SCAN = 1024


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
        # 満杯なら最古（=連鎖の頭）を落とす前に decision 系を per-hop へ畳んで空ける。
        if len(_buffer) == _buffer.maxlen:
            _compact_locked()
        # それでも満杯なら append で最古が落ちる（満杯にした append 自身は落とさない）。
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


def _compact_locked() -> int:
    """Fold oldest per-candidate decision events into per-hop summaries.

    Caller holds ``_lock``. Runs only when the buffer is full; groups with >= 2
    members are folded so at least one slot is always freed. Individual candidate
    detail survives in the summary meta (recoverable via REST/SSE snapshot).
    Returns the number of slots freed (0 when nothing was aggregatable).
    """
    window = list(itertools.islice(_buffer, _COMPACT_SCAN))
    groups: dict[tuple, list[WiringEvent]] = {}
    for e in window:
        if e.kind not in _AGGREGATABLE_DECISION_KINDS:
            continue
        request_id = e.meta.get("request_id")
        turn_id = e.meta.get("turn_id")
        if not (request_id or turn_id):
            continue  # 相関不能なイベントは hop を特定できないので畳まない
        groups.setdefault((e.meta.get("persona"), request_id, turn_id, e.meta.get("hop")), []).append(e)

    collapsed: dict[int, WiringEvent] = {}  # 先頭に畳んだ要素の seq -> サマリ
    doomed: set[int] = set()
    for members in groups.values():
        if len(members) < 2:
            continue
        first = members[0]

        def _rows(kind: str, group: list[WiringEvent]) -> list[dict[str, Any]]:
            rows = []
            for m in group:
                if m.kind != kind:
                    continue
                row = dict(m.meta)
                row["source"] = m.source
                row["weight"] = m.weight
                rows.append(row)
            return rows

        collapsed[first.seq] = WiringEvent(
            seq=first.seq,
            kind="decision_hop",
            source="",
            target="",
            weight=float(len(members)),
            meta={
                "persona": first.meta.get("persona"),
                "request_id": first.meta.get("request_id"),
                "turn_id": first.meta.get("turn_id"),
                "hop": first.meta.get("hop"),
                "count": len(members),
                "passed": _rows("decision_pass", members),
                "rejected": _rows("decision_reject", members),
                "bypass": _rows("decision_bypass", members),
            },
            ts=first.ts,
        )
        doomed.update(m.seq for m in members)

    if not doomed:
        return 0
    freed = len(doomed) - len(collapsed)
    rebuilt: deque[WiringEvent] = deque(maxlen=_buffer.maxlen)
    for e in _buffer:
        if e.seq in collapsed:
            rebuilt.append(collapsed[e.seq])
        elif e.seq not in doomed:
            rebuilt.append(e)
    _buffer.clear()
    _buffer.extend(rebuilt)
    return freed


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
