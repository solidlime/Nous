"""pi hook 経由の記憶抽出 pipeline（turn.completed → 記憶化）。

chat pipeline を通らない pi 対話ターンを nous 側で記憶化する経路。
`run_memory_llm` は ChatConfig を要求するため使わず、`MemoryLLM.process` を
`LLMConfig` 由来の薄い設定アダプタ経由で呼ぶ（既存 pipeline 無改変）。
プロンプト（`_CONTEXT_LLM_PROMPT`）・JSON パース・正規化ヘルパは memory_extractor を再利用する。
"""

from __future__ import annotations

import contextlib
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any, cast

from nous.application.chat.memory_extractor import (
    DRIFT_VALID_DAYS,
    MemoryLLM,
    _body_delta_state,
    _build_memory_llm_context,
    _context_update_skips,
    _normalize_drift_fact,
    normalize_importance,
    normalize_tags,
)
from nous.domain.language import FALLBACK_LANGUAGE, SUPPORTED_LANGUAGES, detect_language
from nous.domain.memory.session_event import SessionEvent
from nous.domain.search.engine import SearchQuery
from nous.domain.shared.result import Success
from nous.domain.shared.time_utils import get_now
from nous.domain.value_objects import ensure_project_tag, normalize_emotion, normalize_project_slug
from nous.domain.value_objects import normalize_importance as _clamp
from nous.infrastructure.logging.structured import get_logger
from nous.infrastructure.sqlite.session_event_repo import SessionEventRepository

if TYPE_CHECKING:
    from nous.application.use_cases import AppContext
    from nous.config.settings import Settings
    from nous.domain.chat_config import ChatConfig

logger = get_logger(__name__)

#: hook pipeline が拾う event 型（session.stopped は _summarize_session_end 専用）。
HOOK_EXTRACTION_EVENT_TYPES = frozenset({"turn.completed"})

#: facts の重複判定しきい値（chat pipeline の run_memory_llm と同一規約）。
DUPLICATE_SCORE_THRESHOLD = 0.85

#: 抽出 LLM の max_tokens。
#: reasoning を前提としない旧 ChatConfig 既定値（512)では、reasoning LLM が
#: reasoning token を max_tokens に含めて消費するため content が空になる
#: reasoning 系モデルは reasoning tokens も max_tokens に含むため余裕を取る。
#: hook 抽出は短文なので 8192 で十分。
HOOK_EXTRACT_MAX_TOKENS = 8192

FAILED_EVENT_TYPE = "hook_extraction.failed"


@dataclass(frozen=True)
class _HookLLMConfig:
    """`MemoryLLM.process` が ChatConfig に要求する最小面だけを写したアダプタ。"""

    provider: str
    model: str
    api_key: str
    base_url: str
    language: str = FALLBACK_LANGUAGE
    extract_model: str = ""
    extract_max_tokens: int = HOOK_EXTRACT_MAX_TOKENS

    def get_effective_model(self) -> str:
        return self.model

    def get_effective_api_key(self) -> str:
        return self.api_key

    def get_effective_base_url(self) -> str:
        return self.base_url


def _llm_config(settings: Settings, user_text: str) -> _HookLLMConfig:
    """LLMConfig から抽出 LLM 設定を組み立てる（既存の鍵解決経路を流用）。"""
    enrich = settings.memory_enrichment
    detected = detect_language(user_text) or ""
    return _HookLLMConfig(
        provider=enrich.provider,
        model=enrich.model,
        api_key=enrich.get_effective_api_key(settings),
        base_url=enrich.base_url,
        language=detected if detected in SUPPORTED_LANGUAGES else FALLBACK_LANGUAGE,
    )


def _project_tag(event: dict[str, Any]) -> str | None:
    """turn.completed detail の project slug を canonical slug に正規化（不備なら None）。

    正規化は normalize_project_slug に委譲（canonical 規約は write_service と共有）。
    AGENTS.md 由来の大文字・_ 混在 slug も lowercase 化で受理。"""
    raw = str(cast("dict", event.get("detail") or {}).get("project") or "").strip()
    return normalize_project_slug(raw) or None


def _with_project(tags: list[str], project_tag: str | None) -> list[str]:
    """ensure_project_tag への薄いラッパ（既存 project:* は尊重、新 list を返す）。"""
    if not project_tag:
        return tags
    return ensure_project_tag(tags, project_tag) or tags


