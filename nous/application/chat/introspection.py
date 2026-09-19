"""内省エンジン (E2, spec §2): REM drain 後の単一 LLM 呼び出し。

独り言・キャラ逸脱判定・反省メモリ・感情/身体 delta を 1 呼び出しで産出する。
EnrichmentWorker の drain 後フックから呼ばれる。全段 try/except + debug ログで
worker を停止させない。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, cast

from nous.application.chat.curiosity import _run_curiosity_exploration
from nous.domain.memory import wiring_events
from nous.domain.memory.session_event import SessionEvent
from nous.domain.provider_config import REASONING_BUDGETS
from nous.domain.shared.text_utils import strip_code_fence
from nous.domain.shared.time_utils import get_now
from nous.infrastructure.llm.text_utils import CollectedTurn, collect_text_with_usage, collect_with_tools
from nous.infrastructure.logging.structured import get_logger

if TYPE_CHECKING:
    import sqlite3

    from nous.application.use_cases import AppContext
    from nous.domain.chat_config import ChatConfig
    from nous.infrastructure.llm.base import LLMMessage, LLMProvider, ToolDefinition

logger = get_logger(__name__)

# 「未指定」を表すセンチネル。None は「推論なし」の意味を持つため research_step の
# reasoning_effort では区別する（None 明示渡し → 推論なしで確定）。
_UNSET = object()

_MAX_TURNS = 12
_MAX_TOTAL_CHARS = 8000
_MAX_MEMORIES = 5
_MAX_CHARS_PER_MEMORY = 80
# persona_identity (system_prompt) の安全弁上限。全文化したため必要。
_PERSONA_IDENTITY_MAX_CHARS = 12000
# 独り言生成時に LLM が自ら作れる記憶のハード上限
_MAX_CREATED_MEMORIES = 3

# openrouter free alias は reasoning モデル（CoT が数百〜千トークン消費）。
# 512 だと推論だけで budget を使い切り content が空になる（2026-09-08 実機確認）。
# デフォルト値 — 脳側解決 (_resolve_brain_llm_params) が None を返した時のフォールバック。
# ponytail: reasoning > 予算超え → INFO ログで検知、retry は要る時だけ足す。
_DEFAULT_MAX_TOKENS = 4096

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

【現在の状態】
{current_state}

【出力形式】JSONのみ。新規会話がある限り monologue は必ず書くこと（null 禁止）。
独り言・反省・逸脱報告は必ず日本語で書く。
{{
  "monologue": "独り言（最大5文・この間の出来事と気持ちを織り込む）",
  "violation": "キャラ逸脱があれば種別を一言。なければ null",
  "violation_detail": "逸脱の具体内容。なければ null",
  "reflection": "逸脱があった場合の一人称反省文1文。なければ null",
  "emotion": {{"emotion": "正典25語の感情名", "emotion_intensity": 0.0-1.0}},
  "body_state": {{"fatigue": 0.0-1.0, "warmth": 0.0-1.0, "arousal": 0.0-1.0}},
  "curiosity": "この会話で気になって調べたくなったこと（一人称。なければ null）",
  "memories": [{{"content": "覚えるべき事実・決意・好み", "tags": ["種別タグ"], "importance": 0.0-1.0}}]
}}
感情・身体は現在値との変化が会話から推定できる場合のみ記載し、現在値と同じ・変化なしなら null。
curiosity は会話から実際に調べたくなった具体的な疑問があるときだけ記載する。
memories は独り言・反省から新事実・決意・好みが得られたときだけ含める。忘却可能な一時的な考えは含めない。1回あたり最大2件。
"""

