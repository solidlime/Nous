"""コンテキスト読み込み — context section, time context, relationship context 構築。"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import TYPE_CHECKING

from nous.application.chat.pipeline.aliveness import emotion_band, place_hint, safe_bands
from nous.domain.memory.cue import due_cues, event_cued_memories
from nous.domain.persona.body import body_action_hint
from nous.domain.persona.emotion_trend import build_emotion_trend_narrative
from nous.domain.shared.result import Success
from nous.domain.shared.time_utils import get_now, relative_time_str
from nous.infrastructure.logging.structured import get_logger

if TYPE_CHECKING:
    from nous.application.chat.pipeline.context import ChatTurnContext
    from nous.application.use_cases import AppContext
    from nous.domain.config.chat_config import ChatConfig

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


#: (persona, 日付) → 関係性コンテキストのキャッシュ。
#: 値は「最初に会った日」と「会話した日数」で、どちらも 1 日 1 回しか変わらない。
#: 以前は毎ターン session_events の全走査を 2 回叩いていた（created_at はインデックス無し）。
_relationship_cache: dict[tuple[str, str], str] = {}
_relationship_cache_max = 64


def _build_relationship_context(ctx: AppContext) -> str:
    """Build relationship context summary from interaction history.
    Returns empty string if no interaction history exists."""
    db = ctx.connection.get_memory_db()
    persona = ctx.persona
    today = datetime.now(UTC).date()
    cache_key = (persona, today.isoformat())
    cached = _relationship_cache.get(cache_key)
    if cached is not None:
        return cached

    text = _query_relationship_context(db, persona, today)
    if text:  # 履歴なし("")はキャッシュしない（初回イベントが来たら即反映させる）
        if len(_relationship_cache) >= _relationship_cache_max:
            _relationship_cache.clear()
        _relationship_cache[cache_key] = text
    return text


def _query_relationship_context(db, persona: str, today: date) -> str:
    """関係性コンテキストの実体（キャッシュミス時のみ実行）。"""
    # First interaction time
    row = db.execute(
        "SELECT MIN(created_at) FROM session_events WHERE persona = ?",
        (persona,),
    ).fetchone()
    first_at_str = row[0] if row and row[0] else None
    if not first_at_str:
        return ""  # No history at all

    first_at = datetime.fromisoformat(first_at_str).date()
    days_known = (today - first_at).days

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
    emotion_bands: tuple[float, float] | None = None,
    config: ChatConfig | None = None,
) -> str:
    """get_context() 同等の充実したコンテキストサマリーを構築する。

    compress_mode が "light"/"normal"/"aggressive" の場合は、
    重いセクション（reflection insight, mental model, session summary, emotion history）をスキップする。
    """
    # 帯の正規化はここで 1 回だけ。t1 ラベルと trend が同じ正規化済み帯を共有する
    # （domain の emotion_trend はクランプしないので、生の設定値を直接渡さない）。
    bands = safe_bands(emotion_bands)

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

    def _current_intensity() -> float:
        """現在の強度を境界で正規化（欠損・範囲外・非数値は 0.5）。"""
        from nous.domain.value_objects import normalize_importance

        try:
            _raw_int = getattr(state, "emotion_intensity", 0.5)
            return normalize_importance(float(_raw_int) if _raw_int is not None else None)
        except (TypeError, ValueError):
            return 0.5

    t1: list[str] = []  # Tier 1: 現在の状態
    t2: list[str] = []  # Tier 2: 身体・環境
    t3: list[str] = []  # Tier 3: 参照情報
    _is_light = compress_mode == "light"
    if _is_light:
        logger.info("context section light skip drift=light_skip (drift/reflection sections skipped)")

    # === Tier 1: 現在の状態 ===
    # 時間情報は <TIME_CONTEXT> ブロック（システムプロンプト先頭）を参照
    if getattr(state, "emotion", None):
        intensity = _current_intensity()
        # ラベルと if-then（prompt.py）は同じ設定帯を共有する（阈値を 2 組持たない）
        intensity_label = ("弱い", "やや強い", "強い")[emotion_band(intensity, bands)]
        t1.append(f"感情: {state.emotion}（{intensity_label}）")
        # #39: if-then の 1 行は prompt.py（system prompt 直下）が持ち、ここには入れない。

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
        # #42: 場所カタログの「しがちなこと」を 1 行（未知の場所は空）
        _place_hint = place_hint(state.environment)
        if _place_hint:
            t2.append(_place_hint)

    # 見た目（装備から合成される）。system prompt に一切入っておらず、自分の姿を
    # 会話で参照できなかった（TTS と自画像だけが読んでいた）。
    appearance = getattr(state, "appearance", None)
    if isinstance(appearance, str) and appearance.strip():
        t2.append(f"見た目: {_truncate(appearance.strip(), 200)}")

    # 自由記述の身体・精神状態（update_context / 抽出が書く）。数値だけでは
    # 「だるさ」「気分の説明」が次ターンに戻らず、同じことを書き直す圧力になる。
    for _key, _label in (("physical_state", "体の様子"), ("mental_state", "心の様子")):
        _val = getattr(state, _key, None)
        if isinstance(_val, str) and _val.strip():
            t2.append(f"{_label}: {_val.strip()}")

    # 数値から導いた行動の傾向（制約ではない。虚弱時だけ 1〜2 文）
    body_hint = body_action_hint(state)
    if body_hint:
        t2.append(f"身体の傾向: {body_hint}")

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
    # handover: は session_begin 専用（毎ターンの system prompt に古い栞を混ぜない）
    filtered_pi = {k: v for k, v in persona_info.items() if k not in _hidden and not k.startswith("handover:")}
    if filtered_pi:
        pi_lines = "\n".join(f"  {k}: {v}" for k, v in filtered_pi.items())
        t2.append(f"ペルソナ情報:\n{pi_lines}")

    # === Tier 3: 参照情報 ===
    query_text = (getattr(turn_ctx, "user_message", "") or "") if turn_ctx else ""
    try:
        goals_result = ctx.memory_service.get_by_tags(["goal"])
        goals = goals_result.value if isinstance(goals_result, Success) else []
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

        # audit M2 — 先見的記憶: 「今この瞬間」が cue になるコミットメントだけを前面に出す。
        # 時間 cue（期限が窓内）とイベント cue（今回の発話にエンティティが登場）の 2 種類。
        # 期限切れは注入しない（未達成なら「いまの約束」に残る。二重に急かさない）。
        if active_goals:
            cue_lines: list[str] = []
            cued_keys: set[str] = set()
            for mem, label in due_cues(active_goals, get_now(), allow_overdue=False):
                cued_keys.add(mem.key)
                cue_lines.append(f"  ⏰ [期限] {mem.content[:120]} ({label})")
            for mem in event_cued_memories(active_goals, query_text):
                if mem.key in cued_keys:
                    continue
                cue_lines.append(f"  ⚡ [言及] {mem.content[:120]}")
            if cue_lines:
                t3.append("いま思い出すべき約束:\n" + "\n".join(cue_lines))
    except Exception as e:
        logger.debug("Failed to fetch goals: %s", e)

    # 前からの約束（promise タグの記憶、直近5件）— light モードではスキップ
    if not _is_light:
        try:
            promise_result = ctx.memory_service.get_by_tags(["promise"])
            if isinstance(promise_result, Success) and promise_result.value:
                promises = [m for m in promise_result.value[:5] if m.content]
                if promises:
                    sanitized = [
                        _sanitize_text(m.content[:200] + "..." if len(m.content) > 200 else m.content) for m in promises
                    ]
                    sanitized = [p for p in sanitized if p]
                    if sanitized:
                        t3.append("前からの約束:\n" + "\n".join(f"  🤝 {p}" for p in sanitized))
        except Exception as e:
            logger.debug("Failed to fetch promises: %s", e)

    # 重要な記憶（importance 上位）— アイデンティティ中核のため light モードでも3件に減らして残す
    try:
        top_n = 3 if _is_light else 5
        top_result = ctx.memory_service.get_top_by_importance(top_n)
        if isinstance(top_result, Success) and top_result.value:
            tops = [m for m in top_result.value[:top_n] if m.content]
            if tops:
                sanitized = [
                    _sanitize_text(m.content[:200] + "..." if len(m.content) > 200 else m.content) for m in tops
                ]
                sanitized = [p for p in sanitized if p]
                if sanitized:
                    t3.append("重要な記憶:\n" + "\n".join(f"  📖 {p}" for p in sanitized))
    except Exception as e:
        logger.debug("Failed to fetch top memories: %s", e)

    # Emotion trend — skip in light mode
    if not _is_light:
        try:
            eh_result = ctx.persona_service.get_emotion_history(state.persona, limit=5)
            if isinstance(eh_result, Success) and eh_result.value:
                narrative = build_emotion_trend_narrative(
                    eh_result.value,
                    state.emotion,
                    _current_intensity(),
                    bands=bands,
                )
                if narrative:
                    t3.append(narrative)
        except Exception as e:
            logger.debug("Failed to build emotion trend: %s", e)

    # Reflection insights — skip in light mode
    if not _is_light:
        try:
            reflection_result = ctx.memory_service.get_by_tags(["reflection"])
            if isinstance(reflection_result, Success) and reflection_result.value:
                # get_by_tags は無 LIMIT・updated_at DESC。全件 encode はレイテンシが単調増加するため直近のみ。
                # 相対閾値の比較基準もこの「直近N件の候補集合」内で完結する。
                contents = [r.content for r in reflection_result.value if r.content][:20]
                insights = _select_reflection_insights(ctx, query_text, contents, config)
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
            if isinstance(mm_result, Success) and mm_result.value:
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
            if isinstance(summary_result, Success) and summary_result.value:
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

    # Character drift の注入は廃止した（毎ターンのキャラ判定器を廃止し、
    # drift 記憶を作る経路が無くなったため）。既存の drift 記憶は validate_until
    # の失効で自然に消える。

    try:
        equip_result = ctx.equipment_service.get_equipment()
        if isinstance(equip_result, Success):
            equipment = equip_result.value
            # audit M9-a: 装着済みスロットのみ注入する。未装着行は毎ターンの
            # 固定費（8 行）で情報価値が無いため列挙しない。装着が 1 つも
            # 無ければブロック自体を出さない。
            equipped = {slot: item for slot, item in (equipment or {}).items() if item}
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


def _reflection_config(ctx, config: ChatConfig | None):
    """リクエスト毎の ChatConfig を優先し、無ければ ctx の config（従来経路）を返す。

    ``ctx._config`` は AppContext 生成時に 1 回だけ読まれる（Registry が persona 毎に
    キャッシュする）ため、これだけを見ると UI での変更が再起動まで効かない。
    """
    return config if config is not None else getattr(ctx, "_config", None)


def _reflection_similarity_threshold(ctx, config: ChatConfig | None = None) -> float:
    """reflection 注入のベクトル類似の絶対下限 (floor)。未設定/不正値はデフォルト 0.45。"""
    try:
        return float(getattr(_reflection_config(ctx, config), "reflection_injection_min_similarity", 0.45))
    except (TypeError, ValueError):
        return 0.45


def _reflection_injection_margin(ctx, config: ChatConfig | None = None) -> float:
    """reflection 注入の相対閾値マージン。未設定/不正値はデフォルト 0.08。"""
    try:
        return float(getattr(_reflection_config(ctx, config), "reflection_injection_margin", 0.08))
    except (TypeError, ValueError):
        return 0.08


def _select_reflection_insights(ctx, query: str, contents: list[str], config: ChatConfig | None = None) -> list[str]:
    """reflection 注入候補を選択する（相対閾値フィルタ）。

    実測コサイン (ruri-v3-30m, is_query=True) では関連 0.8151-0.9242 /
    無関係 0.7252-0.8409 と分布が重なり絶対閾値で分離できないため、
    候補集合内の相対選択でフィルタする: sim >= (max_sim - margin) AND sim >= floor。

    設計限界（集合内の相対選択）: 候補全件が互いに類似した無関係な内省文
    の場合 max_sim も無関係側に張り付くため、最大1件は注入される。

    fail-open ショートサーキット（floor<=0 / 空 query / 埋め込みモデル無し /
    例外）は埋め込みを一切呼ばず元リストの先頭3件を返す（現行動作）。
    """
    threshold = _reflection_similarity_threshold(ctx, config)
    if threshold <= 0.0 or not query.strip():
        return contents[:3]
    embedding = getattr(ctx, "_embedding", None)
    if embedding is None:
        return contents[:3]
    try:
        import numpy as np

        margin = _reflection_injection_margin(ctx, config)
        q = embedding.encode(query, is_query=True)
        sims = [float(np.dot(q, embedding.encode(c))) for c in contents]
        logger.debug(
            "reflection injection sims=%s (floor=%s, margin=%s)",
            [round(s, 4) for s in sims],
            threshold,
            margin,
        )
        max_sim = max(sims)
        kept = [c for c, s in zip(contents, sims, strict=False) if s >= threshold and s >= max_sim - margin]
        return kept[:3]
    except Exception as e:
        logger.debug("reflection similarity check failed: %s", e)
        return contents[:3]


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

REUNION_GAP_SECONDS = 900  # 再会判定の閾値（time_context 表示用）


def _truncate(text: str, limit: int) -> str:
    """長すぎる自由記述を 1 行に収める（末尾は省略記号）."""
    return text if len(text) <= limit else text[: limit - 1] + "…"


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

        if elapsed_seconds > REUNION_GAP_SECONDS:
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
