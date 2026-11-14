"""Auto-generated from tools.py split — _tools_persona.py."""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

from nous.application.handover import AUTO_TAG, build_handover, handover_key
from nous.domain.memory.cue import due_cues
from nous.domain.memory.entities import Memory
from nous.domain.memory.service import ONE_SHOT_STATE_TAGS
from nous.domain.profile.tokens import DEFAULT_PROFILE_MAX_TOKENS, estimate_tokens
from nous.domain.shared.result import Success
from nous.domain.shared.time_utils import get_now, relative_time_str
from nous.infrastructure.sqlite.block_repo import PROFILE_BLOCK_NAMES

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from nous.application.use_cases import AppContext


from nous.api.mcp._tools_helpers import (  # noqa: E402
    _apply_body_decay,
    _apply_circadian_drift,
    _apply_emotion_decay,
    _dedupe_memories,
    _format_lightweight_response,
    _format_state_block,
    tool_called_audited,
)


async def _tool_get_context(
    ctx: AppContext, persona: str, project: str | None = None, session_effects: bool = True
) -> dict:
    """Get persona state and memory overview. Call FIRST at session start.
    Lightweight: active commitments + essential story + body/emotion state (~500-800 tokens).
    project: 指定時は project:<slug> タグ付き記憶を PROJECT MEMORIES 節で表示（最大5件）。
    session_effects: 読取副作用（会話時刻の記録・one-shot 状態メモリの消費）を
    実行するか。監査 M8（v4.0）により正規入口は session_begin で、get_context は
    v4.x 互換のためデフォルトで副作用を維持しつつ非推奨警告を出す。"""
    state_result = ctx.persona_service.get_context(persona)
    if not state_result.is_ok:
        await ctx.event_bus.publish(
            "tool.called",
            {
                "persona": persona,
                "session_id": getattr(ctx, "session_id", None),
                "tool_name": "get_context",
                "params_summary": f"persona={persona}, project={project}",
                "result_summary": str(state_result.error),
                "success": False,
            },
        )
        return {"ok": False, "error": state_result.error}
    state = state_result.value

    state, decay_note = await _apply_emotion_decay(ctx, persona, state)

    state = await _apply_body_decay(ctx, persona, state)
    state = _apply_circadian_drift(ctx, persona, state)

    # Top memories for ESSENTIAL STORY (reduced from 15 to 8 for leaner context)
    top_result = ctx.memory_service.get_top_by_importance(8)
    top_memories = top_result.value if top_result.is_ok else []

    # Emotion history for trajectory display
    emotion_history: list = []
    try:
        eh_result = ctx.persona_service.get_emotion_history(persona, limit=5)
        if eh_result.is_ok:
            emotion_history = eh_result.value
    except Exception:
        logger.warning(
            "_tool_get_context: get_emotion_history failed for persona '%s'",
            persona,
            exc_info=True,
        )

    # Lightweight: essentials for seamless persona + conversation restoration
    goals_result = ctx.memory_service.get_by_tags(["goal"])
    goals = goals_result.value if goals_result.is_ok else []
    reflection_result = ctx.memory_service.get_by_tags(["reflection"])
    reflections = reflection_result.value if reflection_result.is_ok else []
    mm_result = ctx.memory_service.get_by_tags(["mental_model", "abstracted"])
    mental_models = mm_result.value if mm_result.is_ok else []
    # Session summaries — conversation continuity
    ss_result = ctx.memory_service.get_by_tags(["session_summary"])
    session_summaries = ss_result.value if ss_result.is_ok else []
    # 最新のサマリを優先表示（並び順が保証されないため updated_at 降順でソート）
    session_summaries = sorted(
        session_summaries,
        key=lambda m: m.updated_at or m.created_at or get_now(),
        reverse=True,
    )
    equip_result = ctx.equipment_service.get_equipment()
    equipment = equip_result.value if equip_result.is_ok else {}
    # Recent memories (last 5) for conversation continuity across sessions
    recent_result = ctx.memory_service.get_recent(5)
    recent = (
        recent_result.value if recent_result.is_ok else []
    )  # top_memories と重複する recent は除外（重要度表示側を優先）
    recent = [m for m in recent if not any(m.key == t.key for t in top_memories)]

    # Project memories — project:<slug> タグ付き記憶を updated_at 降順・内容 dedupe・上位5件で表示
    project_memories: list | None = None
    if project:
        pm_result = ctx.memory_service.get_by_tags([f"project:{project}"])
        # is_ok は bool プロパティで narrow 不能のため isinstance で分岐（union-attr 回避）
        if isinstance(pm_result, Success):
            project_memories = pm_result.value
        else:
            logger.warning(
                "_tool_get_context: get_by_tags failed for project '%s': %s",
                project,
                pm_result.error,
            )
            project_memories = []
        project_memories = sorted(
            project_memories,
            key=lambda m: m.updated_at or m.created_at or get_now(),
            reverse=True,
        )
        project_memories = _dedupe_memories(list(project_memories), set())[:5]
        if not project_memories:
            project_memories = None

    # wiki 上位層（#18）: ページ本文は入れず、件数だけ 1 行で知らせる。
    wiki_page_count: int | None = None
    if project:
        try:
            from nous.infrastructure.wiki.store import WikiStore

            wiki_store = WikiStore(ctx.settings.data_root, persona)
            prefix = f"project-{project.lower()}-"
            wiki_page_count = len([s for s in wiki_store.list_slugs() if s.startswith(prefix)]) or None
        except Exception as e:
            logger.debug("_tool_get_context: wiki count failed: %s", e)
            wiki_page_count = None

    # 未解決の問い（#55）: 1 件だけ。project 指定時は同じ project を優先する。
    open_question: str | None = None
    # 引き継ぎ栞（#58）用に全文を新しい順で持っておく（先頭2件が論点、末尾が「次」）
    handover_questions: list[str] = []
    try:
        oq_result = ctx.memory_service.get_by_tags(["open-question"])
        if isinstance(oq_result, Success) and oq_result.value:
            candidates = list(oq_result.value)
            if project:
                scoped = [m for m in candidates if f"project:{project}" in (getattr(m, "tags", ()) or ())]
                candidates = scoped or candidates
            candidates.sort(key=lambda m: m.created_at or m.updated_at or get_now())
            handover_questions = [" ".join(str(m.content).split()) for m in reversed(candidates)]
            open_question = handover_questions[0][:120]
    except Exception as e:  # noqa: BLE001 — 表示は落とさない
        logger.debug("_tool_get_context: open question lookup failed: %s", e)
        open_question = None

    # 前回の引き継ぎ（#58）: key ``handover:<slug>`` があればそれを最優先（明示更新）。
    handover: str | None = None
    if project:
        handover_mem: Memory | None = None
        hv_result = ctx.memory_service.get_memory(handover_key(project))
        if isinstance(hv_result, Success):
            handover_mem = hv_result.value
        handover = (
            build_handover(
                project,
                ([handover_mem] if handover_mem is not None else []) + list(project_memories or []),
                handover_questions,
                get_now(),
            )
            or None
        )

    # 期限が近い／切れた予定・約束は due_cues（goal 行の ⏰）が毎回ライブ計算で出す。
    time_since = ""
    if state.last_conversation_time:
        time_since = relative_time_str(state.last_conversation_time)
    current_time = get_now().strftime("%Y-%m-%d %H:%M")
    if session_effects:
        logger.info("DEPRECATED: get_context performs session side effects; use session_begin instead (audit M8)")
        ctx.persona_service.record_conversation_time(persona)

    # audit M2 — prospective memory: commitments whose deadline is inside the
    # window are marked ⏰ on their line. 減衰ワーカー廃止で due_reminder の
    # one-shot 生産者は無くなったため、時刻表示はこの due_cues 経路のみ。
    due_labels = {m.key: label for m, label in due_cues(goals or [], get_now()) if getattr(m, "key", None)}

    # 状態記憶（physical_state/mental_state）を読む。消費はしない（#52）。
    one_shot_context: dict[str, str] = {}
    if session_effects:
        for tag_name, label in ONE_SHOT_STATE_TAGS.items():
            mems_result = ctx.memory_service.get_by_tags([tag_name], include_consumed=True)
            if isinstance(mems_result, Success) and mems_result.value:
                latest = mems_result.value[0]
                cleaned = latest.content.replace(f"{tag_name}: ", "", 1)
                one_shot_context[label] = cleaned

    result_text = _format_lightweight_response(
        state,
        top_memories,
        goals,
        equipment,
        recent,
        time_since,
        emotion_history,
        reflections,
        mental_models,
        session_summaries,
        current_time,
        decay_note=decay_note,
        one_shot_context=one_shot_context or None,
        project_memories=project_memories,
        project_name=project or None,
        wiki_page_count=wiki_page_count,
        due_labels=due_labels or None,
        open_question=open_question,
        handover=handover,
    )
    # 次回以降の安定化（#58）: 表示した文字列を key ``handover:<slug>`` に上書き保存する。
    # これで 2 回目以降は明示更新と同じ経路（エージェントが書いた内容が勝つ）に乗る。
    if session_effects and project and handover:
        _upsert_handover(ctx, project, handover)
    await ctx.event_bus.publish(
        "tool.called",
        {
            "persona": persona,
            "session_id": getattr(ctx, "session_id", None),
            "tool_name": "get_context",
            "params_summary": f"persona={persona}, project={project}",
            "result_summary": f"Context formatted ({len(top_memories)} memories, {len(goals)} goals)",
            "success": True,
        },
    )
    return {"ok": True, "result": result_text}