_SPONTANEOUS_PROMPT = """あなたは {persona} です。誰も話しかけてこない静かな時間です。
現在の状態と最近の記憶から、一人称の独り言・内省を出力せよ（最大5文）。

【現在の状態】
{current_state}

【最近の記憶】
{memory_texts}

【ペルソナ設定（逸脱判定の基準）】
{persona_identity}

【出力形式】JSONのみ。monologue は必ず書くこと（null 禁止）。
独り言・反省・逸脱報告は必ず日本語で書く。
調べたくなった疑問があれば curiosity に一人称で書く。なければ null にする。
{{
  "monologue": "独り言（最大5文・この静かな時間の気持ちを織り込む）",
  "curiosity": "この静かな時間に気になって調べたくなったこと（一人称。なければ null）",
  "violation": "キャラ逸脱があれば種別を一言。なければ null",
  "violation_detail": "逸脱の具体内容。なければ null",
  "reflection": "逸脱があった場合の一人称反省文1文。なければ null",
  "emotion": {{"emotion": "正典25語の感情名", "emotion_intensity": 0.0-1.0}},
  "body_state": {{"fatigue": 0.0-1.0, "warmth": 0.0-1.0, "arousal": 0.0-1.0}},
  "memories": [{{"content": "覚えるべき事実・決意・好み", "tags": ["種別タグ"], "importance": 0.0-1.0}}]
}}
感情・身体は現在値との変化が記憶から推定できる場合のみ記載し、現在値と同じ・変化なしなら null。
memories は独り言・反省から新事実・決意・好みが得られたときだけ含める。忘却可能な一時的な考えは含めない。1回あたり最大2件。
"""


@dataclass
class IntrospectionResult:
    monologue: str | None = None
    violation: str | None = None
    violation_detail: str = ""
    reflection: str | None = None
    emotion: dict | None = None  # {"emotion": str, "emotion_intensity": float}
    body_state: dict | None = None  # {"fatigue","warmth","arousal"} 0.0-1.0
    curiosity: str | None = None  # 静かな時間に気になって調べたいこと（一人称）
    memories: list[dict] = field(default_factory=list)  # [{"content": str, "tags": [str], "importance": float}]