async def run_hook_extraction(ctx: AppContext, persona: str, event: dict[str, Any], session_id: str) -> None:
    """turn.completed 1 件を抽出・保存する。fire-and-forget 前提で例外を外へ出さない。

    LLM 失敗時は no-op（logger.warning）＋ session_events に
    `hook_extraction.failed` を 1 行残す（dashboard 可視化用）。
    """
    raw_detail = event.get("detail")
    detail: dict[str, Any] = raw_detail if isinstance(raw_detail, dict) else {}
    user_text = str(detail.get("user_text") or "")
    assistant_text = str(detail.get("assistant_text") or "")
    if not user_text and not assistant_text:
        return

    try:
        context_str, commitments_str, inventory_str = await _build_memory_llm_context(ctx)
        result = await MemoryLLM().process(
            cast("ChatConfig", _llm_config(ctx.settings, user_text)),
            user_message=user_text,
            assistant_response=assistant_text,
            context=context_str,
            commitments=commitments_str,
            inventory=inventory_str,
            persona_name=ctx.persona or persona,
            mode="context",
        )
        if not result:
            logger.warning("hook_extraction: empty LLM result persona=%s", persona)
            _record_failure(ctx, persona, session_id, "empty result")
            return

        n_facts, n_goals, n_promises = await _apply_result(ctx, persona, result, _project_tag(event))
        if result.get("context_update"):
            _apply_context_update(ctx, persona, result["context_update"], detail.get("tool_calls_log") or [])
        logger.info(
            "hook_extraction: %d facts / %d goals / %d promises saved persona=%s",
            n_facts,
            n_goals,
            n_promises,
            persona,
        )
    except Exception as e:
        logger.warning("hook_extraction failed: %s", e)
        _record_failure(ctx, persona, session_id, str(e))


async def _apply_result(
    ctx: AppContext, persona: str, result: dict, project_tag: str | None = None
) -> tuple[int, int, int]:
    """LLM 抽出結果を保存し、(facts, goals, promises) の保存件数を返す。"""
    n_facts = 0
    for fact in result.get("facts") or []:
        content = str(fact.get("content") or "").strip()
        if not content:
            continue
        _normalize_drift_fact(fact, "")
        tags = normalize_tags(fact.get("tags"))
        valid_until = get_now() + timedelta(days=DRIFT_VALID_DAYS) if "character_drift" in tags else None
        if await _create(
            ctx,
            persona,
            content,
            importance=normalize_importance(fact.get("importance")),
            tags=_with_project(tags, project_tag),
            emotion=str(fact.get("emotion") or "neutral"),
            valid_until=valid_until,
        ):
            n_facts += 1

    n_goals = 0
    for goal in result.get("goals") or []:
        if await _apply_commitment(
            ctx,
            persona,
            goal,
            active_tags=_with_project(["goal", "active"], project_tag),
            achieve_tags=["goal", "achieved"],
            cancel_tags=["goal", "cancelled"],
            importance=0.75,
            project_tag=project_tag,
        ):
            n_goals += 1

    n_promises = 0
    for promise in result.get("promises") or []:
        if await _apply_commitment(
            ctx,
            persona,
            promise,
            active_tags=["goal", "active", "interpersonal"],
            achieve_tags=["goal", "achieved", "archived", "interpersonal"],
            cancel_tags=["goal", "cancelled", "archived", "interpersonal"],
            importance=0.8,
            project_tag=project_tag,
        ):
            n_promises += 1

    return n_facts, n_goals, n_promises


async def _apply_commitment(
    ctx: AppContext,
    persona: str,
    item: dict,
    *,
    active_tags: list[str],
    achieve_tags: list[str],
    cancel_tags: list[str],
    importance: float,
    project_tag: str | None = None,
) -> bool:
    """goals / promises 1 件を active リスト（LLM が memory_key で参照）と照合して反映する。"""
    action = str(item.get("action") or "create")
    content = str(item.get("content") or "").strip()
    memory_key = str(item.get("memory_key") or "")
    if action in ("achieve", "fulfill") and memory_key:
        return _set_tags(ctx, memory_key, achieve_tags)
    if action == "cancel" and memory_key:
        return _set_tags(ctx, memory_key, cancel_tags)
    if action == "create" and content:
        return await _create(
            ctx,
            persona,
            content,
            importance=importance,
            tags=_with_project(active_tags, project_tag),
        )
    return False


