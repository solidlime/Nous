"""記憶検索・チャンク作成 — related memory retrieval and formatting for chat context."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from nous.application.chat.pipeline.emotion_decay import _compute_recency_decay
from nous.domain.memory.recall_annotator import RecallAnnotator
from nous.domain.search.engine import SearchQuery
from nous.domain.shared.time_utils import get_now
from nous.infrastructure.logging.structured import get_logger

if TYPE_CHECKING:
    from nous.application.use_cases import AppContext
    from nous.domain.chat_config import ChatConfig

logger = get_logger(__name__)


def _format_memory_hint(ann) -> str:
    """アノテーションを自然な日本語のヒント文字列に変換。"""
    cert_map = {"confident": "確か", "tentative": "たしか", "vague": "うろ覚え", "forgotten": ""}
    cert = cert_map.get(ann.certainty, "")

    time_map = {
        "recent": "最近",
        "days_7": "この前",
        "days_30": "こないだ",
        "days_90": "前に",
        "years": "昔",
        "long_ago": "ずっと前",
    }
    time_hint = time_map.get(ann.time_hint, "")

    source_hint = ""
    if ann.source_hint == "llm_inferred":
        source_hint = "推測"
    elif ann.source_hint == "reflected":
        source_hint = "洞察"

    parts = [p for p in [cert, time_hint, source_hint] if p]
    if not parts:
        return ""
    return "（" + "・".join(parts) + "）"


async def _search_memories(
    ctx: AppContext,
    user_message: str,
    last_assistant: str | None,
    config: ChatConfig,
    top_k: int = 8,
) -> tuple[str, dict, list]:
    """2クエリ並行検索 + 複合スコアリングマージ。

    Returns:
        (formatted_str, debug_info, memories_list)
    """
    recency_w: float = getattr(config, "retrieval_recency_weight", 0.3)
    importance_w: float = getattr(config, "retrieval_importance_weight", 0.3)
    relevance_w: float = getattr(config, "retrieval_relevance_weight", 0.4)
    # リフレクション記憶の降格係数 (主題不定の抽象文が通常検索に混入するのを防ぐ)。
    # 1.0 で無効。
    reflection_penalty = float(getattr(config, "reflection_retrieval_penalty", 0.5))

    queries = [user_message]
    if last_assistant:
        queries.append(last_assistant[:200])

    async def _run(q: str) -> list:
        try:
            result = await ctx.search_engine.search(
                SearchQuery(text=q, top_k=top_k, valid_at=get_now(), apply_rif=True)
            )
            return result.value if result.is_ok else []
        except Exception as e:
            logger.warning("search_memory failed (query=%s): %s", q[:40], e)
            return []

    results = await asyncio.gather(*[_run(q) for q in queries])

    # Collect unique candidates by content
    seen: set[str] = set()
    mem_by_content: dict[str, object] = {}
    for result_list in results:
        for item in result_list:
            if isinstance(item, tuple):
                mem = item[0]
            elif hasattr(item, "memory"):
                mem = item.memory
            else:
                mem = item
            content = getattr(mem, "content", str(mem))
            if content not in seen:
                seen.add(content)
                mem_by_content[content] = mem

    # relevance = 絶対コサイン類似度 (旧RRFは新鮮記憶支配を招くため廃止)。
    # 2クエリ間は max で統合 (コサイン値域 [0,1] を超えない)。
    # 候補過多時は rec+imp 部分で事前ランキングし上位のみエンコード。
    # 埋め込み取得不能時は relevance=0.0 で継続 (fail-open)。
    pre: list[tuple[float, str, object]] = []
    for content, mem in mem_by_content.items():
        importance = float(getattr(mem, "importance", 0.5))
        created_at = getattr(mem, "created_at", None)
        recency = _compute_recency_decay(created_at)
        pre.append((recency_w * recency + importance_w * importance, content, mem))
    if len(pre) > 30:
        pre.sort(key=lambda x: x[0], reverse=True)
        pre = pre[:30]

    cos_scores: dict[str, float] = {content: 0.0 for _, content, _ in pre}
    embedding = getattr(ctx, "_embedding", None)
    if embedding is not None and pre:
        try:
            import numpy as np

            qvecs = [embedding.encode(q, is_query=True) for q in queries]
            for _, content, _ in pre:
                d = embedding.encode(content)
                cos_scores[content] = max(float(np.dot(qv, d)) for qv in qvecs)
        except Exception as e:
            logger.debug("memory relevance cosine failed: %s", e)

    # Compute composite score for each unique memory
    scored: list[tuple[float, object]] = []
    for base, content, mem in pre:
        relevance = cos_scores[content]
        composite = base + relevance_w * relevance
        if "reflection" in (getattr(mem, "tags", None) or []):
            composite *= reflection_penalty
        scored.append((composite, mem))

    scored.sort(key=lambda x: x[0], reverse=True)
    top = scored[:top_k]

    if not top:
        return "", {"queries": queries, "results": []}, []

    cos_values = list(cos_scores.values())
    logger.debug(
        "cosine relevance: min=%.4f, max=%.4f, top_%d_composite_range=[%.4f, %.4f]",
        min(cos_values),
        max(cos_values),
        len(top),
        top[-1][0],
        top[0][0],
    )

    annotator = RecallAnnotator()
    now = datetime.now(tz=UTC)
    lines: list[str] = []
    for _, m in top:
        created_at = getattr(m, "created_at", None)
        if created_at is not None:
            if created_at.tzinfo is None:
                created_at = created_at.replace(tzinfo=UTC)
            age_days = max(0.0, (now - created_at).total_seconds() / 86400.0)
        else:
            age_days = 30.0  # default fallback
        ann = annotator.annotate(
            confidence=float(getattr(m, "confidence", 1.0)),
            age_days=age_days,
            source_type=str(getattr(m, "source_type", "user_stated")),
            kind=str(getattr(m, "kind", "semantic")),
        )
        if not ann.should_mention:
            continue
        hint = _format_memory_hint(ann)
        content = getattr(m, "content", str(m))
        if hint:
            lines.append(f"{hint} {content}")
        else:
            lines.append(content)
    memories_list: list[object] = [m for _, m in top]
    debug_results = [
        {
            "content": getattr(m, "content", str(m)),
            "importance": round(float(getattr(m, "importance", 0.5)), 2),
            "score": round(score, 4),
            "cosine": round(cos_scores.get(getattr(m, "content", str(m)), 0.0), 4),
        }
        for score, m in top
    ]
    return "\n".join(lines), {"queries": queries, "results": debug_results}, memories_list


async def _search_keyword_fast(
    ctx: AppContext,
    user_message: str,
    last_assistant: str | None,
    top_k: int = 5,
) -> list[dict]:
    """Fast keyword-only memory search for progressive disclosure.

    Returns a list of dicts suitable for MemoryActivitySSE.retrieved field:
    [{"content": str, "score": float, "importance": float}, ...]
    """
    queries = [user_message]
    if last_assistant:
        queries.append(last_assistant[:200])

    async def _run(q: str) -> list:
        try:
            result = await ctx.search_engine.search(SearchQuery(text=q, top_k=top_k, mode="keyword"))
            return result.value if result.is_ok else []
        except Exception:
            return []

    results = await asyncio.gather(*[_run(q) for q in queries])

    # Deduplicate by content, keep first occurrence
    seen: set[str] = set()
    items: list[dict] = []
    for result_list in results:
        for item in result_list:
            if isinstance(item, tuple):
                mem = item[0]
            elif hasattr(item, "memory"):
                mem = item.memory
            else:
                mem = item
            content = getattr(mem, "content", str(mem))
            if content not in seen:
                seen.add(content)
                items.append(
                    {
                        "content": content[:200],
                        "score": 1.0,
                        "importance": float(getattr(mem, "importance", 0.5)),
                    }
                )
                if len(items) >= top_k:
                    break
        if len(items) >= top_k:
            break
    return items[:top_k]


async def _search_episodes(
    ctx: AppContext,
    query: str,
    top_k: int = 3,
) -> list[dict]:
    """Fallback: search Episode Memory (session_events) when Note Memory is insufficient.

    Returns list of dicts with 'topic', 'summary', 'content' keys.
    """
    session_event_repo = getattr(ctx, "_session_event_repo", None)
    if session_event_repo is None:
        return []

    try:
        from nous.domain.search.engine import SearchQuery

        # Use semantic search via search_engine for relevance if available
        if hasattr(ctx, "search_engine") and ctx.search_engine is not None:
            search_result = await ctx.search_engine.search(
                SearchQuery(text=query, top_k=top_k, mode="semantic", apply_rif=True)
            )
            if search_result.is_ok and search_result.value:
                episodes = []
                for hit in search_result.value:
                    mem = hit.memory if hasattr(hit, "memory") else hit
                    content = getattr(mem, "content", str(mem))[:200]
                    tags = getattr(mem, "tags", [])
                    source = getattr(mem, "source_context", "")
                    episodes.append(
                        {
                            "topic": tags[0] if tags else "episode",
                            "summary": content[:100],
                            "content": content,
                            "episode_id": source,
                        }
                    )
                return episodes

        # Fallback to keyword search on session event summaries
        events = session_event_repo.get_by_persona(ctx.persona, limit=top_k * 5)
        # Simple keyword scoring
        query_lower = query.lower()
        scored = []
        for ev in events:
            summary = (ev.summary or "").lower()
            detail = (ev.detail or "").lower()
            # Count query term occurrences
            score = summary.count(query_lower) * 2 + detail.count(query_lower)
            if score > 0:
                scored.append(
                    (
                        score,
                        {
                            "topic": ev.event_type or "session_event",
                            "summary": (ev.summary or "")[:100],
                            "content": (ev.detail or ev.summary or "")[:200],
                            "episode_id": str(ev.id or ""),
                        },
                    )
                )
        scored.sort(key=lambda x: -x[0])
        return [s[1] for s in scored[:top_k]]
    except Exception:
        logger.debug("_search_episodes failed (best-effort)", exc_info=True)
        return []