async def _tool_session_begin(ctx: AppContext, persona: str, project: str | None = None) -> dict:
    """Canonical session-start entry (audit M8): returns the same context as
    get_context AND owns the session side effects (conversation-time record,
    one-shot state consumption). get_context retains those effects for v4.x
    compatibility only."""
    return await _tool_get_context(ctx, persona, project=project, session_effects=True)


def _upsert_handover(ctx: AppContext, project: str, text: str) -> None:
    """引き継ぎ栞を key ``handover:<slug>`` の記憶として upsert する（新しい機構は作らない）。"""
    key = handover_key(project)
    try:
        existing = ctx.memory_service.get_memory(key)
        if isinstance(existing, Success) and existing.value is not None:
            ctx.memory_service.update_memory(key, content=text)
            return
        now = get_now()
        ctx.memory_service.save_memory(
            Memory(
                key=key,
                content=text,
                created_at=now,
                updated_at=now,
                importance=0.6,
                tags=["handover", AUTO_TAG],
                kind="semantic",
                source_type="system",
            )
        )
    except Exception as e:  # noqa: BLE001 — 栞の保存失敗でセッション開始を落とさない
        logger.debug("_upsert_handover failed: %s", e)


@tool_called_audited("update_context")
async def _tool_update_context(
    ctx: AppContext,
    persona: str,
    emotion: str | None = None,
    emotion_intensity: float | None = None,
    valence: float | None = None,
    arousal: float | None = None,
    physical_state: str | None = None,
    mental_state: str | None = None,
    environment: str | None = None,
    relationship_status: str | None = None,
    body_state: dict | None = None,
    context_note: str | None = None,
    user_info: dict | None = None,
    persona_info: dict | None = None,
    nickname: str | None = None,
    relationship_type: str | None = None,
    appearance: str | None = None,
) -> dict:
    """Update persona state. context_note: short note on current activity for session continuity.
    body_state: {fatigue, warmth, arousal, heart_rate, pain (0.0-1.0)}.
    valence/arousal: direct emotion rating in [-1, 1] (both required, together with emotion).
    Stored as {"va": [v, a]} JSON in the emotion history record's context.
    appearance: free-text description of current appearance (clothing, hair, accessories)."""
    updated: list[str] = []

    # Direct V-A rating (Phase 0 spike). Priority: direct > derived (emotion_to_va).
    va_context: str | None = None
    if valence is not None or arousal is not None:
        if emotion is None:
            return {"ok": False, "error": "valence/arousal requires emotion"}
        if valence is None or arousal is None:
            return {"ok": False, "error": "valence and arousal must be provided together"}
        try:
            _v = max(-1.0, min(1.0, float(valence)))
            _a = max(-1.0, min(1.0, float(arousal)))
        except (TypeError, ValueError):
            return {"ok": False, "error": "valence/arousal must be numbers"}
        va_context = json.dumps({"va": [_v, _a]})
        from nous.domain.value_objects import emotion_to_va, normalize_emotion

        logger.info(
            "va_direct=(%.2f, %.2f) va_derived=%s persona=%s",
            _v,
            _a,
            emotion_to_va(normalize_emotion(emotion)),
            persona,
        )

    if emotion is not None:
        # f2: 0.0を欠損扱いしない（or 0.5は0.0を潰す）＋範囲正規化
        from nous.domain.value_objects import normalize_importance

        try:
            _intensity = normalize_importance(float(emotion_intensity) if emotion_intensity is not None else None)
        except (TypeError, ValueError):
            _intensity = 0.5
        result = ctx.persona_service.update_emotion(persona, emotion, _intensity, context=va_context or "manual_update")
        if result.is_ok:
            updated.append(f"emotion={emotion}")

    physical_updates: dict[str, str] = {}
    if physical_state is not None:
        physical_updates["physical_state"] = physical_state
    if mental_state is not None:
        physical_updates["mental_state"] = mental_state
    if body_state is not None:
        for key in ("fatigue", "warmth", "arousal", "heart_rate", "pain"):
            if key in body_state and body_state[key] is not None:
                physical_updates[key] = str(body_state[key])
    if physical_updates:
        result = ctx.persona_service.update_physical_state(persona, **physical_updates)
        if result.is_ok:
            updated.extend(f"{k}={v}" for k, v in physical_updates.items())
    reported = dict(physical_updates)

    if environment is not None:
        # 場所の変更は move と同じ経路（生理コスト + ``place.moved``）を通す。
        # ここで直接 ``environment`` を書くと滞在時間の起点が残らず、ダッシュボードが
        # 「新しい場所 + 古い到着時刻」を表示してしまう（kanban #49）。
        from nous.application.movement import apply_move

        moved = apply_move(ctx, persona, environment, environment_text=environment)
        if moved.ok:
            # 移動コストは state に上乗せされる。返り値（と報告）も移動後の実値に揃える。
            if moved.fatigue is not None and "fatigue" in reported:
                updated = [f"fatigue={moved.fatigue}" if u.startswith("fatigue=") else u for u in updated]
            moved_note = f"(+{moved.minutes}min)" if moved.minutes else ""
            updated.append(f"environment={environment}{moved_note}")
        else:
            # 失敗を黙って飲むと呼び出し側が「場所が変わった」と誤解する（監査にも残らない）。
            logger.warning("update_context: environment not applied: %s", moved.error)
            updated.append(f"environment_skipped={moved.error or 'unknown'}")

    # context_note: lightweight session continuity marker
    if context_note is not None:
        ctx.persona_service.update_persona_info(persona, {"context_note": context_note})
        updated.append("context_note updated")

    if relationship_status is not None or relationship_type is not None:
        status = relationship_status or relationship_type
        if status:
            result = ctx.persona_service.update_relationship(persona, status)
            if result.is_ok:
                updated.append(f"relationship={status}")

    if user_info is not None:
        result = ctx.persona_service.update_user_info(persona, user_info)
        if result.is_ok:
            updated.append("user_info updated")

    if persona_info is not None:
        pi = dict(persona_info)
        if nickname:
            pi["nickname"] = nickname
        # goals are extracted and persisted by PersonaService.update_persona_info internally
        result = ctx.persona_service.update_persona_info(persona, pi)
        if result.is_ok:
            updated.append("persona_info updated")
    elif nickname:
        result = ctx.persona_service.update_persona_info(persona, {"nickname": nickname})
        if result.is_ok:
            updated.append(f"nickname={nickname}")

    # Appearance
    if appearance is not None:
        ctx.persona_service.update_state(persona, "appearance", appearance)
        updated.append(f"appearance={appearance[:40]}…" if len(appearance) > 40 else f"appearance={appearance}")

    if not updated:
        return {"ok": True, "result": "No changes made (all parameters were None)"}
    await ctx.event_bus.publish(
        "context.updated",
        {
            "persona": persona,
            "emotion": emotion,
            "emotion_intensity": emotion_intensity,
            "body_state": body_state,
            "context_note": context_note,
        },
    )
    state_result = ctx.persona_service.get_context(persona)
    state_block = _format_state_block(state_result.value) if isinstance(state_result, Success) else ""
    summary = f"Context updated: {', '.join(updated)}"
    return {"ok": True, "result": f"{summary}\n{state_block}" if state_block else summary}


