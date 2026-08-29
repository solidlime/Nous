"""MemoryLLM extractor: LLM calls, JSON parsing, and result application."""

from __future__ import annotations

import contextlib
import json
from typing import TYPE_CHECKING

from nous.application.chat.memory_prompts import _MEMORY_LLM_PROMPT
from nous.domain.language import LanguageResolver
from nous.domain.search.engine import SearchQuery
from nous.domain.value_objects import VALID_EMOTIONS, normalize_importance
from nous.infrastructure.llm.base import LLMMessage
from nous.infrastructure.llm.factory import get_provider
from nous.infrastructure.logging.structured import get_logger

if TYPE_CHECKING:
    from nous.application.use_cases import AppContext
    from nous.domain.chat_config import ChatConfig

logger = get_logger(__name__)


class MemoryLLM:
    """T35: ターン終了後に facts・context_update・inventory_update を一括抽出する。"""

    async def process(
        self,
        config: ChatConfig,
        user_message: str,
        assistant_response: str,
        *,
        context: str = "",
        commitments: str = "",
        inventory: str = "",
        persona_name: str = "assistant",
        persona_identity: str = "",
    ) -> dict:
        extract_model = config.extract_model.strip() or config.get_effective_model()
        api_key = config.get_effective_api_key()
        if not api_key or not extract_model:
            return {}

        try:
            provider = get_provider(
                config.provider,
                api_key,
                extract_model,
                config.get_effective_base_url(),
            )
        except Exception as e:
            logger.warning("MemoryLLM: provider init failed: %s", e)
            return {}

        language_resolver = LanguageResolver(config)
        lang = language_resolver.resolve(user_message=user_message)
        prompt = _MEMORY_LLM_PROMPT.format(
            language=LanguageResolver.display_name(lang),
            persona_name=persona_name,
            persona_identity=persona_identity.strip() or f"あなたは {persona_name} として振る舞います。",
            context=context.strip() or "(情報なし)",
            commitments=commitments.strip() or "(なし)",
            inventory=inventory.strip() or "(なし)",
            user_message=user_message[:500],
            assistant_response=assistant_response[:500],
        )

        from nous.infrastructure.llm.base import DoneEvent, ErrorEvent, TextDeltaEvent

        text = ""
        try:
            async for event in provider.stream(
                messages=[LLMMessage(role="user", content=prompt)],
                system="",
                tools=[],
                temperature=0.0,
                max_tokens=config.extract_max_tokens,
            ):
                if isinstance(event, TextDeltaEvent):
                    text += event.content
                elif isinstance(event, (DoneEvent, ErrorEvent)):
                    break
        except Exception as e:
            logger.warning("MemoryLLM: LLM call failed: %s", e)
            return {}

        return _parse_memory_llm_result(text)


def _parse_memory_llm_result(text: str) -> dict:
    """MemoryLLM出力のJSONをパースする。"""
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        text = "\n".join(lines[1:-1] if lines[-1].startswith("```") else lines[1:])
    try:
        result = json.loads(text)
        if isinstance(result, dict):
            if "facts" not in result:
                result["facts"] = []
            result["facts"] = [f for f in result["facts"] if isinstance(f, dict) and "content" in f]
            if "goals" not in result:
                result["goals"] = []
            result["goals"] = [g for g in result["goals"] if isinstance(g, dict) and "content" in g]
            if "promises" not in result:
                result["promises"] = []
            result["promises"] = [p for p in result["promises"] if isinstance(p, dict) and "content" in p]
            if "context_update" not in result:
                result["context_update"] = {}
            if "inventory_update" not in result:
                result["inventory_update"] = {}
            return result
        # 後方互換: 古いファクト配列形式
        if isinstance(result, list):
            return {
                "facts": [f for f in result if isinstance(f, dict) and "content" in f],
                "goals": [],
                "promises": [],
                "context_update": {},
                "inventory_update": {},
            }
    except Exception as _e:
        logger.debug("MemoryLLM: failed to parse LLM output: %s", _e)
    return {}


