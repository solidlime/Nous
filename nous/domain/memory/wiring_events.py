"""Synapse fire event feed — thread-safe ring buffer for UI visualization.

Kinds: ``link_fire`` (Hebbian co-activation), ``recall_boost``
(strength boost on recall), ``ppr_hit`` (PPR top seeds with scores),
``replay_fire`` (offline reactivation / memory enrichment / decay-cycle
stability update), ``novelty_gate`` (novelty-gated stability boost from
the EnrichmentWorker).

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

WIRING_KINDS = frozenset(["link_fire", "recall_boost", "ppr_hit", "replay_fire", "novelty_gate"])
WIRING_BUFFER_SIZE = 200


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
        _buffer.append(event)
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
    with _lock:
        _buffer.clear()
