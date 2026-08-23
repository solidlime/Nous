"""PrepareStep: ターン開始時の準備（感情減衰 + コンテキスト取得 + 記憶検索）。"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from nous.application.chat.pipeline.context_loader import (  # noqa: F401
    _GAP_INSTRUCTIONS,
    _SUSPICIOUS_RANGES,
    _TIME_OF_DAY,
    _build_context_section,
    _build_relationship_context,
    _build_time_context,
    _classify_gap,
    _is_suspicious_cp,
)

# Re-export all public symbols from the split modules.
# Existing callers (including tests) using
#   from nous.application.chat.pipeline.prepare import X
# continue to work unchanged.
from nous.application.chat.pipeline.emotion_decay import (  # noqa: F401
    _RECENCY_LAMBDA,
    _compute_recency_decay,
)
from nous.application.chat.pipeline.memory_retriever import (  # noqa: F401
    _format_memory_hint,
    _search_episodes,
    _search_keyword_fast,
    _search_memories,
)
from nous.domain.shared.time_utils import relative_time_str
from nous.infrastructure.logging.structured import get_logger

if TYPE_CHECKING:
    from nous.application.chat.pipeline.context import ChatTurnContext
    from nous.application.chat.session_store import TreeSessionWindow
    from nous.application.use_cases import AppContext
    from nous.domain.chat_config import ChatConfig

logger = get_logger(__name__)


def _build_recall_query(session, current_user_message: str) -> str:
    """§2: 直近ユーザー発言 最大3件の結合（合計800字上限、超過時は新しい方から採用）。"""
    # TreeSessionWindow._messages は list[dict]（role/content キー）なので辞書アクセス必須
    history = [
        str(m.get("content"))
        for m in session._messages
        if isinstance(m, dict) and m.get("role") == "user" and m.get("content")
    ]
    if not history or history[-1] != current_user_message:
        history.append(current_user_message)
    combined = "\n".join(history[-3:])
    return combined[-800:] if len(combined) > 800 else combined


def _build_digest(ctx, config) -> str:
    """§1 Recency digest: 直近記憶を updated_at 降順で N 件（クエリ一致不要・consumed 済みも含む）。"""
    n = int(getattr(config, "memory_digest_count", 5) or 0)
    if n <= 0:
        return ""
    try:
        result = ctx.memory_service.get_recent(limit=n)
        memories = result.value if result.is_ok else []
        if not memories:
            return ""
        lines = ["[最近のできごと — 他クライアントとの活動を含む]"]
        for m in memories:
            content = (getattr(m, "content", "") or "").strip()[:200]
            if not content:
                continue
            updated_at = getattr(m, "updated_at", None)
            ts = relative_time_str(updated_at) if updated_at else ""
            ts_str = f" ({ts})" if ts else ""
            lines.append(f"- {ts_str}{content}")
        return "\n".join(lines) if len(lines) > 1 else ""
    except Exception:
        logger.warning("PrepareStep: digest build failed", exc_info=True)
        return ""


class PrepareStep:
    """ターン開始時の準備ステップ。"""

    async def run(
        self,
        ctx: AppContext,
        session: TreeSessionWindow,
        turn_ctx: ChatTurnContext,
        config: ChatConfig | None = None,
    ) -> None:
        """
        1. 前ターンのMemoryLLMを待機
        2. EmotionDecay適用
        3. get_context() + 記憶検索を並行実行
        4. ChatTurnContextに結果を格納
        """
        from nous.domain.chat_config import ChatConfig as _ChatConfig

        if config is None:
            config = _ChatConfig()

        # 1. 前ターンのMemoryLLMタスクを待つ
        if session.pending_memory_task is not None:
            try:
                await session.pending_memory_task
            except Exception as e:
                logger.warning("PrepareStep: pending MemoryLLM task error: %s", e)
            finally:
                session.pending_memory_task = None

        persona = ctx.persona

        # 2. PersonaState取得 + EmotionDecay適用 + BodyDecay適用
        state_result = ctx.persona_service.get_context(persona)
        if state_result.is_ok:
            state = state_result.value
            from nous.api.mcp._tools_helpers import _apply_body_decay, _apply_emotion_decay, _apply_relationship_decay

            state, decay_note = await _apply_emotion_decay(ctx, persona, state)
            state = await _apply_body_decay(ctx, persona, state)
            relationship_note = await _apply_relationship_decay(ctx, persona, state)
            if relationship_note:
                decay_note = f"{decay_note}\n{relationship_note}" if decay_note else relationship_note

            # Author's Note: propagate to turn_ctx for PromptBuildStep
            turn_ctx.author_note = getattr(state, "author_note", None)
            turn_ctx.author_note_frequency = getattr(state, "author_note_frequency", "always")

            # state_raw: シリアライズ可能な dict
            turn_ctx.state_raw = (
                {
                    k: str(v) if not isinstance(v, (str, int, float, bool, list, dict, type(None))) else v
                    for k, v in vars(state).items()
                }
                if hasattr(state, "__dict__")
                else {}
            )

            # TIME_CONTEXT ブロック（システムプロンプト先頭注入用）
            if getattr(config, "show_message_timestamps", False):
                turn_ctx.time_context = _build_time_context(state)
            else:
                turn_ctx.time_context = ""

            # context_section 構築
            context_task = asyncio.create_task(
                _build_context_section(
                    ctx, state, turn_ctx, compress_mode=config.context_compression_mode, decay_note=decay_note
                )
            )
            # Progressive disclosure: only preload N memories; LLM searches for more if needed
            preload_count = getattr(config, "memory_preload_count", 5)
            memory_task = asyncio.create_task(
                _search_memories(
                    ctx,
                    _build_recall_query(session, turn_ctx.user_message),
                    None,
                    config,
                    top_k=max(preload_count, 1) if preload_count > 0 else 100,
                )
            )
            results = await asyncio.gather(context_task, memory_task, return_exceptions=True)
            context_section = results[0]
            memory_result = results[1]

            # §1 Recency digest（同期 API のため gather 後に構築）
            turn_ctx.recency_digest = _build_digest(ctx, config)

            if isinstance(context_section, Exception):
                logger.warning("PrepareStep: context_section build failed: %s", context_section)
                context_section = ""
            if isinstance(memory_result, Exception):
                logger.warning("PrepareStep: memory search failed: %s", memory_result)
                turn_ctx.related_memories = ""
                turn_ctx.memory_debug = {}
                turn_ctx.memories_raw = []
                turn_ctx.memories_objects = []
            else:
                turn_ctx.related_memories, debug, memories_list = memory_result
                turn_ctx.memory_debug = debug
                turn_ctx.memories_raw = debug.get("results", [])
                turn_ctx.memories_objects = memories_list

            turn_ctx.context_section = context_section

            # HiMem 2-tier: Episode Memory fallback when Note Memory insufficient
            if config.episode_search_enabled:
                retrieved_count = len(turn_ctx.memories_raw)
                if preload_count == 0 or retrieved_count < preload_count:
                    try:
                        ep_results = await _search_episodes(ctx, turn_ctx.user_message, top_k=3)
                        if ep_results:
                            ep_lines = ["\n[Recent Episodes]"]
                            for ep in ep_results:
                                ep_lines.append(f"  [{ep.get('topic', 'episode')}] {ep.get('summary', '')[:80]}")
                            turn_ctx.related_memories += "\n" + "\n".join(ep_lines)
                    except Exception:
                        logger.debug("PrepareStep: episode search fallback failed", exc_info=True)
        else:
            logger.warning("PrepareStep: get_context failed: %s", state_result.error)
            # contextなしで継続
            try:
                preload_count = getattr(config, "memory_preload_count", 5)
                turn_ctx.related_memories, debug, memories_list = await _search_memories(
                    ctx,
                    _build_recall_query(session, turn_ctx.user_message),
                    None,
                    config,
                    top_k=max(preload_count, 1) if preload_count > 0 else 100,
                )
                turn_ctx.memory_debug = debug
                turn_ctx.memories_raw = debug.get("results", [])
                turn_ctx.memories_objects = memories_list
            except Exception as e:
                logger.warning("PrepareStep: memory search failed: %s", e)