async def _build_memory_llm_context(ctx: AppContext) -> tuple[str, str, str]:
    """MemoryLLM に渡すコンテキスト・コミットメント・インベントリ文字列を構築する。

    Returns:
        (context_str, commitments_str, inventory_str)
    """
    lines: list[str] = []
    persona = ctx.persona

    state_result = ctx.persona_service.get_context(persona)
    if state_result.is_ok:
        state = state_result.value
        user_info = getattr(state, "user_info", {}) or {}
        user_name = user_info.get("name") or user_info.get("nickname") or ""
        if user_name:
            lines.append(f"ユーザー名: {user_name}")
        emotion = getattr(state, "emotion", "")
        if emotion:
            intensity = getattr(state, "emotion_intensity", None)
            lines.append(f"感情: {emotion}" + (f" (強度={intensity:.1f})" if intensity else ""))
        for field in ("mental_state", "physical_state", "environment"):
            val = getattr(state, field, "")
            if val:
                lines.append(f"{field}: {val}")

    # アクティブな goal (scope=self と scope=interpersonal を統合)
    commit_lines: list[str] = []
    for tag_pair, label in [
        (["goal", "active"], "goal (self)"),
        (["goal", "active", "interpersonal"], "goal (interpersonal)"),
    ]:
        mem_result = ctx.memory_service.get_by_tags(tag_pair)
        if mem_result.is_ok and mem_result.value:
            for m in mem_result.value[:5]:
                key = getattr(m, "key", None) or getattr(m, "id", "")
                commit_lines.append(f"  [{label}] key={key} : {m.content[:100]}")
    commitments_str = "\n".join(commit_lines)

    # 装備品（context に含める）
    equip_result = ctx.equipment_service.get_equipment()
    if equip_result.is_ok and equip_result.value:
        equipped = {k: v for k, v in equip_result.value.items() if v}
        if equipped:
            equip_str = ", ".join(f"{k}={v}" for k, v in equipped.items())
            lines.append(f"装備: {equip_str}")

    # 所持品リスト
    inv_lines: list[str] = []
    try:
        items_result = ctx.equipment_service.search_items()
        if items_result.is_ok and items_result.value:
            for item in items_result.value[:10]:
                desc = f" ({item.description})" if getattr(item, "description", None) else ""
                inv_lines.append(f"  - {item.name}{desc}")
    except Exception as _e:
        logger.debug("MemoryLLM: failed to build context inventory: %s", _e)
    inventory_str = "\n".join(inv_lines)

    return "\n".join(lines), commitments_str, inventory_str


