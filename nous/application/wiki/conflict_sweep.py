"""記憶層の矛盾掃除（#39）。

wiki 編纂は「ページ同士の食い違い」を LLM 応答の ``conflicts`` で拾うが、記憶そのもの
（同じ project の似た 2 件で数値や結論が食い違う）は編纂プロンプトに載らないまま溜まる。
ここでは候補を**純関数で安く絞ってから** ``classify_contradiction`` に渡す。

コスト上限が設計の中心:

- 候補抽出は LLM を呼ばない（同 project タグ・本文 Jaccard >= しきい値・数値の食い違い）
- LLM は ``max_pairs`` 件まで（既定 10）。**カーソルは持たない**ので、毎週とも
  「類似度上位 max_pairs」が選ばれ、独立と判定されたペアは候補に残り続ける
  （11 位以下の矛盾には届かない。LLM コストは週 max_pairs 回で一定）
- 矛盾と判定されたら古い側の ``valid_until`` / ``superseded_by`` を閉じる（削除はしない）
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable

    from nous.domain.memory.entities import Memory

# 英数は 2 文字以上、日本語は文字種が少ないので 2 文字以上をそのまま語として扱う。
_TOKEN_RE = re.compile(r"[0-9a-z]{2,}|[\u3040-\u30ff\u4e00-\u9fff]{2,}", re.IGNORECASE)
_NUMBER_RE = re.compile(r"\d+(?:\.\d+)?")
#: 日付は「食い違う数値」として数えない（"11-09 に計測" と "11-10 に計測" を矛盾扱いしない）。
_DATE_RE = re.compile(r"\d{4}[-/]\d{1,2}[-/]\d{1,2}|\d{1,2}:\d{2}")
#: 1 プロジェクトで総当たりに載せる上限（O(k^2) の暴発防止。ソート済みなので新しい方が残る）。
_GROUP_CAP = 200


def tokens(text: str) -> set[str]:
    """比較用の語集合（小文字化のみ。形態素解析は入れない）。"""
    return {t.lower() for t in _TOKEN_RE.findall(text or "")}


def jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def numbers(text: str) -> set[str]:
    return set(_NUMBER_RE.findall(_DATE_RE.sub(" ", text or "")))


def project_of(memory: Any) -> str | None:
    """``project:<slug>`` タグの slug（無ければ None）。"""
    for tag in getattr(memory, "tags", ()) or ():
        if isinstance(tag, str) and tag.startswith("project:"):
            return tag.split(":", 1)[1]
    return None


def _still_open(memory: Any) -> bool:
    """まだ有効な記憶か（tombstone 済み・validity window が閉じたものは候補外）。

    ``archived`` は編纂の sources 消化で沈んだだけで内容は生きている。ここで除外すると
    新しい側は編纂直後に必ず archived になるため、実データでは 1 ペアも拾えなくなる。
    """
    if getattr(memory, "lifecycle_status", "active") == "tombstoned":
        return False
    return getattr(memory, "valid_until", None) is None


def _stamp(value: Any) -> datetime:
    """時刻を UTC の aware datetime に正規化する（offset 混在でも辞書順が時系列になる）。"""
    if isinstance(value, datetime):
        return value.astimezone(UTC) if value.tzinfo else value.replace(tzinfo=UTC)
    try:
        parsed = datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return datetime.min.replace(tzinfo=UTC)
    return parsed.astimezone(UTC) if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _order_key(memory: Any) -> tuple[datetime, str]:
    """（UTC に正規化した時刻, key）。時刻は秒精度で同着になり得るので key で決定的にする。"""
    stamp = datetime.min.replace(tzinfo=UTC)
    for attr in ("valid_from", "created_at", "updated_at"):
        value = getattr(memory, attr, None)
        if value:
            stamp = _stamp(value)
            break
    return (stamp, str(getattr(memory, "key", "")))


def find_candidate_pairs(
    memories: list[Memory],
    *,
    min_jaccard: float = 0.5,
    limit: int = 50,
) -> list[tuple[Memory, Memory, float]]:
    """（新しい記憶, 古い記憶, 類似度）の候補。**LLM は呼ばない**。

    数値が片側にでもあり、かつ食い違う場合だけ候補にする（「30 分」と「1 時間」のような
    数値の書き換えは、文体が似ていても内容が別物になりやすいため）。

    類似度の降順で返す。``max_pairs`` で切る側（``sweep``）が「似ている順」に
    処理するので、``limit`` を広げた分だけ次回に回る候補の質が上がる。
    """
    groups: dict[str, list[Memory]] = {}
    for m in memories:
        if not _still_open(m):
            continue
        project = project_of(m)
        if project:
            groups.setdefault(project, []).append(m)

    pairs: list[tuple[Memory, Memory, float]] = []
    for group in groups.values():
        group.sort(key=_order_key, reverse=True)
        # 総当たりは O(k^2)。1 プロジェクトが数百件まで育っても秒単位に膨らまない上限。
        group = group[:_GROUP_CAP]
        # 計算は記憶ごとに 1 回だけ（内側ループで毎回再計算すると群が大きいとき効いてくる）。
        bag = {
            id(m): (
                numbers(getattr(m, "content", "") or ""),
                tokens(getattr(m, "content", "") or ""),
                getattr(m, "content", "") or "",
            )
            for m in group
        }
        for i, newer in enumerate(group):
            nums_a, tok_a, _ = bag[id(newer)]
            for older in group[i + 1 :]:
                nums_b, tok_b, _ = bag[id(older)]
                if not (nums_a ^ nums_b):
                    continue  # 数値が同じ（または両方に無い）→ 数値の食い違いではない
                similarity = jaccard(tok_a, tok_b)
                if similarity < min_jaccard:
                    continue
                pairs.append((newer, older, similarity))
    pairs.sort(key=lambda p: p[2], reverse=True)
    return pairs[: max(0, limit)]


async def sweep(
    pairs: list[tuple[Memory, Memory, float]],
    *,
    provider: Any,
    close: Callable[[str, str], None],
    max_pairs: int = 10,
) -> dict[str, Any]:
    """候補ペアを ``classify_contradiction`` にかけ、矛盾の古い側を閉じる。

    ``close(old_key, new_key)`` は呼び出し側の責務（DB 更新の詳細をここに持ち込まない）。
    """
    from nous.domain.memory.contradiction import ContradictionType, classify_contradiction

    checked = closed = failed = 0
    closed_keys: list[list[str]] = []
    for newer, older, _similarity in pairs[: max(0, max_pairs)]:
        checked += 1
        result = await classify_contradiction(
            getattr(newer, "content", "") or "",
            [
                {
                    "key": getattr(older, "key", ""),
                    "content": getattr(older, "content", "") or "",
                    "similarity": 1.0,
                }
            ],
            provider,
        )
        if result is None:
            # 判定不能（stream 失敗・JSON 破損・例外）。成功として数えない。
            failed += 1
            continue
        if result.type is ContradictionType.CONTRADICTORY:
            older_key = str(getattr(older, "key", ""))
            newer_key = str(getattr(newer, "key", ""))
            try:
                close(older_key, newer_key)
                closed += 1
                closed_keys.append([older_key, newer_key])
            except Exception:  # noqa: BLE001 — 1 件の失敗で掃除全体を止めない
                failed += 1
                continue
    return {
        "candidates": len(pairs),
        "checked": checked,
        "failed": failed,
        "closed": closed,
        "closed_keys": closed_keys,
        "capped": len(pairs) > max_pairs,
    }
