"""``session_begin`` の notes — 沈黙の間を埋める（#37）。

どちらも begin の戻り値 ``notes: list[str]`` に 1 行ずつ載るだけ。生成に失敗しても
begin は成功させる（失敗は ``warning:`` 行として notes に残す）。

沈黙の判定は ``session_events`` の最後の ``session.stopped`` との差（新しいテーブルは作らない）。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from nous.domain.shared.result import Success
from nous.domain.shared.time_utils import get_now
from nous.infrastructure.llm.base import LLMMessage
from nous.infrastructure.llm.factory import get_provider
from nous.infrastructure.llm.text_utils import collect_text
from nous.infrastructure.logging.structured import get_logger
from nous.infrastructure.sqlite.session_event_repo import SessionEventRepository

if TYPE_CHECKING:
    from datetime import datetime

    from nous.application.use_cases import AppContext

logger = get_logger(__name__)

SILENCE_TAG = "life:between"
DEFAULT_SILENCE_HOURS = 6.0
SILENCE_MAX_CHARS = 200

_SILENCE_PROMPT = """\
あなたは{persona}。{hours:.1f}時間ぶりに相手が戻ってくる。
その間どう過ごしたか、一人称で2文だけ書け。出来事・体の調子・気分のどれかに触れる。
前置き・説明・箇条書きは書くな。{context}
[出力]
本文のみ。
"""


def _hours_since(then: datetime, now: datetime) -> float:
    """tz 無し（SQLite の保存値）と tz 有り（get_now）を混ぜても落ちない差。"""
    if (then.tzinfo is None) != (now.tzinfo is None):
        then = then.replace(tzinfo=None) if now.tzinfo is None else then.astimezone(now.tzinfo)
    return (now - then).total_seconds() / 3600.0


async def fill_silence(ctx: AppContext, persona: str, hours: float | None = None) -> str | None:
    """前回 ``session.stopped`` から *hours* 以上空いていれば記憶に1件落とす。

    戻り値は notes に足す行（失敗時のみ ``warning: ...``）。何もしない時は None。
    """
    # 閾値の優先度: 呼び出し側の hours 引数（session_events.py が Settings の
    # session_silence_hours を渡す）> ChatConfig の fill_silence_hours（persona 毎）
    # > 最終下限。Settings 側はセッション begin の運用値、ChatConfig 側は補完の
    # persona 既定で概念が違う（計画書 D2-12、命名で区別）。
    cfg_hours = getattr(ctx.config, "fill_silence_hours", None) if ctx.config is not None else None
    if hours is not None:
        limit = float(hours)
    elif cfg_hours is not None:
        limit = float(cfg_hours)
    else:
        limit = DEFAULT_SILENCE_HOURS
    now = get_now()
    try:
        last = SessionEventRepository(ctx.connection).last_event_at(persona, "session.stopped")
    except Exception as e:  # noqa: BLE001 — begin は落とさない
        logger.warning("fill_silence: last_event_at failed persona=%s: %s", persona, e)
        return f"warning: silence check failed: {e}"
    if last is None:
        return None
    gap = _hours_since(last, now)
    if gap < limit:
        return None

    text = await _generate(ctx, persona, gap)
    if text is None:
        return f"warning: silence memory skipped ({gap:.1f}h, LLM unavailable)"
    result = await ctx.memory_service.create_memory(content=text, importance=0.5, tags=[SILENCE_TAG], emotion="neutral")
    if not getattr(result, "is_ok", False):
        return f"warning: silence memory not stored: {getattr(result, 'error', None)}"
    logger.info("fill_silence: persona=%s gap=%.1fh stored", persona, gap)
    return None


async def _generate(ctx: AppContext, persona: str, gap: float) -> str | None:
    config = ctx.config
    if config is None:
        return None
    api_key = config.get_effective_api_key()
    model = config.extract_model.strip() or config.get_effective_model()
    if not api_key or not model:
        return None

    context = ""
    try:
        state_result = ctx.persona_service.get_context(persona)
        if isinstance(state_result, Success):
            bits = [
                str(getattr(state_result.value, key, "") or "") for key in ("environment", "emotion", "context_note")
            ]
            joined = " / ".join(b for b in bits if b)
            context = f"今の場所・気分: {joined}。" if joined else ""
    except Exception:  # noqa: BLE001 — 文脈は飾り
        context = ""

    prompt = _SILENCE_PROMPT.format(persona=persona, hours=gap, context=context)
    try:
        provider = get_provider(config.provider, api_key, model, config.get_effective_base_url())
        text = await collect_text(
            provider,
            messages=[LLMMessage(role="user", content=prompt)],
            system="",
            tools=[],
            temperature=0.9,
            max_tokens=160,
        )
    except Exception as e:  # noqa: BLE001 — 失敗は warning 行に落とす
        logger.warning("fill_silence: LLM failed persona=%s: %s", persona, e)
        return None
    flat = " ".join((text or "").split())
    return flat[:SILENCE_MAX_CHARS] or None