def _set_tags(ctx: AppContext, memory_key: str, tags: list[str]) -> bool:
    """既存 memory の tags を差し替える（達成/中止の状態遷移）。既存の project:* は温存する。"""
    merged = list(tags)
    existing = ctx.memory_service.get_memory(memory_key)
    if isinstance(existing, Success):
        old_tags = getattr(existing.value, "tags", None)
        if isinstance(old_tags, list):
            for t in old_tags:
                if isinstance(t, str) and t.startswith("project:") and t not in merged:
                    merged.append(t)
    upd = ctx.memory_service.update_memory(memory_key, tags=merged)
    if isinstance(upd, Success):
        return True
    logger.warning("hook_extraction: tag update failed key=%s: %s", memory_key, upd.error)
    return False


async def _create(
    ctx: AppContext,
    persona: str,
    content: str,
    *,
    importance: float,
    tags: list[str],
    emotion: str = "neutral",
    valid_until: datetime | None = None,
) -> bool:
    """重複（類似 ≥0.85）を skip して記憶を 1 件保存する。"""
    if await _is_duplicate(ctx, content):
        logger.debug("hook_extraction: skipping duplicate persona=%s: %s", persona, content[:60])
        return False
    mem_result = await ctx.memory_service.create_memory(
        content=content,
        importance=importance,
        tags=tags,
        emotion=emotion,
        valid_until=valid_until,
    )
    if not isinstance(mem_result, Success):
        logger.warning("hook_extraction: save failed persona=%s: %s", persona, content[:60])
        return False
    await _upsert_vector(ctx, persona, mem_result.value)
    return True


async def _is_duplicate(ctx: AppContext, content: str) -> bool:
    """意味検索の最上位スコアがしきい値を超えていれば重複とみなす。"""
    res = await ctx.search_engine.search(SearchQuery(text=content, top_k=3, mode="semantic"))
    if not isinstance(res, Success) or not res.value:
        return False
    return getattr(res.value[0], "score", 0.0) > DUPLICATE_SCORE_THRESHOLD


async def _upsert_vector(ctx: AppContext, persona: str, memory: Any) -> None:
    """ベクトルストアへの反映（失敗は非致命）。"""
    if ctx.vector_store is None:
        return
    with contextlib.suppress(Exception):
        await ctx.vector_store.upsert(persona, memory.key, memory.content)


def _apply_context_update(ctx: AppContext, persona: str, ctx_update: dict, tool_calls_log: list[dict] | None) -> None:
    """context_update を persona state に適用する（run_memory_llm と同一規約の薄い写し）。"""
    skip_emotion, skip_body, skip_state_text, skip_user_info, _ = _context_update_skips(tool_calls_log)

    emotion = ctx_update.get("emotion")
    if emotion and not skip_emotion:
        normalized = normalize_emotion(str(emotion).strip())
        if normalized and normalized != "neutral":
            ctx.persona_service.update_emotion(
                persona,
                normalized,
                _clamp_emotion_intensity(ctx_update.get("emotion_intensity")),
                context="llm_suggested",
            )

    if not skip_state_text:
        state_fields: dict[str, object] = {
            key: val
            for key in ("physical_state", "mental_state", "environment")
            if isinstance(val := ctx_update.get(key), str) and val.strip()
        }
        state_fields.update(_body_delta_state(ctx, persona, ctx_update, skip_body=skip_body))
        if state_fields:
            ctx.persona_service.update_physical_state(persona, **state_fields)

    if not skip_user_info:
        user_info = {
            key.removeprefix("user_"): str(val)
            for key, val in ctx_update.items()
            if key.startswith("user_") and val is not None
        }
        if user_info:
            ctx.persona_service.update_user_info(persona, user_info)

    context_note = ctx_update.get("context_note")
    if context_note:
        ctx.persona_service.update_persona_info(persona, {"context_note": context_note})


def _clamp_emotion_intensity(val: object) -> float:
    """感情強度を [0,1] に正規化（非数値は 0.5）。"""
    try:
        return _clamp(float(val) if val is not None else None)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0.5


def _record_failure(ctx: AppContext, persona: str, session_id: str, reason: str) -> None:
    """抽出失敗を session_events に残す（dashboard 可視化用・失敗は非致命）。"""
    with contextlib.suppress(Exception):
        SessionEventRepository(ctx.connection).insert(
            SessionEvent(
                session_id=session_id,
                persona=persona,
                event_type=FAILED_EVENT_TYPE,
                summary=f"hook extraction failed: {reason}"[:500],
            )
        )