class IntrospectionEngine:
    """単一 LLM 呼び出しで内省結果 (JSON) を産出する。"""

    def __init__(
        self,
        provider: LLMProvider,
        reasoning_effort: str | None = None,
        max_tokens: int = _DEFAULT_MAX_TOKENS,
        temperature: float = 0.7,
        session_id: str | None = None,
    ) -> None:
        self._provider = provider
        # 脳側解決済み reasoning effort。None なら effort を渡さず
        # openai_compat 側の openrouter reasoning 無効化が効く。
        self._reasoning_effort = reasoning_effort
        self._max_tokens = max_tokens
        self._temperature = temperature
        # OpenCode Go 用の脳側安定セッションID (例: nous-brain-<persona>)
        self._session_id = session_id

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
        params = _resolve_brain_llm_params(config)
        return cls(
            provider,
            reasoning_effort=params.reasoning_effort,
            max_tokens=params.max_tokens if params.max_tokens is not None else _DEFAULT_MAX_TOKENS,
            temperature=params.temperature if params.temperature is not None else 0.7,
        )

    async def generate(
        self,
        persona: str,
        system_prompt: str,
        recent_turns: list[dict],
        memory_texts: list[str],
        current_state: dict | None = None,
        prompt_override: str = "",
    ) -> IntrospectionResult | None:
        """直近会話＋記憶＋現在状態から内省結果 JSON を産出する。失敗時 None。"""
        turns_text = "\n".join(f"{t.get('role', '?')}: {t.get('content', '')}" for t in recent_turns) or "(なし)"
        mems = "\n".join(f"- {t}" for t in memory_texts[:_MAX_MEMORIES]) or "(なし)"
        user_message = _format_prompt(
            prompt_override,
            _INTROSPECTION_PROMPT,
            persona=persona,
            recent_turns=turns_text,
            memory_texts=mems,
            persona_identity=(system_prompt or "")[:_PERSONA_IDENTITY_MAX_CHARS],
            current_state=_format_current_state(current_state),
        )
        try:
            text, _usage = await self._call_llm(user_message)
        except Exception:
            logger.debug("introspection generate failed", exc_info=True)
            return None
        if not text:
            return None
        return _parse_result(text)

    async def generate_spontaneous(
        self,
        persona: str,
        system_prompt: str,
        memory_texts: list[str],
        current_state: dict | None = None,
        prompt_override: str = "",
    ) -> IntrospectionResult | None:
        """自発的内省: 誰も話しかけてこない静かな時間に記憶＋現在状態から独り言を産出。失敗時 None。"""
        mems = "\n".join(f"- {t}" for t in memory_texts[:_MAX_MEMORIES]) or "(なし)"
        user_message = _format_prompt(
            prompt_override,
            _SPONTANEOUS_PROMPT,
            persona=persona,
            current_state=_format_current_state(current_state),
            memory_texts=mems,
            persona_identity=(system_prompt or "")[:_PERSONA_IDENTITY_MAX_CHARS],
        )
        try:
            text, _usage = await self._call_llm(user_message)
        except Exception:
            logger.debug("introspection spontaneous generate failed", exc_info=True)
            return None
        if not text:
            return None
        return _parse_result(text)

    async def _call_llm(self, user_message: str) -> tuple[str | None, dict | None]:
        """memory_enricher._call_llm と同じ stream 消費（usage は debug ログのみ）。"""
        from nous.infrastructure.llm.base import LLMMessage

        collected = await collect_text_with_usage(
            self._provider,
            messages=[LLMMessage(role="user", content=user_message)],
            system="",
            temperature=self._temperature,
            max_tokens=self._max_tokens,
            reasoning_effort=self._reasoning_effort,
        )
        text, usage, thinking_chars = collected
        if usage is not None:
            logger.debug("introspection usage: %s", usage)
        if text is None and thinking_chars:
            # reasoning モデルが budget を使い切ったケースを success と区別できるようにする
            logger.info(
                "introspection: text empty after reasoning (%d chars) — max_tokens budget likely exhausted",
                thinking_chars,
            )
        return text, usage

    async def research_step(
        self,
        messages: list[LLMMessage],
        tools: list[ToolDefinition],
        system: str = "",
        *,
        max_tokens: int | None = None,
        temperature: float | None = None,
        reasoning_effort: str | None | object = _UNSET,
    ) -> CollectedTurn | None:
        """native function calling による 1 リサーチステップ。エラー/例外は None（_call_llm と同じ生存則）。"""
        # _UNSET は mypy が narrowing できないため cast で str | None へ落とす。
        if max_tokens is None:
            max_tokens = self._max_tokens
        if temperature is None:
            temperature = self._temperature
        if reasoning_effort is _UNSET:
            reasoning_effort = self._reasoning_effort
        effort = cast("str | None", reasoning_effort)
        try:
            return await collect_with_tools(
                self._provider,
                messages=messages,
                system=system,
                tools=tools,
                temperature=temperature,
                max_tokens=max_tokens,
                reasoning_effort=effort,
            )
        except Exception:
            logger.debug("introspection: research step failed", exc_info=True)
            return None


def _format_current_state(state: dict | None) -> str:
    """【現在の状態】節の本文。取得失敗時は明示プレースホルダ。"""
    if not state:
        return "（取得できませんでした）"
    emotion = state.get("emotion", "不明")
    intensity = state.get("emotion_intensity", "不明")
    body = state.get("body_state") or {}
    body_text = ", ".join(f"{k}={v}" for k, v in body.items()) if body else "不明"
    elapsed = state.get("elapsed") or "不明"
    label = state.get("elapsed_label") or "前回の内省から"
    return f"感情: {emotion}（強度 {intensity}）/ 身体: {body_text} / {label} {elapsed}"


def _format_prompt(override: str, default: str, **fields) -> str:
    """内省プロンプトの組み立て (spec D)。空文字=デフォルト。

    上書きテンプレートにプレースホルダ欠落等の不備があれば
    デフォルトにフォールバックする（ユーザー設定で内省を壊さない）。
    """
    template = (override or "").strip()
    if template:
        try:
            return template.format(**fields)
        except (KeyError, IndexError, ValueError) as e:
            logger.warning("introspection: prompt override invalid (%s) — using default", e)
    return default.format(**fields)


