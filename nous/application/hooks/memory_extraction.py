"""pi hook 経由の記憶抽出 pipeline（turn.completed → 記憶化）。

chat pipeline を通らない pi 対話ターンを nous 側で記憶化する経路。
`run_memory_llm` は ChatConfig を要求するため使わず、`MemoryLLM.process` を
`LLMConfig` 由来の薄い設定アダプタ経由で呼ぶ（既存 pipeline 無改変）。
プロンプト（`_CONTEXT_LLM_PROMPT`）・JSON パース・正規化ヘルパは memory_extractor を再利用する。
"""

from __future__ import annotations

import contextlib
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, cast

from nous.application.chat.memory_extractor import (
    MemoryLLM,
    _body_delta_state,
    _build_memory_llm_context,
    _context_update_skips,
    normalize_importance,
    normalize_tags,
)
from nous.domain.language import FALLBACK_LANGUAGE, SUPPORTED_LANGUAGES, detect_language
from nous.domain.memory.session_event import SessionEvent
from nous.domain.search.engine import SearchQuery
from nous.domain.shared.result import Success
from nous.domain.value_objects import ensure_project_tag, normalize_emotion, normalize_project_slug
from nous.domain.value_objects import normalize_importance as _clamp
from nous.infrastructure.logging.structured import get_logger
from nous.infrastructure.sqlite.session_event_repo import SessionEventRepository

if TYPE_CHECKING:
    from datetime import datetime

    from nous.application.use_cases import AppContext
    from nous.config.settings import Settings
    from nous.domain.config.chat_config import ChatConfig

logger = get_logger(__name__)

#: hook pipeline が拾う event 型（session.stopped は _summarize_session_end 専用）。
HOOK_EXTRACTION_EVENT_TYPES = frozenset({"turn.completed"})

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
    # reasoning LLM は reasoning token も max_tokens に含むため、既定 512 では
    # content が空になる。hook 抽出は短文なので settings 既定の 8192 で十分。
    extract_max_tokens: int = 8192

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
        extract_max_tokens=settings.memory_enrichment.extraction_max_tokens,
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
        context_str, inventory_str = await _build_memory_llm_context(ctx)
        result = await MemoryLLM().process(
            cast("ChatConfig", _llm_config(ctx.settings, user_text)),
            user_message=user_text,
            assistant_response=assistant_text,
            context=context_str,
            inventory=inventory_str,
            persona_name=ctx.persona or persona,
            mode="context",
        )
        if not result:
            logger.warning("hook_extraction: empty LLM result persona=%s", persona)
            _record_failure(ctx, persona, session_id, "empty result")
            return

        n_facts, _n_insights = await _apply_result(ctx, persona, result, _project_tag(event))
        if result.get("context_update"):
            _apply_context_update(ctx, persona, result["context_update"], detail.get("tool_calls_log") or [])
        logger.info(
            "hook_extraction: %d facts saved persona=%s",
            n_facts,
            persona,
        )
    except Exception as e:
        logger.warning("hook_extraction failed: %s", e)
        _record_failure(ctx, persona, session_id, str(e))


async def _apply_result(ctx: AppContext, persona: str, result: dict, project_tag: str | None = None) -> tuple[int, int]:
    """LLM 抽出結果を保存し、(facts, insights) の保存件数を返す。

    pi-hook 経路が書き込むのは facts のみ。insights（reflection 記憶）は
    内省パイプラインの担域で、この経路では発生しないため常に 0。
    """
    n_facts = 0
    for fact in result.get("facts") or []:
        content = str(fact.get("content") or "").strip()
        if not content:
            continue
        tags = normalize_tags(fact.get("tags"))
        if await _create(
            ctx,
            persona,
            content,
            importance=normalize_importance(fact.get("importance")),
            tags=_with_project(tags, project_tag),
            emotion=str(fact.get("emotion") or "neutral"),
        ):
            n_facts += 1

    return n_facts, 0


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
    """重複（類似 ≥ settings.memory.duplicate_threshold）を skip して記憶を 1 件保存する。"""
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
    return getattr(res.value[0], "score", 0.0) > ctx.settings.memory.duplicate_threshold


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
            for key in ("physical_state", "mental_state")
            if isinstance(val := ctx_update.get(key), str) and val.strip()
        }
        state_fields.update(_body_delta_state(ctx, persona, ctx_update, skip_body=skip_body))
        if state_fields:
            ctx.persona_service.update_physical_state(persona, **state_fields)
        # relationship_status は空文字で Failure になるので strip 後の空は呼ばない
        rel = ctx_update.pop("relationship_status", None)
        if isinstance(rel, str) and rel.strip():
            ctx.persona_service.update_relationship(persona, rel.strip())
        # 場所は移動と同じ経路（生理コスト + ``place.moved``）。直接書くと滞在時間の
        # 起点が残らず、ダッシュボードが「新しい場所 + 古い到着時刻」を出す。
        env_raw = ctx_update.pop("environment", None)
        if isinstance(env_raw, str) and env_raw.strip():
            from nous.application.persona.movement import apply_move

            moved = apply_move(ctx, persona, env_raw, environment_text=env_raw, charge_if_unknown=False)
            if moved.ok:
                ctx_update["environment"] = env_raw
            else:
                logger.warning("hook_extraction: environment not applied: %s", moved.error)
    else:
        ctx_update.pop("environment", None)  # 適用されない値は SSE に流さない
        ctx_update.pop("relationship_status", None)

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
