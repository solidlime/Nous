"""MoT high-confidence thoughts table (F5).

Separate slot from fact recall: gist consolidation stores high-confidence
traces here; recall fetches top-k without touching fact scores. Corrosion
(time decay + TTL) lives on this table only — never double-decayed with
``memory_strength`` / ``memory_links``.

eMoT weighting is undecided: plain linear corrosion + TTL for now.
"""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta

from nous.domain.shared.time_utils import format_iso, get_now
from nous.infrastructure.logging.structured import get_logger

logger = get_logger(__name__)

MOT_CONFIDENCE_THRESHOLD = 0.8
MOT_TOP_K = 3
MOT_CORROSION_PER_HOUR = 0.02
MOT_MIN_EFFECTIVE_CONFIDENCE = 0.5
MOT_TTL_HOURS = 72

MOT_THOUGHTS_DDL = """
CREATE TABLE IF NOT EXISTS mot_thoughts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    key TEXT NOT NULL,
    consolidation_key TEXT NOT NULL,
    trace TEXT NOT NULL,
    confidence REAL NOT NULL DEFAULT 0.0,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_mot_thoughts_key ON mot_thoughts(key);
CREATE INDEX IF NOT EXISTS idx_mot_thoughts_consolidation ON mot_thoughts(consolidation_key);
CREATE INDEX IF NOT EXISTS idx_mot_thoughts_created ON mot_thoughts(created_at DESC);
"""


@dataclass
class MotThought:
    """A high-confidence trace with corrosion-adjusted confidence."""

    key: str
    consolidation_key: str
    trace: str
    confidence: float
    created_at: str


def ensure_thoughts_table(db_conn: sqlite3.Connection) -> None:
    """Idempotent DDL for ``mot_thoughts`` (safe to run on every access)."""
    db_conn.executescript(MOT_THOUGHTS_DDL)


def effective_confidence(stored: float, created_at: str, now: datetime | None = None) -> float:
    """Linear corrosion: stored − rate·age_hours (floor 0)."""
    try:
        created = datetime.fromisoformat(created_at)
        ref = now or get_now()
        if created.tzinfo is None and ref.tzinfo is not None:
            ref = ref.replace(tzinfo=None)
        age_hours = max(0.0, (ref - created).total_seconds() / 3600.0)
    except (ValueError, TypeError):
        age_hours = 0.0
    return max(0.0, stored - MOT_CORROSION_PER_HOUR * age_hours)


def save_thought(
    db_conn: sqlite3.Connection,
    key: str,
    consolidation_key: str,
    trace: str,
    confidence: float,
    created_at: str | None = None,
) -> bool:
    """Persist a trace iff confidence ≥ threshold. Returns True when saved."""
    try:
        conf = float(confidence)
    except (TypeError, ValueError):
        return False
    if conf < MOT_CONFIDENCE_THRESHOLD:
        return False
    ensure_thoughts_table(db_conn)
    prune_expired(db_conn)
    db_conn.execute(
        "INSERT INTO mot_thoughts (key, consolidation_key, trace, confidence, created_at) VALUES (?, ?, ?, ?, ?)",
        (key, consolidation_key, trace, conf, created_at or format_iso(get_now())),
    )
    db_conn.commit()
    return True


def prune_expired(db_conn: sqlite3.Connection, now: datetime | None = None) -> int:
    """Delete TTL-expired rows. Returns pruned count."""
    ensure_thoughts_table(db_conn)
    ref = now or get_now()
    cutoff = (ref - timedelta(hours=MOT_TTL_HOURS)).isoformat()
    cursor = db_conn.execute("DELETE FROM mot_thoughts WHERE created_at < ?", (cutoff,))
    db_conn.commit()
    return cursor.rowcount


def fetch_thoughts(
    db_conn: sqlite3.Connection,
    query_text: str,
    limit: int = MOT_TOP_K,
    now: datetime | None = None,
) -> list[MotThought]:
    """Top-k thoughts by query-token overlap, corrosion-filtered.

    Separate slot: never alters fact-recall scores. Rows below the
    effective-confidence floor or without any token hit are excluded.
    """
    ensure_thoughts_table(db_conn)
    prune_expired(db_conn, now)
    tokens = [t for t in re.split(r"\W+", (query_text or "").casefold()) if len(t) >= 2]
    if not tokens:
        return []
    ref = now or get_now()
    scored: list[tuple[int, float, str, MotThought]] = []
    try:
        rows = db_conn.execute(
            "SELECT key, consolidation_key, trace, confidence, created_at FROM mot_thoughts"
        ).fetchall()
    except sqlite3.OperationalError:
        return []
    for row in rows:
        trace = row["trace"] or ""
        lowered = trace.casefold()
        hits = sum(lowered.count(tok) for tok in tokens)
        if hits <= 0:
            continue
        eff = effective_confidence(float(row["confidence"]), row["created_at"], ref)
        if eff < MOT_MIN_EFFECTIVE_CONFIDENCE:
            continue
        scored.append(
            (
                hits,
                eff,
                row["created_at"],
                MotThought(
                    key=row["key"],
                    consolidation_key=row["consolidation_key"],
                    trace=trace,
                    confidence=eff,
                    created_at=row["created_at"],
                ),
            )
        )
    scored.sort(key=lambda s: (-s[0], -s[1], s[2]))
    return [s[3] for s in scored[:limit]]