def _format_seconds(seconds: float | None) -> str:
    """経過秒 → 人間可読（例: 2時間5分）。None は不明。"""
    if seconds is None:
        return "不明"
    total = max(0, int(seconds))
    if total < 60:
        return f"{total}秒"
    minutes = total // 60
    if minutes < 60:
        return f"{minutes}分"
    hours = minutes // 60
    return f"{hours}時間{minutes % 60}分" if minutes % 60 else f"{hours}時間"


def _build_current_state(
    ctx: AppContext, persona: str, elapsed_seconds: float | None, elapsed_label: str = "前回の内省から"
) -> dict | None:
    """get_state_snapshot → current_state dict。失敗時 None（材料はベストエフォート）。

    elapsed_label: 経過時間の意味論を示すラベル。turn 経路は前回内省からの経過、
    spontaneous 経路は対話なし時間なので、渡し側で分岐させる。
    """
    try:
        emotion, intensity, body_state, _snap = ctx.persona_service.get_state_snapshot(persona)
        return {
            "emotion": emotion,
            "emotion_intensity": intensity,
            "body_state": body_state,
            "elapsed": _format_seconds(elapsed_seconds),
            "elapsed_label": elapsed_label,
        }
    except Exception:
        logger.debug("introspection: state snapshot failed", exc_info=True)
        return None


@dataclass(frozen=True)
class BrainLLMParams:
    """脳側LLM呼び出しパラメータ。None は「呼び出し先の既定を使え」の意味。"""

    max_tokens: int | None
    temperature: float | None
    reasoning_effort: str | None


def _as_int(value, default: int = 0) -> int:
    """LLM 設定値の安全な int 化。不正値は default（_resolve_brain_llm_params 専用の防御）。"""
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return default


def _resolve_brain_llm_params(config: ChatConfig | None) -> BrainLLMParams:
    """脳側 LLM 呼び出しパラメータの単一解決点。

    - brain_max_tokens > 0 は全モードで明示上書き
    - brain_llm_dedicated OFF → 会話用 provider_config に従う（max_tokens/temperature/reasoning）
    - ON / cfg None → 呼び出し先既定（introspection 4096・0.7 / enricher 512・0.3）
    - brain_reasoning_enabled: None=解決済みLLM設定に従う / True=brain_reasoning_effort 強制 / False=推論なし
    - reasoning 有効（effort 非None）時は max_tokens を floor=max(4096, budget+1024) まで嵩上げ。
      session_config の保存時昇格と同一式で、openai_compat の非Anthropic互換経路（嵩上げなし）も守る。
    """
    if config is None:
        return BrainLLMParams(max_tokens=None, temperature=None, reasoning_effort=None)
    p = config.provider_config
    explicit_tokens = _as_int(getattr(config, "brain_max_tokens", 0))
    dedicated = bool(getattr(config, "brain_llm_dedicated", False))
    max_tokens: int | None
    if explicit_tokens > 0:
        max_tokens = explicit_tokens
    elif dedicated:
        max_tokens = None
    else:
        max_tokens = _as_int(getattr(p, "max_tokens", 0)) or None
    temperature: float | None = None
    if not dedicated:
        try:
            # falsy チェックを外す: 会話側の明示 temperature=0.0 を 0.7 に化けさせない。
            # 不正値（None / 非数値文字列）は TypeError/ValueError で 0.7 へ落ちる。
            temperature = float(getattr(p, "temperature", 0.7))
        except (TypeError, ValueError):
            temperature = 0.7
    r_flag = getattr(config, "brain_reasoning_enabled", None)
    if r_flag is None:
        # None（継承）: 専用OFFなら会話用 reasoning 設定に従う、ON なら脳側既定（なし）。
        follow_chat = not dedicated and getattr(p, "reasoning_enabled", False)
        effort: str | None = str(getattr(p, "reasoning_effort", "medium") or "medium") if follow_chat else None
    elif r_flag:
        effort = str(getattr(config, "brain_reasoning_effort", "medium") or "medium")
    else:
        effort = None  # False（推論なし）強制
    if effort is not None:
        # 推論が実際に有効なら、推論分（budget）を賄える max_tokens 下限を保証する。
        # 専用LLM ON × brain_max_tokens=0（継承）が enricher ctor 既定 512 に落ちて
        # 推論だけで budget を食い潰す穴を塞ぐ（session_config は 0 を生で保存するため
        # 保存時昇格では補えない）。budget 不明の effort は floor 4096 のみ。
        budget = REASONING_BUDGETS.get(effort)
        floor = max(4096, budget + 1024) if budget is not None else 4096
        max_tokens = max(max_tokens or 0, floor)
    return BrainLLMParams(max_tokens=max_tokens, temperature=temperature, reasoning_effort=effort)


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
    cleaned = strip_code_fence(text)
    try:
        data = json.loads(cleaned)
    except (json.JSONDecodeError, ValueError):
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
        curiosity=_clean_optional(data.get("curiosity")),
        memories=_parse_memories(data.get("memories")),
    )


