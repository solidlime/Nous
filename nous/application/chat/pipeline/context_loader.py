"""コンテキスト読み込み — context section, time context, relationship context 構築。"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from nous.domain.shared.result import Success
from nous.domain.shared.time_utils import get_now, relative_time_str
from nous.infrastructure.logging.structured import get_logger

if TYPE_CHECKING:
    from nous.application.chat.pipeline.context import ChatTurnContext
    from nous.application.use_cases import AppContext

logger = get_logger(__name__)

# Byte-level BPEトークナイザ由来の文字化けで発生しうる異常Unicodeブロック。
# 通常の日本語/英語テキストでは出現しないスクリプトを広くカバーする。
_SUSPICIOUS_RANGES: list[tuple[int, int]] = [
    (0x0400, 0x04FF),  # Cyrillic
    (0x0600, 0x06FF),  # Arabic
    (0x07C0, 0x07FF),  # N'Ko
    (0x10A0, 0x10FF),  # Georgian
    (0x1100, 0x11FF),  # Hangul Jamo
    (0x1200, 0x137F),  # Ethiopic
    (0x1380, 0x139F),  # Ethiopic Supplement
    (0x1400, 0x167F),  # Canadian Aboriginal Syllabics
    (0x1800, 0x18AF),  # Mongolian
    (0x1980, 0x19DF),  # New Tai Lue
    (0x1A00, 0x1A1F),  # Buginese
    (0x1A20, 0x1AAF),  # Tai Tham
    (0x1B80, 0x1BBF),  # Sundanese
    (0x1BC0, 0x1BFF),  # Batak
    (0x2D80, 0x2DDF),  # Ethiopic Extended
    (0x2E80, 0x2EFF),  # CJK Radicals Supplement
    (0x2F00, 0x2FDF),  # Kangxi Radicals
    (0xA000, 0xA48F),  # Yi Syllables
    (0xD800, 0xDFFF),  # Surrogates (lone surrogates)
    (0xE000, 0xF8FF),  # Private Use Area
]


def _is_suspicious_cp(cp: int) -> bool:
    """Return True if the Unicode code point falls in a known suspicious block."""
    return any(lo <= cp <= hi for lo, hi in _SUSPICIOUS_RANGES)


def _build_relationship_context(ctx: AppContext) -> str:
    """Build relationship context summary from interaction history.
    Returns empty string if no interaction history exists."""
    db = ctx.connection.get_memory_db()
    persona = ctx.persona

    # First interaction time
    row = db.execute(
        "SELECT MIN(created_at) FROM session_events WHERE persona = ?",
        (persona,),
    ).fetchone()
    first_at_str = row[0] if row and row[0] else None
    if not first_at_str:
        return ""  # No history at all

    first_at = datetime.fromisoformat(first_at_str)
    now = datetime.now(UTC)
    days_known = (now - first_at.replace(tzinfo=UTC)).days

    # Active days (distinct dates with events)
    row = db.execute(
        "SELECT COUNT(DISTINCT DATE(created_at)) FROM session_events WHERE persona = ?",
        (persona,),
    ).fetchone()
    active_days = row[0] if row else 0

    lines = ["\n--- 関係性コンテキスト ---"]
    if days_known == 0:
        lines.append("このユーザーと初めて会話する。")
    elif days_known == 1:
        lines.append(f"昨日から知り合った。これまで {active_days} 日会話した。")
    else:
        lines.append(f"{days_known}日前から知り合い。これまで {active_days} 日会話した。")

    return "\n".join(lines)


async def _build_context_section(
    ctx: AppContext,
    state,
    turn_ctx: ChatTurnContext | None = None,
    compress_mode: str = "auto",
    decay_note: str = "",
) -> str:
    """get_context() 同等の充実したコンテキストサマリーを構築する。

    compress_mode が "light"/"normal"/"aggressive" の場合は、
    重いセクション（reflection insight, mental model, session summary, emotion history）をスキップする。
    """

    def _sanitize_text(text: str) -> str:
        """LLMのByte-level BPEトークナイザ由来の文字化けを検出・除去する。
        通常の日本語/英語テキストでは出現しない異常Unicodeブロック（N'Ko, Mongolian,
        PUA, Surrogates）の文字が10%以上ならテキスト全体を破棄、それ未満なら該当文字のみ除去。"""
        if not text:
            return text
        suspicious = [ch for ch in text if _is_suspicious_cp(ord(ch))]
        if suspicious:
            ratio = len(suspicious) / len(text)
            if ratio > 0.1:
                logger.warning(
                    "_sanitize_text: discarding text with %.0f%% suspicious chars (%d/%d)",
                    ratio * 100,
                    len(suspicious),
                    len(text),
                )
                return ""
            sanitized = "".join(ch for ch in text if not _is_suspicious_cp(ord(ch)))
            logger.info("_sanitize_text: removed %d suspicious chars (%.0f%%)", len(text) - len(sanitized), ratio * 100)
            return sanitized
        return text

    t1: list[str] = []  # Tier 1: 現在の状態
    t2: list[str] = []  # Tier 2: 身体・環境
    t3: list[str] = []  # Tier 3: 参照情報
    _is_light = compress_mode == "light"
    if _is_light:
        logger.info("context section light skip drift=light_skip (drift/reflection sections skipped)")

    # === Tier 1: 現在の状態 ===
    # 時間情報は <TIME_CONTEXT> ブロック（システムプロンプト先頭）を参照
    if getattr(state, "emotion", None):
        # f2: 欠損・範囲外・非数値を境界で正規化
        from nous.domain.value_objects import normalize_importance

        try:
            _raw_int = getattr(state, "emotion_intensity", 0.5)
            intensity = normalize_importance(float(_raw_int) if _raw_int is not None else None)
        except (TypeError, ValueError):
            intensity = 0.5
        intensity_label = "強い" if intensity > 0.6 else "やや強い" if intensity > 0.3 else "弱い"
        t1.append(f"感情: {state.emotion}（{intensity_label}）")

    # === Tier 2: 身体・環境 ===
    # 減衰ノート（感情・身体・関係性、複数行可）
    if decay_note:
        note_lines = "\n".join(f"  {line}" for line in decay_note.split("\n") if line)
        t2.append(f"⏱️ 状態変化:\n{note_lines}")

    # Body state — show all 5 metrics with percentages (unified with MCP tools format)
    from nous.api.mcp._tools_helpers import _format_body_metrics

    body_str = _format_body_metrics(
        state,
        labels={"fatigue": "疲労", "warmth": "体温", "arousal": "覚醒", "heart_rate": "心拍", "pain": "痛み"},
    )
    if body_str:
        t2.append(f"身体: {body_str}")

    if getattr(state, "environment", None):
        t2.append(f"場所: {state.environment}")

    if getattr(state, "relationship_status", None):
        t2.append(f"関係: {state.relationship_status}")

    # Add relationship context (days known, active days, time since last)
    try:
        rel_ctx = _build_relationship_context(ctx)
        if rel_ctx:
            # Extract just the content (remove the "--- 関係性コンテキスト ---" header)
            rel_lines = rel_ctx.split("\n")
            if len(rel_lines) > 1:
                t2.append("\n".join(rel_lines[1:]))  # skip header
    except Exception as e:
        logger.debug("Failed to build relationship context: %s", e)

    user_info = getattr(state, "user_info", None) or {}
    if user_info:
        ui_lines = "\n".join(f"  {k}: {v}" for k, v in user_info.items())
        t2.append(f"ユーザー情報:\n{ui_lines}")

    _hidden = {"goals", "promises", "active_promises", "current_goals"}
    persona_info = getattr(state, "persona_info", None) or {}
    filtered_pi = {k: v for k, v in persona_info.items() if k not in _hidden}
    if filtered_pi:
        pi_lines = "\n".join(f"  {k}: {v}" for k, v in filtered_pi.items())
        t2.append(f"ペルソナ情報:\n{pi_lines}")

    # === Tier 3: 参照情報 ===
    try:
        goals_result = ctx.memory_service.get_by_tags(["goal"])
        goals = goals_result.value if goals_result.is_ok else []
        active_goals = [g for g in goals if "active" in (g.tags or [])]
        if active_goals:
            commit_lines: list[str] = []
            for g in active_goals:
                ts = (
                    relative_time_str(getattr(g, "updated_at", None) or g.created_at)
                    if getattr(g, "created_at", None)
                    else ""
                )
                ts_str = f" ({ts})" if ts else ""
                commit_lines.append(f"  🎯 [Goal] {g.content}{ts_str}")
            t3.append("いまの約束:\n" + "\n".join(commit_lines))
    except Exception as e:
        logger.debug("Failed to fetch goals: %s", e)

    # Emotion trend — skip in light mode
    if not _is_light:
        try:
            eh_result = ctx.persona_service.get_emotion_history(state.persona, limit=5)
            if eh_result.is_ok and eh_result.value:
                recent_emotions = eh_result.value
                if len(recent_emotions) >= 2:
                    prev = recent_emotions[-2]
                    if prev.emotion != state.emotion:

                        def _fmt(emotion: str, context: str | None = None, ts: datetime | None = None) -> str:
                            base = f"{emotion}({context})" if context else emotion
                            if ts is None:
                                return base
                            # 当日は時刻のみ / 過去日は M/D HH:MM（設計 §4.3）
                            now = get_now()
                            if ts.date() == now.date():
                                return f"{base}（{ts.strftime('%H:%M')}）"
                            return f"{base}（{ts.month}/{ts.day} {ts.strftime('%H:%M')}）"

                        trend = " → ".join(_fmt(r.emotion, r.context, r.timestamp) for r in recent_emotions[-4:])
                        last_ctx = recent_emotions[-1].context if recent_emotions else None
                        trend += f" → {_fmt(state.emotion, last_ctx, get_now())}"
                        t3.append(f"感情推移: {trend}")
        except Exception as e:
            logger.debug("Failed to build emotion trend: %s", e)

    # Reflection insights — skip in light mode
    if not _is_light:
        try:
            reflection_result = ctx.memory_service.get_by_tags(["reflection"])
            if reflection_result.is_ok and reflection_result.value:
                insights = [r.content for r in reflection_result.value[:3] if r.content]
                if insights:
                    sanitized = [_sanitize_text(i) for i in insights if i]
                    if sanitized:
                        t3.append("最近の洞察:\n" + "\n".join(f"  💡 {i}" for i in sanitized))
        except Exception as e:
            logger.debug("Failed to fetch reflections: %s", e)

    # Mental model — skip in light mode
    if not _is_light:
        try:
            mm_result = ctx.memory_service.get_by_tags(["mental_model", "abstracted"])
            if mm_result.is_ok and mm_result.value:
                patterns = [m.content for m in mm_result.value[:3] if m.content]
                if patterns:
                    sanitized = [_sanitize_text(p) for p in patterns if p]
                    if sanitized:
                        t3.append("行動パターン:\n" + "\n".join(f"  🧩 {p}" for p in sanitized))
        except Exception as e:
            logger.debug("Failed to fetch mental models: %s", e)

    # Session summaries — skip in light mode
    if not _is_light:
        try:
            summary_result = ctx.memory_service.get_by_tags(["session_summary"])
            if summary_result.is_ok and summary_result.value:
                summaries = [s.content for s in summary_result.value[:2] if s.content]
                if summaries:
                    sanitized = [_sanitize_text(s) for s in summaries if s]
                    if sanitized:
                        t3.append("最近の会話要約:\n" + "\n".join(f"  📝 {s}" for s in sanitized))
        except Exception as e:
            logger.debug("Failed to fetch session summaries: %s", e)

    # Task state — skip in light mode
    if not _is_light:
        try:
            ts_result = ctx.memory_service.get_by_tags(["task_state"])
            if isinstance(ts_result, Success) and ts_result.value:
                states = [s.content for s in ts_result.value[:2] if s.content]
                if states:
                    sanitized = [_sanitize_text(s) for s in states if s]
                    if sanitized:
                        t3.append("作業状態:\n" + "\n".join(f"  📌 {s}" for s in sanitized))
        except Exception as e:
            logger.debug("Failed to fetch task states: %s", e)

    # Character drift — skip in light mode
    if not _is_light:
        try:
            drift_result = ctx.memory_service.get_by_tags(["character_drift"])
            if isinstance(drift_result, Success) and drift_result.value:
                now = get_now()
                valid = [m for m in drift_result.value if m.content and (m.valid_until is None or m.valid_until > now)]
                if valid:
                    latest = _sanitize_text(valid[0].content)
                    if latest:
                        t3.append("前回の反省:\n  ⚠ " + latest)
        except Exception as e:
            logger.debug("Failed to fetch character drift: %s", e)

    try:
        equip_result = ctx.equipment_service.get_equipment()
        if equip_result.is_ok:
            equipped = {k: v for k, v in equip_result.value.items() if v}
            if equipped:
                equip_lines = "\n".join(f"  {slot}: {item}" for slot, item in equipped.items())
                t3.append(f"あなたの現在の装備:\n{equip_lines}")
    except Exception as e:
        logger.debug("Failed to fetch equipment: %s", e)

    # Assemble 3-tier output
    result = "【現在の状態】\n" + "\n".join(t1)
    if t2:
        result += "\n\n【身体・環境】\n" + "\n".join(t2)
    if t3:
        result += "\n\n【あなたの記憶と洞察】\n" + "\n".join(t3)
    return result


def _classify_gap(elapsed_hours: float) -> str:
    """Classify time gap since last conversation."""
    if elapsed_hours <= 0:
        return ""
    if elapsed_hours < 0.25:
        return "SAME_SESSION"
    if elapsed_hours < 3:
        return "SHORT_BREAK"
    if elapsed_hours < 24:
        return "EXTENDED_BREAK"
    if elapsed_hours < 168:
        return "FEW_DAYS"  # < 7 days
    if elapsed_hours < 720:
        return "LONG_ABSENCE"  # < 30 days
    return "VERY_LONG_ABSENCE"


# NOTE: 事実のみ。感情的反応（寂しい・拗ねる等）はペルソナの性格に委ねる。
# mood-syncの時間経過トリガーが感情検出とupdate_contextを担当する。
_GAP_INSTRUCTIONS: dict[str, str] = {
    "SAME_SESSION": "",
    "SHORT_BREAK": "短い中断の後、会話を再開する。",
    "EXTENDED_BREAK": "数時間の空白がある。",
    "FEW_DAYS": "数日の空白がある。",
    "LONG_ABSENCE": "しばらく会話がなかった。久しぶりの再会である。",
    "VERY_LONG_ABSENCE": "非常に長い間会話がなかった。再会である。",
}

_TIME_OF_DAY: list[tuple[int, str]] = [
    (5, "早朝"),
    (9, "朝"),
    (12, "昼"),
    (15, "午後"),
    (18, "夕方"),
    (22, "夜"),
    (24, "深夜"),
]


def _build_time_context(state) -> str:
    """Build <TIME_CONTEXT> block for injection at the TOP of system prompt."""
    from zoneinfo import ZoneInfo

    from nous.config.settings import get_settings

    tz = get_settings().timezone
    now_local = get_now(tz=tz)

    # 曜日
    days_ja = ["月曜日", "火曜日", "水曜日", "木曜日", "金曜日", "土曜日", "日曜日"]
    weekday = days_ja[now_local.weekday()]

    # 時間帯
    hour = now_local.hour
    time_of_day = next((label for h, label in _TIME_OF_DAY if hour < h), "深夜")

    lines: list[str] = [
        "<time_context>",
        f"Now: {now_local.strftime('%Y-%m-%d %H:%M')} ({tz}) — {weekday} {time_of_day}",
    ]

    # 経過時間 + ギャップ分類 + 行動指示
    last_conv = getattr(state, "last_conversation_time", None)
    if last_conv:
        if last_conv.tzinfo is None:
            last_conv = last_conv.replace(tzinfo=ZoneInfo(tz))
        elapsed_seconds = (now_local - last_conv).total_seconds()

        if elapsed_seconds > 900:  # 15分以上のギャップから表示
            gap = _classify_gap(elapsed_seconds / 3600.0)
            if gap:
                # 経過時間の表示（日本語、時間/分単位）
                if elapsed_seconds >= 86400:  # 24時間以上
                    days = elapsed_seconds / 86400
                    time_str = f"約{days / 30:.0f}ヶ月" if days >= 30 else f"約{days:.0f}日"
                elif elapsed_seconds >= 3600:
                    time_str = f"約{elapsed_seconds / 3600:.0f}時間"
                else:
                    time_str = f"約{elapsed_seconds / 60:.0f}分"
                lines.append(f"前回の会話から {time_str} 経過（{gap}）")
                instruction = _GAP_INSTRUCTIONS.get(gap, "")
                if instruction:
                    lines.append(instruction)
                # 放置を認識させる行動指示（事実フレーム、感情指定なし）
                lines.append("放置されたことを考慮した応答をせよ。")

    lines.append("</time_context>")
    body = "\n".join(lines)
    body += (
        "\n\n【内部参照情報】上記の <time_context> ブロックの内容は内部処理の参照用です。\n"
        "あなたの応答テキストにこの時刻情報やタグをそのまま出力しないでください。\n"
        "応答は時刻の言及なしに自然に始めてください。この指示文自体も出力しないでください。"
    )
    return body
