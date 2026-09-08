"""内省エンジン (E2, spec §2): REM drain 後の単一 LLM 呼び出し。

独り言・キャラ逸脱判定・反省メモリ・感情/身体 delta を 1 呼び出しで産出する。
EnrichmentWorker の drain 後フックから呼ばれる。全段 try/except + debug ログで
worker を停止させない。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING

from nous.domain.memory import wiring_events
from nous.domain.memory.session_event import SessionEvent
from nous.domain.shared.time_utils import get_now
from nous.infrastructure.logging.structured import get_logger

if TYPE_CHECKING:
    import sqlite3

    from nous.application.use_cases import AppContext
    from nous.domain.chat_config import ChatConfig
    from nous.infrastructure.llm.base import LLMProvider

logger = get_logger(__name__)

_MAX_TURNS = 12
_MAX_TOTAL_CHARS = 8000
_MAX_MEMORIES = 5
_MAX_CHARS_PER_MEMORY = 80
# openrouter free alias は reasoning モデル（CoT が数百〜千トークン消費）。
# 512 だと推論だけで budget を使い切り content が空になる（2026-09-08 実機確認）。
# ponytail: reasoning > ~1800 tokens で budget 溢れ → INFO ログで検知、retry は要る時だけ足す。
_MAX_TOKENS = 2048

_CHAT_SESSIONS_SCHEMA = (
    "CREATE TABLE IF NOT EXISTS chat_sessions ("
    "persona TEXT NOT NULL, session_id TEXT NOT NULL, "
    "messages TEXT NOT NULL DEFAULT '[]', timestamps TEXT NOT NULL DEFAULT '[]', "
    "updated_at TEXT NOT NULL, PRIMARY KEY (persona, session_id))"
)

_INTROSPECTION_PROMPT = """あなたは {persona} です。
以下の資料から、一人称の独り言・内省結果を出力せよ。

【最近の会話】
{recent_turns}

【この間に記憶に刻んだこと】
{memory_texts}

【ペルソナ設定（逸脱判定の基準）】
{persona_identity}