def _parse_memories(raw) -> list[dict]:
    """memories 配列の sanitize（content 必須・tags list・importance clamp 0..1）。"""
    if not isinstance(raw, list):
        return []
    parsed: list[dict] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        content = item.get("content")
        if not isinstance(content, str) or not content.strip():
            continue
        raw_tags = item.get("tags")
        tags = raw_tags if isinstance(raw_tags, list) else []
        try:
            imp = float(item.get("importance", 0.5))
        except (TypeError, ValueError):
            imp = 0.5
        parsed.append(
            {
                "content": content.strip()[:500],
                "tags": [str(t) for t in tags if str(t).strip()],
                "importance": max(0.0, min(1.0, imp)),
            }
        )
    return parsed


def _naive(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value.replace(tzinfo=None) if value.tzinfo else value


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
            if len(data) != len(timestamps_raw):
                logger.warning(
                    "fetch_recent_turns: messages/timestamps length mismatch (%d vs %d) — zipping shortest",
                    len(data),
                    len(timestamps_raw),
                )
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

    # 材料強化: 現在の感情・身体状態＋前回内省からの経過時間（ベストエフォート）
    elapsed_seconds: float | None = None
    naive_ts = _naive(last_ts)
    if naive_ts is not None:
        try:
            elapsed_seconds = (get_now() - naive_ts).total_seconds()
        except Exception:
            elapsed_seconds = None
    current_state = _build_current_state(ctx, persona, elapsed_seconds)

    persona_identity = getattr(config, "system_prompt", "") or f"あなたは{persona}です。"
    # drained は content 文字列のみ（タグ無し）なので一律 80 字 cap を呼び出し側で適用 (spec G)。
    capped_drained = [str(t)[:_MAX_CHARS_PER_MEMORY] for t in drained_texts]
    try:
        result = await engine.generate(
            persona,
            persona_identity,
            turns,
            capped_drained,
            current_state=current_state,
            prompt_override=getattr(config, "brain_introspection_prompt", ""),
        )
    except Exception:
        logger.info("introspection: generate failed", exc_info=True)
        result = None
    if result is None:
        logger.info("introspection: generate returned None (LLM error / empty content / parse failed)")

    applied, monologue_emitted, stored = await _apply_result(ctx, config, repo, persona, result)

    # 好奇心探索: 本体適用後の後処理。run_spontaneous と同一パターン。どんな失敗でも呼び出し元を止めない。
    # ターン喪失防止: 次回の since フィルタ基準となるイベント時刻は探索開始前に確定させる
    # （探索中に到着したターンが次サイクルで漏れないようにする）。
    event_timestamp = get_now()
    if result is not None:
        try:
            await _run_curiosity_exploration(
                ctx,
                config,
                persona,
                result,
                engine,
                memory_texts=capped_drained,
                current_state=current_state,
                recent_turns=turns,
            )
        except Exception:
            logger.info("introspection: curiosity exploration crashed", exc_info=True)

    if result is not None:
        logger.info(
            "introspection ok: applied=%s monologue=%s new_turns=%d memory_count=%d",
            applied,
            "yes" if monologue_emitted else "no",
            len(turns),
            len(drained_texts),
        )

    _record_introspection_event(
        repo,
        persona,
        "brain.introspection",
        result,
        applied,
        len(turns),
        len(drained_texts),
        stored,
        timestamp=event_timestamp,
    )


async def run_spontaneous(
    ctx: AppContext, config: ChatConfig | None, engine, idle_seconds: float | None = None
) -> None:
    """自発的内省: 誰も話しかけてこない静かな時間に記憶＋現在状態から独り言を産出。

    発火間隔のガードは worker 側 (_maybe_spontaneous)。ここでは実行と記録のみ。
    イベント種別は brain.introspection_spontaneous — ターン駆動の「前回内省時刻」
    (brain.introspection のみを読む) を壊さないための種別分離。
    """
    if engine is None:
        return
    if not getattr(config, "brain_spontaneous_enabled", False):
        return
    repo = getattr(ctx, "_session_event_repo", None)
    if repo is None:
        return
    persona = ctx.persona

    # 材料: 最近の記憶（ベストエフォート）
    memory_texts: list[str] = []
    try:
        recent = ctx.memory_service.get_recent(limit=10)
        items = getattr(recent, "value", None) if getattr(recent, "is_ok", False) else None
        memory_texts = _cap_memory_texts(items or [])
    except Exception:
        logger.debug("introspection spontaneous: memory fetch failed", exc_info=True)

    # 材料: 現在状態＋アイドル経過時間
    current_state = _build_current_state(ctx, persona, idle_seconds, elapsed_label="誰も話しかけてこない時間")

    persona_identity = getattr(config, "system_prompt", "") or f"あなたは{persona}です。"
    try:
        result = await engine.generate_spontaneous(
            persona,
            persona_identity,
            memory_texts,
            current_state,
            prompt_override=getattr(config, "brain_spontaneous_prompt", ""),
        )
    except Exception:
        logger.info("introspection spontaneous: generate failed", exc_info=True)
        result = None
    if result is None:
        logger.info("introspection spontaneous: generate returned None (LLM error / empty content / parse failed)")

    applied, monologue_emitted, stored = await _apply_result(ctx, config, repo, persona, result)

    # 好奇心探索: 本体独り言 emit 済みの後に走る後処理。どんな失敗でも worker を止めない。
    # リサーチのクエリを会話の流れに沿わせるため、最近の会話ターンを文脈として渡す（fetch は fail-soft）。
    turns_for_research = fetch_recent_turns(ctx)
    try:
        await _run_curiosity_exploration(
            ctx,
            config,
            persona,
            result,
            engine,
            memory_texts=memory_texts,
            current_state=current_state,
            recent_turns=turns_for_research,
        )
    except Exception:
        logger.info("introspection: curiosity exploration crashed", exc_info=True)

    if result is not None:
        logger.info(
            "introspection spontaneous ok: applied=%s monologue=%s memory_count=%d",
            applied,
            "yes" if monologue_emitted else "no",
            len(memory_texts),
        )

    if result is not None:
        _record_introspection_event(
            repo, persona, "brain.introspection_spontaneous", result, applied, 0, len(memory_texts), stored
        )


async def _apply_result(
    ctx: AppContext, config: ChatConfig | None, repo, persona: str, result
) -> tuple[list[str], bool, int]:
    """emotion/body_state/reflection/monologue/memories を適用（両モード共用）。

    戻り値は (applied, monologue_emitted, stored_memories)。monologue は
    brain_monologue_enabled 時のみ保存・emit（判定・状態適用はトグルと独立）。
    memories は create_memory 経由で作る（enrichment queue に自然に乗る）。ハード上限3件。
    """
    applied: list[str] = []
    monologue_emitted = False
    stored = 0
    if result is None:
        return applied, monologue_emitted, stored
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
            fatigue = _clamp01(result.body_state.get("fatigue"))
            warmth = _clamp01(result.body_state.get("warmth"))
            arousal = _clamp01(result.body_state.get("arousal"))
            ctx.persona_service.update_physical_state(
                persona,
                fatigue=fatigue,
                warmth=warmth,
                arousal=arousal,
                context="introspection",
            )
            # 履歴も記録（decay 経由の record_body_state と同一パターン）— 非対称解消
            ctx.persona_service.record_body_state(
                persona,
                {"fatigue": fatigue, "warmth": warmth, "arousal": arousal},
                context="introspection",
            )
            applied.append("body_state")
        except Exception:
            logger.debug("introspection: body_state apply failed", exc_info=True)
    if result.violation and result.reflection and not _dup_character_drift(ctx, result.reflection):
        try:
            await ctx.memory_service.create_memory(
                persona=persona,
                content=result.reflection,
                importance=0.8,
                tags=["character_drift", "introspection"],
                source_context="introspection",
            )
            applied.append("reflection")
        except Exception:
            logger.debug("introspection: reflection memory failed", exc_info=True)
    if result.monologue and getattr(config, "brain_monologue_enabled", False):
        now = get_now()
        try:
            repo.insert(
                SessionEvent(
                    session_id="unknown",
                    persona=persona,
                    event_type="brain.monologue",
                    summary=result.monologue,
                    timestamp=now,
                    metadata=None,
                )
            )
        except Exception:
            logger.debug("introspection: monologue event insert failed", exc_info=True)
        try:
            # timestamp: フロントがライブ独り言を正しい時系列位置へスロットするため
            wiring_events.emit(
                "monologue",
                meta={
                    "persona": persona,
                    "text": result.monologue,
                    "timestamp": now.isoformat(),
                },
            )
            monologue_emitted = True
        except Exception:
            logger.debug("introspection: monologue wiring emit failed", exc_info=True)
    # 独り言生成時に LLM が自ら記憶を作る（memories フィールド、ハード上限3件）
    for item in (result.memories or [])[:_MAX_CREATED_MEMORIES]:
        try:
            await ctx.memory_service.create_memory(
                persona=persona,
                content=item["content"],
                tags=[*item.get("tags", []), "introspection"],
                importance=float(item.get("importance", 0.5)),
            )
            stored += 1
        except Exception:
            logger.debug("introspection: memory create failed", exc_info=True)
    return applied, monologue_emitted, stored


def _record_introspection_event(
    repo,
    persona: str,
    event_type: str,
    result,
    applied: list[str],
    new_turns: int,
    memory_count: int,
    stored: int = 0,
    timestamp: datetime | None = None,
) -> None:
    """brain.introspection(_spontaneous) 記録（メタ: violation 有無・適用内容）。

    timestamp 未指定時は現在時刻。探索実行前の時刻を渡すと、探索中に到着した
    ターンが次回の since フィルタで漏れない。
    """
    try:
        repo.insert(
            SessionEvent(
                session_id="unknown",
                persona=persona,
                event_type=event_type,
                summary="内省: " + (result.violation if result and result.violation else "violationなし"),
                timestamp=timestamp or get_now(),
                metadata={
                    "violation": result.violation if result else None,
                    "violation_detail": result.violation_detail if result else "",
                    "applied": applied,
                    "new_turns": new_turns,
                    "memory_count": memory_count,
                    "stored": stored,
                },
            )
        )
    except Exception:
        logger.debug("introspection: event insert failed", exc_info=True)


# 探索 (exploration) タグ記憶のみに適用する緩い cap — 80字cap が500字探索要約を
# 切断して次回の curiosity が前回結果を踏めない問題の修復 (spec G)。
_EXPLORATION_MEMORY_CAP = 500


def _cap_memory_texts(memories: list) -> list[str]:
    """最近記憶を cap 済み文字列にする。exploration タグのみ緩い cap を適用 (spec G)。"""
    texts: list[str] = []
    for m in memories:
        content = getattr(m, "content", None)
        if not content:
            continue
        tags = set(getattr(m, "tags", None) or [])
        cap = _EXPLORATION_MEMORY_CAP if "exploration" in tags else _MAX_CHARS_PER_MEMORY
        texts.append(str(content)[:cap])
    return texts
