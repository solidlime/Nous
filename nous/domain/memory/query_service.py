from __future__ import annotations

import contextlib
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from nous.domain.memory.repository import MemoryRepository

from nous.domain.memory.entities import Memory, MemoryStrength
from nous.domain.shared.errors import DomainError, MemoryNotFoundError
from nous.domain.shared.result import Failure, Result, Success
from nous.domain.shared.time_utils import get_now

logger = logging.getLogger(__name__)

# brain_* 設定のデフォルト（Global Constraints / session_config.py:95-104 と同期）。
# lane1 が session_config に定義済みのキーを getattr で安全参照し、
# 未定義・読み込み失敗時はこのデフォルトへフォールバックする。
_BRAIN_DEFAULTS = {
    "brain_emotion_gain_k": 0.5,
    "brain_rif_suppression_rho": 0.05,
    "brain_link_separation_threshold": 0.75,
}


def resolve_brain_config(repo: object) -> dict[str, float]:
    """brain_* 設定の getattr 安全参照（失敗時はデフォルト）。

    repo の接続（``_conn``: data_dir + persona）から per-persona ChatConfig を
    解決する。テスト用フェイクや参照不能な repo ではデフォルト値を返す。
    """
    values = dict(_BRAIN_DEFAULTS)
    try:
        from nous.domain.chat_config import ChatConfigFileRepository

        conn = getattr(repo, "_conn", None)
        cfg = ChatConfigFileRepository(conn.data_dir).get(conn.persona)
        for key in values:
            values[key] = float(getattr(cfg, key, values[key]))
    except Exception:
        pass
    return values


class MemoryQueryService:
    """Handles read operations, statistics, and recall boosting."""

    def __init__(self, repo: MemoryRepository) -> None:
        self._repo = repo

    def get_memory(self, key: str) -> Result[Memory, DomainError]:
        """Retrieve a memory by key (excludes tombstoned memories)."""
        result = self._repo.find_by_key(key)
        if isinstance(result, Failure):
            return Failure(result.error)
        if result.value is None:
            return Failure(MemoryNotFoundError(f"Memory not found: {key}"))
        if getattr(result.value, "lifecycle_status", "active") == "tombstoned":
            return Failure(MemoryNotFoundError(f"Memory deleted: {key}"))
        return Success(result.value)

    def get_recent(self, limit: int = 10, offset: int = 0) -> Result[list[Memory], DomainError]:
        """Get most recent memories with optional pagination offset."""
        return self._repo.find_recent(limit=limit, offset=offset)

    def count_memories(self) -> Result[int, DomainError]:
        """Count total non-tombstoned memories."""
        return self._repo.count()

    def get_stats(self, top_n: int = 20) -> Result[dict, DomainError]:
        """Get memory statistics.

        Args:
            top_n: Maximum number of entries to return in tag/emotion distributions (default 20).
        """
        count_result = self._repo.count()
        if isinstance(count_result, Failure):
            return Failure(count_result.error)

        all_result = self._repo.find_all()
        if isinstance(all_result, Failure):
            return Failure(all_result.error)

        memories = all_result.value
        tag_dist: dict[str, int] = {}
        emotion_dist: dict[str, int] = {}
        daily_counts: dict[str, int] = {}
        for m in memories:
            for tag in m.tags:
                tag_dist[tag] = tag_dist.get(tag, 0) + 1
            emotion_dist[m.emotion] = emotion_dist.get(m.emotion, 0) + 1
            if m.created_at:
                day_key = (
                    m.created_at.strftime("%Y-%m-%d") if hasattr(m.created_at, "strftime") else str(m.created_at)[:10]
                )
                daily_counts[day_key] = daily_counts.get(day_key, 0) + 1

        total_count = count_result.value
        tagged_count = sum(1 for m in memories if m.tags)

        # Sort by count descending and truncate to top_n
        sorted_tags = sorted(tag_dist.items(), key=lambda x: -x[1])
        sorted_emotions = sorted(emotion_dist.items(), key=lambda x: -x[1])
        hidden_tags = max(0, len(sorted_tags) - top_n)
        hidden_emotions = max(0, len(sorted_emotions) - top_n)

        result: dict = {
            "total_count": total_count,
            "daily_counts": daily_counts,
            "tag_distribution": dict(sorted_tags[:top_n]),
            "emotion_distribution": dict(sorted_emotions[:top_n]),
            "tagged_ratio": tagged_count / total_count if total_count > 0 else None,
        }
        if hidden_tags:
            result["tag_distribution_note"] = f"+ {hidden_tags} more tags (use top_n to see more)"
        if hidden_emotions:
            result["emotion_distribution_note"] = f"+ {hidden_emotions} more emotion types"
        return Success(result)

    def boost_recall(self, key: str, emotion_intensity: float | None = None) -> Result[MemoryStrength, DomainError]:
        """Boost memory strength on recall.

        Args:
            key: Memory key to boost.
            emotion_intensity: Current emotion intensity used as proxy for valence
                (Bower 1981 emotion-congruent recall). Stored in strength.valence.
        """
        strength_result = self._repo.get_strength(key)
        if isinstance(strength_result, Failure):
            return Failure(strength_result.error)

        strength = strength_result.value
        if strength is None:
            strength = MemoryStrength(memory_key=key)

        # Store current emotion intensity as valence for emotion-congruent recall
        if emotion_intensity is not None:
            strength.valence = emotion_intensity

        # 感情情報なし（None）は従来動作（gain 1.5）を維持するためそのまま透過。
        # 明示的な感情強度のみ brain_emotion_gain_k による式が適用される。
        strength.boost_on_recall(
            emotion_intensity=emotion_intensity,
            gain_k=resolve_brain_config(self._repo)["brain_emotion_gain_k"],
        )
        strength.last_recall = get_now()

        save_result = self._repo.save_strength(strength)
        if isinstance(save_result, Failure):
            return Failure(save_result.error)
        try:
            from nous.domain.memory.wiring_events import emit as _wiring_emit
            from nous.domain.memory.wiring_events import repo_persona as _repo_persona

            _wiring_emit(
                "recall_boost",
                source=key,
                weight=float(strength.strength),
                meta={
                    "recall_count": strength.recall_count,
                    "stability": strength.stability,
                    "persona": _repo_persona(self._repo),
                },
            )
        except Exception:
            logger.debug("wiring emit failed for %s", key, exc_info=True)
        return Success(strength)

    def get_by_tags(self, tags: list[str], include_consumed: bool = False) -> Result[list[Memory], DomainError]:
        """Get memories that contain ALL specified tags."""
        return self._repo.get_by_tags(tags, include_consumed=include_consumed)

    def get_memory_history(self, key: str) -> Result[list[dict], DomainError]:
        """Get version history for a memory."""
        return self._repo.get_versions(key)

    def get_memory_index(self) -> Result[dict, DomainError]:
        """Get compressed memory index."""
        return self._repo.get_memory_index()

    def get_and_consume_one_shot(self, tag: str) -> Result[list[Memory], DomainError]:
        """Get the latest memory with the given tag and mark it as consumed.

        Used for one-shot state memories (e.g., physical_state, mental_state).
        Returns a list with the latest memory if found, else empty list.
        """
        result = self._repo.get_by_tags([tag])
        if isinstance(result, Failure) or not result.value:
            return Success([])
        memories = sorted(result.value, key=lambda m: m.created_at or get_now(), reverse=True)
        latest = memories[0]
        with contextlib.suppress(Exception):
            self._repo.consume_memory(latest.key)
        return Success([latest])
