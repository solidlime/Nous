"""ReflectionEngine: Generative Agentsスタイルの高次洞察生成。"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from nous.domain.search.engine import SearchQuery
from nous.infrastructure.llm.base import LLMMessage
from nous.infrastructure.llm.factory import get_provider
from nous.infrastructure.logging.structured import get_logger

if TYPE_CHECKING:
    from nous.application.use_cases import AppContext
    from nous.domain.chat_config import ChatConfig

logger = get_logger(__name__)

_REFLECTION_META_TAG = "_reflection_meta"
_REFLECTION_THRESHOLD_DEFAULT = 3.0
_REFLECTION_MIN_INTERVAL_HOURS_DEFAULT = 1.0

_REFLECTION_PROMPT = """\
以下は最近記録された記憶・事実のリストです。

{memories}

【指示】
これらの記憶から、最も重要な3つの高次洞察を導き出してください。
単なる事実の繰り返しではなく、パターン・傾向・本質的な理解を表す洞察にしてください。

【出力形式】
JSONのみ。コメント不要。
{{"insights": ["洞察1", "洞察2", "洞察3"]}}
"""


def _get_last_reflection_at(ctx: AppContext) -> datetime | None:
    """最後のリフレクション時刻をメタ記憶から取得する。"""
    result = ctx.memory_service.get_by_tags([_REFLECTION_META_TAG])
    if not result.is_ok or not result.value:
        return None
    for mem in result.value:
        if mem.content.startswith("last_reflection_at:"):
            ts_str = mem.content.split(":", 1)[1].strip()
            try:
                return datetime.fromisoformat(ts_str)
            except ValueError:
                pass
    return None


def _store_last_reflection_at(ctx: AppContext, ts: datetime) -> None:
    """リフレクション時刻をメタ記憶として保存する（古いものを削除して置き換え）。"""
    existing = ctx.memory_service.get_by_tags([_REFLECTION_META_TAG])
    if existing.is_ok and existing.value:
        for mem in existing.value:
            if mem.content.startswith("last_reflection_at:"):
                ctx.memory_service.delete_memory(mem.key)

    ctx.memory_service.create_memory(
        content=f"last_reflection_at: {ts.isoformat()}",
        importance=0.1,
        tags=[_REFLECTION_META_TAG],
        emotion="neutral",
    )


async def maybe_run_reflection(
    ctx: AppContext,
    config: ChatConfig,
    recent_importance_sum: float,
) -> list[str]:
    """リフレクションを必要に応じて実行する。

    Args:
        ctx: AppContext
        config: ChatConfig
        recent_importance_sum: 最近抽出されたファクトの importance 合計値

    Returns:
        生成された洞察文字列のリスト。リフレクション未実行時は空リスト。
    """
    threshold: float = getattr(config, "reflection_threshold", _REFLECTION_THRESHOLD_DEFAULT)
    min_interval_hours: float = getattr(config, "reflection_min_interval_hours", _REFLECTION_MIN_INTERVAL_HOURS_DEFAULT)

    if recent_importance_sum < threshold:
        return []

    # 最後のリフレクションから十分な時間が経過しているか確認
    now = datetime.now().astimezone()
    last_at = _get_last_reflection_at(ctx)
    if last_at is not None:
        elapsed = (now - last_at).total_seconds() / 3600.0
        if elapsed < min_interval_hours:
            logger.debug(
                "Reflection skipped: last=%.1fh ago, min_interval=%.1fh",
                elapsed,
                min_interval_hours,
            )
            return []

    api_key = config.get_effective_api_key()
    extract_model = config.extract_model.strip() or config.get_effective_model()
    if not api_key or not extract_model:
        return []

    # 最近24時間以内の記憶を最大20件取得
    cutoff = now - timedelta(hours=24)
    recent_result = ctx.memory_service.get_recent(limit=20)
    if not recent_result.is_ok or not recent_result.value:
        # フォールバック: スマートサーチで最近記憶を取得
        search_result = await ctx.search_engine.search(SearchQuery(text="記憶 事実 出来事", top_k=20, mode="hybrid"))
        memories = []
        if search_result.is_ok:
            for item in search_result.value:
                mem = item[0] if isinstance(item, tuple) else item
                memories.append(mem)
    else:
        memories = [m for m in recent_result.value if m.created_at >= cutoff] or recent_result.value[:10]

    if not memories:
        return []

    memory_lines = "\n".join(f"- [{m.importance:.1f}] {m.content[:120]}" for m in memories[:20])
    prompt = _REFLECTION_PROMPT.format(memories=memory_lines)

    try:
        provider = get_provider(config.provider, api_key, extract_model, config.get_effective_base_url())
    except Exception as e:
        logger.warning("ReflectionEngine: provider init failed: %s", e)
        return []

    from nous.infrastructure.llm.base import DoneEvent, ErrorEvent, TextDeltaEvent

    text = ""
    try:
        async for event in provider.stream(
            messages=[LLMMessage(role="user", content=prompt)],
            system="",
            tools=[],
            temperature=0.3,
            max_tokens=512,
        ):
            if isinstance(event, TextDeltaEvent):
                text += event.content
            elif isinstance(event, (DoneEvent, ErrorEvent)):
                break
    except Exception as e:
        logger.warning("ReflectionEngine: LLM call failed: %s", e)
        return []

    insights = _parse_insights(text)
    if not insights:
        return []

    for insight in insights:
        ctx.memory_service.create_memory(
            content=insight,
            importance=0.9,
            tags=["reflection"],
            emotion="neutral",
        )

    _store_last_reflection_at(ctx, now)
    logger.info("ReflectionEngine: stored %d insights for persona=%s", len(insights), ctx.persona)
    return insights


def _parse_insights(text: str) -> list[str]:
    """LLM出力から洞察リストをパースする。"""
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        text = "\n".join(lines[1:-1] if lines[-1].startswith("```") else lines[1:])
    try:
        result = json.loads(text)
        if isinstance(result, dict):
            insights = result.get("insights", [])
            return [s for s in insights if isinstance(s, str) and s.strip()]
    except Exception:
        pass
    return []