【出力形式】JSONのみ。新規会話がある限り monologue は必ず書くこと（null 禁止）。
{{
  "monologue": "独り言（最大5文・この間の出来事と気持ちを織り込む）",
  "violation": "キャラ逸脱があれば種別を一言。なければ null",
  "violation_detail": "逸脱の具体内容。なければ null",
  "reflection": "逸脱があった場合の一人称反省文1文。なければ null",
  "emotion": {{"emotion": "正典25語の感情名", "emotion_intensity": 0.0-1.0}},
  "body_state": {{"fatigue": 0.0-1.0, "warmth": 0.0-1.0, "arousal": 0.0-1.0}}
}}
感情・身体は会話から自然に推定した場合のみ記載し、変化なしなら null。
"""


@dataclass
class IntrospectionResult:
    monologue: str | None = None
    violation: str | None = None
    violation_detail: str = ""
    reflection: str | None = None
    emotion: dict | None = None  # {"emotion": str, "emotion_intensity": float}
    body_state: dict | None = None  # {"fatigue","warmth","arousal"} 0.0-1.0


class IntrospectionEngine:
    """単一 LLM 呼び出しで内省結果 (JSON) を産出する。"""

    def __init__(self, provider: LLMProvider, reasoning_effort: str | None = None) -> None:
        self._provider = provider
        # 脳専用 reasoning トグル (chat の reasoning とは独立)。None なら effort を渡さず
        # openai_compat 側の openrouter reasoning 無効化が効く。
        self._reasoning_effort = reasoning_effort

    @classmethod
    def from_config(cls, config: ChatConfig | None, settings=None) -> IntrospectionEngine | None:
        """brain 解決鎖 (use_cases._init_enricher と同一): ON→専用5キー / OFF→chat 4点 / cfg None→settings 鎖。"""
        try:
            if settings is None:
                from nous.config.settings import get_settings

                settings = get_settings()
            provider_name, api_key, model, base_url = _resolve_llm_config(config, settings)
        except Exception:
            logger.debug("introspection engine resolve failed", exc_info=True)
            return None
        if not api_key or not model:
            return None
        from nous.infrastructure.llm.factory import get_provider

        try:
            provider = get_provider(provider=provider_name, api_key=api_key, model=model, base_url=base_url)
        except Exception:
            logger.debug("introspection provider init failed", exc_info=True)
            return None
        return cls(provider, reasoning_effort=_brain_reasoning_effort(config))

    async def generate(
        self,
        persona: str,
        system_prompt: str,
        recent_turns: list[dict],
        memory_texts: list[str],
    ) -> IntrospectionResult | None:
        """直近会話＋記憶から内省結果 JSON を産出する。失敗時 None。"""
        turns_text = "\n".join(f"{t.get('role', '?')}: {t.get('content', '')}" for t in recent_turns) or "(なし)"
        mems = "\n".join(f"- {t[:_MAX_CHARS_PER_MEMORY]}" for t in memory_texts[:_MAX_MEMORIES]) or "(なし)"
        user_message = _INTROSPECTION_PROMPT.format(
            persona=persona,
            recent_turns=turns_text,
            memory_texts=mems,
            persona_identity=(system_prompt or "")[:2000],
        )
        try:
            text, _usage = await self._call_llm(user_message)
        except Exception:
            logger.debug("introspection generate failed", exc_info=True)
            return None
        if not text:
            return None
        return _parse_result(text)

    async def _call_llm(self, user_message: str) -> tuple[str | None, dict | None]:
        """memory_enricher._call_llm と同じ stream 消費パターン (usage は debug ログのみ)。"""
        from nous.infrastructure.llm.base import (
            DoneEvent,
            ErrorEvent,
            LLMMessage,
            TextDeltaEvent,
            ThinkingDeltaEvent,
        )

        parts: list[str] = []
        usage: dict | None = None
        thinking_chars = 0
        async for event in self._provider.stream(
            messages=[LLMMessage(role="user", content=user_message)],
            system="",
            temperature=0.7,
            max_tokens=_MAX_TOKENS,
            reasoning_effort=self._reasoning_effort,
        ):
            if isinstance(event, TextDeltaEvent):
                parts.append(event.content)
            elif isinstance(event, ThinkingDeltaEvent):
                thinking_chars += len(event.content)
            elif isinstance(event, ErrorEvent):
                logger.debug("introspection LLM stream error: %s", event.message)
                return None, None
            elif isinstance(event, DoneEvent):
                usage = event.usage
                logger.debug("introspection usage: %s", usage)
        text = "".join(parts) if parts else None
        if text is None and thinking_chars:
            # reasoning モデルが budget を使い切ったケースを success と区別できるようにする
            logger.info(
                "introspection: text empty after reasoning (%d chars) — max_tokens budget likely exhausted",
                thinking_chars,
            )
        return text, usage


def _brain_reasoning_effort(config: ChatConfig | None) -> str | None:
    """脳専用 reasoning トグル → stream に渡す effort。OFF/未設定は None。"""
    if config is None or not getattr(config, "brain_reasoning_enabled", False):
        return None
    return str(getattr(config, "brain_reasoning_effort", "medium") or "medium")


def _resolve_llm_config(config: ChatConfig | None, settings) -> tuple[str, str, str, str]:
    """(provider, api_key, model, base_url)。_init_enricher の解決鎖を踏襲。"""
    if config is None:
        me = settings.memory_enrichment
        return me.provider, me.get_effective_api_key(settings), me.model, me.base_url
    if not config.brain_llm_dedicated:
        p = config.provider_config
        return p.provider, p.get_effective_api_key(), p.get_effective_model(), p.get_effective_base_url()
    me = settings.memory_enrichment
    provider = config.brain_llm_provider or me.provider
    model = config.brain_llm_model or me.model
    base_url = config.brain_llm_base_url or me.base_url
    api_key = config.brain_llm_api_key or me.get_effective_api_key(settings)
    if not api_key and provider == config.provider_config.provider:
        api_key = config.provider_config.get_effective_api_key()
    return provider, api_key, model, base_url


def _clean_optional(value) -> str | None:
    """文字列 "null"/"none"/空 を None に正規化（モデルが JSON null でなく文字列を返すことがある）。"""
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    if not stripped or stripped.lower() in ("null", "none"):
        return None
    return stripped


def _parse_result(text: str) -> IntrospectionResult | None:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        lines = cleaned.splitlines()
        cleaned = "\n".join(lines[1:-1] if lines[-1].startswith("```") else lines[1:])
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        logger.debug("introspection JSON parse failed: %s", text[:200])
        return None
    if not isinstance(data, dict):
        return None
    violation = _clean_optional(data.get("violation"))
    detail = _clean_optional(data.get("violation_detail")) if violation else None
    reflection = _clean_optional(data.get("reflection"))
    monologue = _clean_optional(data.get("monologue"))
    emotion = data.get("emotion") if isinstance(data.get("emotion"), dict) else None
    body_state = data.get("body_state") if isinstance(data.get("body_state"), dict) else None
    return IntrospectionResult(
        monologue=monologue,
        violation=violation,
        violation_detail=detail.strip() if isinstance(detail, str) else "",
        reflection=reflection,
        emotion=emotion,
        body_state=body_state,
    )


def _naive(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value.replace(tzinfo=None) if value.tzinfo is not None else value


def fetch_recent_turns(ctx: AppContext, since: datetime | None = None) -> list[dict]:
    """chat_sessions 直近12メッセージ(user+assistant)を時刻順に。合計8000字cap。since があれば time > since のみ。"""
    try:
        db: sqlite3.Connection = ctx.connection.get_memory_db()
        db.execute(_CHAT_SESSIONS_SCHEMA)
        row = db.execute(
            "SELECT messages, timestamps FROM chat_sessions WHERE persona=? AND session_id=?",
            (ctx.persona, "main"),
        ).fetchone()
        if row is None:
            return []
        messages_raw = row[0] if not hasattr(row, "keys") else row["messages"]
        data = json.loads(messages_raw)
        entries: list[tuple[datetime, str, str]] = []  # (naive ts, role, content)
        if isinstance(data, dict):
            # 新形式: ツリー → active_path 再構築 (SessionManager.get_messages と同一経路・created_at 保持版)
            nodes = {n["id"]: n for n in data.get("nodes", [])}
            current = data.get("active_leaf_id")
            path: list[dict] = []
            while current is not None:
                node = nodes.get(current)
                if node is None:
                    break
                path.append(node)
                current = node.get("parent_id")
            path.reverse()
            for node in path:
                _append_entry(entries, node.get("role"), node.get("content"), node.get("created_at"))
        elif isinstance(data, list):
            timestamps_raw = json.loads(row[1] if not hasattr(row, "keys") else row["timestamps"])
            for msg, ts_str in zip(data, timestamps_raw, strict=False):
                _append_entry(entries, msg.get("role"), msg.get("content"), ts_str)
    except Exception:
        logger.debug("fetch_recent_turns failed", exc_info=True)
        return []

    since_naive = _naive(since)
    if since_naive is not None:
        entries = [e for e in entries if e[0] > since_naive]
    entries.sort(key=lambda e: e[0])
    entries = entries[-_MAX_TURNS:]
    # 合計 8000 字 cap（新しい方から残す）
    kept: list[tuple[datetime, str, str]] = []
    total = 0
    for entry in reversed(entries):
        if total + len(entry[2]) > _MAX_TOTAL_CHARS and kept:
            break
        kept.append(entry)
        total += len(entry[2])
    kept.reverse()
    return [{"role": role, "content": content} for _ts, role, content in kept]


def _append_entry(entries: list[tuple[datetime, str, str]], role, content, ts) -> None:
    if role not in ("user", "assistant") or not content:
        return
    if not isinstance(ts, str):
        return
    try:
        entries.append(
            (
                datetime.fromisoformat(ts).replace(tzinfo=None)
                if datetime.fromisoformat(ts).tzinfo
                else datetime.fromisoformat(ts),
                str(role),
                str(content),
            )
        )
    except ValueError:
        return


def _clamp01(value) -> float | None:
    if value is None:
        return None
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return None


def _dup_character_drift(ctx: AppContext, reflection: str) -> bool:
    """同一文の character_drift メモリが既存なら True（重複禁止）。"""
    try:
        result = ctx.memory_service.get_by_tags(["character_drift"])
        items = getattr(result, "value", None) if getattr(result, "is_ok", False) else None
        for item in items or []:
            if getattr(item, "content", None) == reflection:
                return True
    except Exception:
        logger.debug("character_drift dedupe check failed", exc_info=True)
    return False


async def run_introspection(ctx: AppContext, config: ChatConfig | None, engine, drained_texts: list[str]) -> None:
    """ガード→ターン取得→generate→適用（全段 try/except、worker停止しない）。"""
    if engine is None:
        logger.info("introspection: engine not configured — skip")
        return
    if not getattr(config, "brain_introspection_enabled", False):
        return
    repo = getattr(ctx, "_session_event_repo", None)
    if repo is None:
        return
    persona = ctx.persona

    # 前回内省時刻以降の新規ターンのみ対象 (spec §2)
    last_ts: datetime | None = None
    try:
        events = repo.get_by_persona(persona, "brain.introspection", 1)
        if events:
            last_ts = events[0].timestamp
    except Exception:
        logger.debug("introspection: last timestamp fetch failed", exc_info=True)
    try:
        turns = fetch_recent_turns(ctx, since=_naive(last_ts))
    except Exception:
        logger.debug("introspection: turn fetch failed", exc_info=True)
        return
    if not turns:
        return

    persona_identity = getattr(config, "system_prompt", "") or f"あなたは{persona}です。"
    try:
        result = await engine.generate(persona, persona_identity, turns, drained_texts)
    except Exception:
        logger.info("introspection: generate failed", exc_info=True)
        result = None
    if result is None:
        logger.info("introspection: generate returned None (LLM error / empty content / parse failed)")

    applied: list[str] = []
    monologue_emitted = False
    if result is not None:
        if result.emotion:
            try:
                ctx.persona_service.update_emotion(
                    persona,
                    str(result.emotion.get("emotion", "neutral")),
                    float(result.emotion.get("emotion_intensity", 0.0)),
                    context="introspection",
                )
                applied.append("emotion")
            except Exception:
                logger.debug("introspection: emotion apply failed", exc_info=True)
        if result.body_state:
            try:
                ctx.persona_service.update_physical_state(
                    persona,
                    fatigue=_clamp01(result.body_state.get("fatigue")),
                    warmth=_clamp01(result.body_state.get("warmth")),
                    arousal=_clamp01(result.body_state.get("arousal")),
                    context="introspection",
                )
                applied.append("body_state")
            except Exception:
                logger.debug("introspection: body_state apply failed", exc_info=True)
        if result.violation and result.reflection and not _dup_character_drift(ctx, result.reflection):
            try:
                await ctx.memory_service.create_memory(
                    content=result.reflection,
                    importance=0.8,
                    tags=["character_drift", "introspection"],
                    source_context="introspection",
                )
                applied.append("reflection")
            except Exception:
                logger.debug("introspection: reflection memory failed", exc_info=True)
        # monologue: brain_monologue_enabled 時のみ保存・emit（判定・状態適用はトグルと独立）
        if result.monologue and getattr(config, "brain_monologue_enabled", False):
            try:
                repo.insert(
                    SessionEvent(
                        session_id="unknown",
                        persona=persona,
                        event_type="brain.monologue",
                        summary=result.monologue,
                        timestamp=get_now(),
                        metadata=None,
                    )
                )
            except Exception:
                logger.debug("introspection: monologue event insert failed", exc_info=True)
            try:
                wiring_events.emit("monologue", meta={"persona": persona, "text": result.monologue})
                monologue_emitted = True
            except Exception:
                logger.debug("introspection: monologue wiring emit failed", exc_info=True)

    if result is not None:
        logger.info(
            "introspection ok: applied=%s monologue=%s new_turns=%d memory_count=%d",
            applied or [],
            "yes" if monologue_emitted else "no",
            len(turns),
            len(drained_texts),
        )

    # brain.introspection 記録（メタ: violation 有無・適用内容）
    try:
        repo.insert(
            SessionEvent(
                session_id="unknown",
                persona=persona,
                event_type="brain.introspection",
                summary="内省: " + (result.violation if result and result.violation else "violationなし"),
                timestamp=get_now(),
                metadata={
                    "violation": result.violation if result else None,
                    "violation_detail": result.violation_detail if result else "",
                    "applied": applied,
                    "new_turns": len(turns),
                    "memory_count": len(drained_texts),
                },
            )
        )
    except Exception:
        logger.debug("introspection: event insert failed", exc_info=True)