async def run_memory_llm(ctx: AppContext, config: ChatConfig, payload: dict) -> dict:
    """T35: 遅延MemoryLLM処理。facts保存 + context/inventory更新を行う。結果dictを返す。"""
    user_message = payload.get("user", "")
    assistant_response = payload.get("assistant", "")
    if not user_message and not assistant_response:
        return {}
    try:
        context_str, commitments_str, inventory_str = await _build_memory_llm_context(ctx)
        persona_name = ctx.persona or "assistant"
        persona_identity = (config.system_prompt or "").strip()
        from nous.application.chat.memory_llm import MemoryLLM as _MemoryLLM

        result = await _MemoryLLM().process(
            config,
            user_message,
            assistant_response,
            context=context_str,
            commitments=commitments_str,
            inventory=inventory_str,
            persona_name=persona_name,
            persona_identity=persona_identity,
        )
        if not result:
            return {}

        persona = ctx.persona

        # facts: スマートアップサート（類似度 > 0.85 ならスキップ）
        facts = result.get("facts", [])
        for fact in facts:
            content = fact.get("content", "")
            if not content:
                continue
            dup_check = await ctx.search_engine.search(SearchQuery(text=content, top_k=3, mode="semantic"))
            if dup_check.is_ok and dup_check.value:
                top_hit = dup_check.value[0]
                hit_score = top_hit.score if hasattr(top_hit, "score") else 0.0
                if hit_score > 0.85:
                    logger.debug("MemoryLLM: skipping duplicate fact (score=%.2f): %s", hit_score, content[:60])
                    continue
            mem_result = await ctx.memory_service.create_memory(
                content=content,
                importance=float(fact.get("importance", 0.6)),
                tags=fact.get("tags", ["auto_extract"]),
                emotion=fact.get("emotion", "neutral"),
            )
            if mem_result.is_ok and ctx.vector_store is not None:
                with contextlib.suppress(Exception):
                    await ctx.vector_store.upsert(persona, mem_result.value.key, mem_result.value.content)
        if facts:
            logger.info("MemoryLLM: processed %d facts for persona=%s", len(facts), persona)

        # goals: action ベース処理（create / achieve / cancel）
        goals = result.get("goals", [])
        for goal in goals:
            action = goal.get("action", "create")
            content = goal.get("content", "")
            memory_key = goal.get("memory_key", "")

            if action == "achieve" and memory_key:
                upd = ctx.memory_service.update_memory(memory_key, tags=["goal", "achieved"])
                logger.info("MemoryLLM: goal achieved key=%s", memory_key)
                if not upd.is_ok:
                    logger.warning("MemoryLLM: goal achieve failed key=%s: %s", memory_key, upd.error)
            elif action == "cancel" and memory_key:
                upd = ctx.memory_service.update_memory(memory_key, tags=["goal", "cancelled"])
                logger.info("MemoryLLM: goal cancelled key=%s", memory_key)
                if not upd.is_ok:
                    logger.warning("MemoryLLM: goal cancel failed key=%s: %s", memory_key, upd.error)
            elif action == "create" and content:
                dup_check = await ctx.search_engine.search(SearchQuery(text=content, top_k=3, mode="semantic"))
                if dup_check.is_ok and dup_check.value:
                    top_hit = dup_check.value[0]
                    if (top_hit.score if hasattr(top_hit, "score") else 0.0) > 0.85:
                        logger.debug("MemoryLLM: skipping duplicate goal: %s", content[:60])
                        continue
                mem_result = await ctx.memory_service.create_memory(
                    content=content,
                    importance=0.75,
                    tags=["goal", "active"],
                    emotion="neutral",
                )
                if mem_result.is_ok and ctx.vector_store is not None:
                    with contextlib.suppress(Exception):
                        await ctx.vector_store.upsert(persona, mem_result.value.key, mem_result.value.content)
        if goals:
            logger.info("MemoryLLM: processed %d goals for persona=%s", len(goals), persona)

        # promises → goals with scope=interpersonal (unified with goals)
        promises = result.get("promises", [])
        for promise in promises:
            action = promise.get("action", "create")
            content = promise.get("content", "")
            memory_key = promise.get("memory_key", "")

            if action in ("fulfill", "achieve") and memory_key:
                upd = ctx.memory_service.update_memory(
                    memory_key, tags=["goal", "achieved", "archived", "interpersonal"]
                )
                logger.info("MemoryLLM: interpersonal goal achieved key=%s", memory_key)
                if not upd.is_ok:
                    logger.warning("MemoryLLM: interpersonal goal achieve failed key=%s: %s", memory_key, upd.error)
            elif action == "cancel" and memory_key:
                upd = ctx.memory_service.update_memory(
                    memory_key, tags=["goal", "cancelled", "archived", "interpersonal"]
                )
                logger.info("MemoryLLM: interpersonal goal cancelled key=%s", memory_key)
                if not upd.is_ok:
                    logger.warning("MemoryLLM: interpersonal goal cancel failed key=%s: %s", memory_key, upd.error)
            elif action == "create" and content:
                dup_check = await ctx.search_engine.search(SearchQuery(text=content, top_k=3, mode="semantic"))
                if dup_check.is_ok and dup_check.value:
                    top_hit = dup_check.value[0]
                    if (top_hit.score if hasattr(top_hit, "score") else 0.0) > 0.85:
                        logger.debug("MemoryLLM: skipping duplicate interpersonal goal: %s", content[:60])
                        continue
                mem_result = await ctx.memory_service.create_memory(
                    content=content,
                    importance=0.8,
                    tags=["goal", "active", "interpersonal"],
                    emotion="neutral",
                )
                if mem_result.is_ok and ctx.vector_store is not None:
                    with contextlib.suppress(Exception):
                        await ctx.vector_store.upsert(persona, mem_result.value.key, mem_result.value.content)
        if promises:
            logger.info("MemoryLLM: processed %d interpersonal goals for persona=%s", len(promises), persona)

        # context_update: 感情・状態を更新
        ctx_update = result.get("context_update", {})
        if ctx_update:
            emotion = ctx_update.get("emotion")
            intensity = ctx_update.get("emotion_intensity")
            if emotion:
                if str(emotion).strip().lower() in VALID_EMOTIONS:
                    ctx.persona_service.update_emotion(
                        persona,
                        emotion,
                        normalize_importance(float(intensity) if intensity is not None else None),
                        context="llm_suggested",
                    )
                else:
                    logger.debug("MemoryLLM: dropping non-canonical emotion label: %r", emotion)

            # physical_state/mental_state → memories (one-shot consumption)
            for key, tags in [
                ("physical_state", ["physical_state", "body"]),
                ("mental_state", ["mental_state", "mind"]),
            ]:
                val = ctx_update.get(key)
                if val is not None and str(val).strip():
                    mem_result = await ctx.memory_service.create_memory(
                        content=f"{key}: {val}",
                        tags=tags,
                        importance=0.6,
                    )
                    if mem_result.is_ok and ctx.vector_store is not None:
                        with contextlib.suppress(Exception):
                            await ctx.vector_store.upsert(persona, mem_result.value.key, mem_result.value.content)
                    ctx_update.pop(key, None)  # update_physical_state に渡さない

            state_fields = {
                k: v
                for k, v in ctx_update.items()
                if k in {"environment", "fatigue", "warmth", "arousal"} and v is not None
            }
            if state_fields:
                ctx.persona_service.update_physical_state(persona, **state_fields)

            # user_info fields → update_user_info
            user_info_map = {}
            for key, val in ctx_update.items():
                if key.startswith("user_") and val is not None:
                    user_info_map[key.replace("user_", "")] = str(val)
            if user_info_map:
                ctx.persona_service.update_user_info(persona, user_info_map)

            # context_note → persona_info（session continuity）
            context_note = ctx_update.get("context_note")
            if context_note:
                ctx.persona_service.update_persona_info(persona, {"context_note": context_note})

        # inventory_update: 装備変更 + アイテム追加/削除/更新
        inv_update = result.get("inventory_update", {})
        equip_map = inv_update.get("equip", {})
        unequip_list = inv_update.get("unequip", [])
        remove_items = inv_update.get("remove_items", [])
        add_items = inv_update.get("add_items", [])
        update_items = inv_update.get("update_items", [])

        for item_name in remove_items:
            if isinstance(item_name, str) and item_name.strip():
                ctx.equipment_service.remove_item(item_name.strip())

        for item_data in add_items:
            if isinstance(item_data, dict):
                name = item_data.get("name", "").strip()
                if name:
                    ctx.equipment_service.add_item(
                        name,
                        category=item_data.get("category"),
                        description=item_data.get("description"),
                    )

        for item_data in update_items:
            if isinstance(item_data, dict):
                name = item_data.get("name", "").strip()
                if name:
                    # Allowlist LLM-provided keys: they become SQL column names
                    # downstream (equipment_repo UPDATE SET clause).
                    allowed = {"item_name", "category", "description", "visual_desc", "quantity", "tags"}
                    updates = {k: v for k, v in item_data.items() if k in allowed and v is not None}
                    if updates:
                        ctx.equipment_service.update_item(name, **updates)

        if equip_map and isinstance(equip_map, dict):
            ctx.equipment_service.equip(equip_map)
        if unequip_list and isinstance(unequip_list, list):
            for slot in unequip_list:
                ctx.equipment_service.unequip([slot])

        # Optional reflection trigger: run reflection when 3+ facts extracted
        if len(facts) >= 3:
            try:
                importance_sum = sum(float(f.get("importance", 0.6)) for f in facts)
                from nous.application.chat.reflection import maybe_run_reflection

                await maybe_run_reflection(ctx, config, importance_sum)
            except Exception as ref_exc:
                logger.debug("run_memory_llm: reflection trigger skipped: %s", ref_exc)

        return result

    except Exception as e:
        logger.warning("run_memory_llm failed: %s", e)
        return {}
