"""プロジェクト引き継ぎ栞（kanban #58）。

``session_begin(project=<slug>)`` の出力に 1 行だけ差し込む「前回どこまでやったか」。
決定論的・LLM 呼び出しゼロ。エージェントが key ``handover:<slug>`` の記憶を
自分で書いていれば、そちらが常に勝つ（自動生成で上書きしない）。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import datetime

    from nous.domain.memory.entities import Memory

HANDOVER_KEY_PREFIX = "handover:"
# 自動生成側の栞に付けるタグ。このタグが付いている ``handover:<slug>`` は
# 「自動更新してよい」、付いていない（＝エージェントが明示的に書いた）ものは上書きしない。
AUTO_TAG = "handover-auto"
ELLIPSIS = "…"
MAX_DONE = 3
MAX_TOPICS = 2
MAX_ITEM_CHARS = 80


def handover_key(project: str) -> str:
    """明示更新に使う記憶キー。"""
    return f"{HANDOVER_KEY_PREFIX}{project}"


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
) -> str:
    """``完了: ... | 論点: ... | 次: ...`` の 1 行を返す。空入力なら ""。

    memories: 当該 project の記憶（``handover:<project>`` を含めてよい）
    questions: 未解決の問い（新しい順。先頭2件が論点、末尾が「次」）

    明示更新 = ``handover:<project>`` キーの記憶に ``handover-auto`` タグが無いもの。
    """
    if limit <= 0:
        return ""
    key = handover_key(project)
    explicit = next((m for m in memories if m.key == key and AUTO_TAG not in (m.tags or [])), None)
    if explicit is not None:
        return _fit(" ".join(str(explicit.content).split()), limit)

    pending = [" ".join(str(q).split()) for q in questions if str(q).strip()]
    # 未解決の問いを「完了」に潜らせない（同じ文面で判定するのでタグ依存しない）。
    done = sorted(
        (m for m in memories if m.content and m.key != key and " ".join(str(m.content).split()) not in set(pending)),
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
