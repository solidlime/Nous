"""プロジェクト引き継ぎ栞（kanban #58）。

``session_begin(project=<slug>)`` の出力に 1 行だけ差し込む「前回どこまでやったか」。
決定論的・LLM 呼び出しゼロ。保存先は ``persona_info`` の ``handover:<slug>``
（memories に置くと Zero Inbox の編纂で物理削除される）。エージェントが自分で書いた
値があれば、そちらが常に勝つ（自動生成で上書きしない）。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import datetime

    from nous.domain.memory.entities import Memory

HANDOVER_KEY_PREFIX = "handover:"
ELLIPSIS = "…"
MAX_DONE = 3
MAX_TOPICS = 2
MAX_ITEM_CHARS = 80


def handover_key(project: str) -> str:
    """``persona_info`` のキー。"""
    return f"{HANDOVER_KEY_PREFIX}{project}"


def read_handover(state: object, project: str | None) -> str | None:
    """``state.persona_info`` から明示更新の栞を読む（project 未指定なら None）。"""
    if not project:
        return None
    info = getattr(state, "persona_info", None) or {}
    value = info.get(handover_key(project))
    return str(value) if value else None


def _timestamp(memory: Memory, now: datetime) -> datetime:
    # 並び順が保証されない入力でも決定論にするため updated_at → created_at → now で錨を取る。
    return memory.updated_at or memory.created_at or now


def _snippet(text: str) -> str:
    flat = " ".join(str(text).split())
    return flat if len(flat) <= MAX_ITEM_CHARS else flat[: MAX_ITEM_CHARS - 1] + ELLIPSIS


def _fit(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1] + ELLIPSIS


def build_handover(
    project: str,
    memories: Sequence[Memory],
    questions: Sequence[str],
    now: datetime,
    limit: int = 400,
    explicit: str | None = None,
) -> str:
    """``完了: ... | 論点: ... | 次: ...`` の 1 行を返す。空入力なら ""。

    memories: 当該 project の記憶（自動生成の材料）
    questions: 未解決の問い（新しい順。先頭2件が論点、末尾が「次」）
    explicit: エージェントが自分で書いた引き継ぎ（``persona_info`` 由来）。あれば常に勝つ。
    """
    if limit <= 0:
        return ""
    if explicit and str(explicit).strip():
        return _fit(" ".join(str(explicit).split()), limit)

    pending = [" ".join(str(q).split()) for q in questions if str(q).strip()]
    # 未解決の問いを「完了」に潜らせない（同じ文面で判定するのでタグ依存しない）。
    done = sorted(
        (m for m in memories if m.content and " ".join(str(m.content).split()) not in set(pending)),
        key=lambda m: _timestamp(m, now),
        reverse=True,
    )[:MAX_DONE]
    parts: list[str] = []
    if done:
        parts.append("完了: " + " / ".join(_snippet(m.content) for m in done))
    if pending:
        parts.append("論点: " + " / ".join(_snippet(q) for q in pending[:MAX_TOPICS]))
        parts.append("次: " + _snippet(pending[-1]))
    if not parts:
        return ""
    return _fit(" | ".join(parts), limit)