# --- Profile tools (B-5) ---


def _sanitize_profile_content(text: str) -> str:
    """context_loader._sanitize_text と同じ流儀で異常 Unicode を除去する。"""
    if not text:
        return text
    # 遅延 import: モジュールレベルだと chat.service 経由の循環 import になる
    from nous.application.chat.pipeline.context_loader import _is_suspicious_cp

    suspicious = [ch for ch in text if _is_suspicious_cp(ord(ch))]
    if not suspicious:
        return text
    ratio = len(suspicious) / len(text)
    if ratio > 0.1:
        logger.warning("profile_update: discarding content with %.0f%% suspicious chars", ratio * 100)
        return ""
    logger.info("profile_update: removed %d suspicious chars (%.0f%%)", len(suspicious), ratio * 100)
    return "".join(ch for ch in text if not _is_suspicious_cp(ord(ch)))


@tool_called_audited("profile_update")
async def _tool_profile_update(ctx: AppContext, persona: str, target: str, content: str) -> dict:
    """Rewrite a profile block whole (target: "me" | "user"). Max ~3000 tokens."""
    if target not in PROFILE_BLOCK_NAMES:
        return {"ok": False, "error": f"Invalid target: {target} (must be 'me' or 'user')"}
    content = _sanitize_profile_content(content)
    if not content:
        return {"ok": False, "error": "content must not be empty"}
    tokens = estimate_tokens(content)
    if tokens > DEFAULT_PROFILE_MAX_TOKENS:
        return {
            "ok": False,
            "error": f"content too large: ~{tokens} tokens exceeds the limit of {DEFAULT_PROFILE_MAX_TOKENS}",
        }
    result = ctx.memory_service.upsert_profile_block(persona, target, content)
    if not isinstance(result, Success):
        return {"ok": False, "error": str(result.error)}
    return {"ok": True, "result": f"Profile block '{target}' updated (~{tokens} tokens)"}
