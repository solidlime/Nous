"""PatternDetector: 複数記憶から繰り返しパターンを抽出し抽象化する。"""

from __future__ import annotations

import json
from datetime import datetime
from typing import TYPE_CHECKING

from nous.infrastructure.llm.base import LLMMessage
from nous.infrastructure.llm.factory import get_provider
from nous.infrastructure.logging.structured import get_logger

if TYPE_CHECKING:
    from nous.application.use_cases import AppContext
    from nous.domain.chat_config import ChatConfig

logger = get_logger(__name__)

_MENTAL_MODEL_META_TAG = "_mental_model_meta"
_MENTAL_MODEL_TAGS = ["mental_model", "abstracted"]
_MENTAL_MODEL_IMPORTANCE = 0.85
_TYPE_TAGS = ["decision", "preference", "milestone", "problem", "emotional"]

_PROMPT_TEMPLATE = """\
以下は「{type_tag}」タイプの記憶群です：

{memories}

【指示】
これらの記憶から、繰り返し現れるパターン・習慣・傾向を2〜3個の抽象化されたモデルとして抽出してください。
例：「ユーザーは朝コーヒーを飲む習慣がある」「ユーザーはReact hooksの理解に苦労する傾向がある」

【出力形式】
JSONのみ。コメント不要。
各モデルは主語を明示すること（ユーザーの習慣・傾向→「ユーザー：」、{persona}自身の振る舞い・傾向→そのキャラクター自身の一人称＋「：」）。
{{"models": ["モデル1", "モデル2", "モデル3"]}}
"""


def _get_last_abstraction_at(ctx: AppContext, type_tag: str) -> datetime | None:
    """メタ記憶から指定タイプの最終抽象化時刻を取得する。"""
    result = ctx.memory_service.get_by_tags([_MENTAL_MODEL_META_TAG])
    if not result.is_ok or not result.value:
        return None
    prefix = f"last_{type_tag}_abstraction:"
    for mem in result.value:
        if mem.content.startswith(prefix):
            ts_str = mem.content.split(":", 1)[1].strip()
            try:
                return datetime.fromisoformat(ts_str)
            except ValueError as _e:
                logger.debug("PatternDetector: failed to parse timestamp '%s': %s", ts_str, _e)
    return None


async def _store_last_abstraction_at(ctx: AppContext, type_tag: str, ts: datetime) -> None:
    """指定タイプの抽象化時刻をメタ記憶として保存する（古いものを削除して置き換え）。"""
    prefix = f"last_{type_tag}_abstraction:"
    existing = ctx.memory_service.get_by_tags([_MENTAL_MODEL_META_TAG])
    if existing.is_ok and existing.value:
        for mem in existing.value:
            if mem.content.startswith(prefix):
                ctx.memory_service.delete_memory(mem.key)

    await ctx.memory_service.create_memory(
        content=f"{prefix} {ts.isoformat()}",
        importance=0.1,
        tags=[_MENTAL_MODEL_META_TAG],
        emotion="neutral",
    )


def _has_new_memories_since(ctx: AppContext, type_tag: str, memories: list) -> bool:
    """指定タイプの記憶群に、前回の抽象化以降に追加されたものが含まれているかを確認する。"""
    last_at = _get_last_abstraction_at(ctx, type_tag)
    if last_at is None:
        # 初回: 抽象化したことがないので処理対象
        return True
    return any(hasattr(mem, "created_at") and mem.created_at and mem.created_at > last_at for mem in memories)


def _parse_models(text: str) -> list[str]:
    """LLM出力からモデルリストをパースする。

    JSONの他、マークダウンのコードブロックで囲まれた形式にも対応。
    """
    text = text.strip()
    if not text:
        return []
    if text.startswith("```"):
        lines = text.splitlines()
        text = "\n".join(lines[1:-1] if lines[-1].startswith("```") else lines[1:])
    try:
        result = json.loads(text)
        if isinstance(result, dict):
            models = result.get("models", [])
            return [s for s in models if isinstance(s, str) and s.strip()]
    except Exception as _e:
        logger.debug("PatternDetector: failed to parse models from LLM output: %s", _e)
    return []


async def maybe_run_mental_model(
    ctx: AppContext,
    config: ChatConfig,
    min_samples: int = 3,
) -> list[str]:
    """Check if any type-tagged memory group has accumulated >= min_samples.
    If so, call LLM to abstract patterns and store as mental model memories.

    Args:
        ctx: AppContext
        config: ChatConfig (for LLM settings)
        min_samples: Minimum memories of same type to trigger abstraction

    Returns:
        List of generated mental model strings.
    """
    # Check if mental model abstraction is enabled
    enabled = getattr(config, "mental_model_enabled", True)
    if not enabled:
        logger.debug("Mental model abstraction disabled via config")
        return []

    # Check LLM availability
    api_key = config.get_effective_api_key()
    extract_model = config.extract_model.strip() or config.get_effective_model()
    if not api_key or not extract_model:
        logger.debug("Mental model skipped: LLM not configured")
        return []

    all_models: list[str] = []

    for type_tag in _TYPE_TAGS:
        try:
            result = ctx.memory_service.get_by_tags([type_tag])
            if not result.is_ok or not result.value:
                continue

            memories = result.value

            # Check if we have enough memories of this type
            if len(memories) < min_samples:
                logger.debug(
                    "Mental model: %s has %d memories (< %d), skipping",
                    type_tag,
                    len(memories),
                    min_samples,
                )
                continue

            # Check if there are new memories since last abstraction
            if not _has_new_memories_since(ctx, type_tag, memories):
                logger.debug("Mental model: %s has no new memories since last abstraction", type_tag)
                continue

            # Collect recent N memories (up to 20 for LLM context)
            recent = sorted(memories, key=lambda m: m.created_at, reverse=True)[:20]
            memory_lines = "\n".join(f"- [{m.importance:.1f}] {m.content[:200]}" for m in recent)

            prompt = _PROMPT_TEMPLATE.format(type_tag=type_tag, memories=memory_lines, persona=ctx.persona)

            try:
                provider = get_provider(config.provider, api_key, extract_model, config.get_effective_base_url())
            except Exception as e:
                logger.warning("PatternDetector: provider init failed for %s: %s", type_tag, e)
                continue

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
                logger.warning("PatternDetector: LLM call failed for %s: %s", type_tag, e)
                continue

            models = _parse_models(text)
            if not models:
                logger.debug("PatternDetector: no models parsed for %s", type_tag)
                continue

            # Store each model as a memory
            _source_keys = [m.key for m in recent]
            for model_content in models:
                await ctx.memory_service.create_memory(
                    content=model_content,
                    importance=_MENTAL_MODEL_IMPORTANCE,
                    tags=list(_MENTAL_MODEL_TAGS),
                    emotion="neutral",
                    source_context=f"mental_model:{type_tag}",
                )

            # Update last abstraction time for this type tag
            await _store_last_abstraction_at(ctx, type_tag, datetime.now().astimezone())

            all_models.extend(models)
            logger.info(
                "PatternDetector: stored %d mental models for type=%s persona=%s",
                len(models),
                type_tag,
                ctx.persona,
            )

        except Exception as e:
            logger.warning("PatternDetector: error processing type %s: %s", type_tag, e)
            continue

    return all_models
