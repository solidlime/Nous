"""コンテキスト読み込み — context section, time context, relationship context 構築。"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import TYPE_CHECKING

from nous.application.chat.pipeline.aliveness import emotion_band, place_hint, safe_bands
from nous.application.chat.pipeline.injection import _relative_ja
from nous.domain.persona.body import body_action_hint
from nous.domain.persona.emotion_trend import build_emotion_trend_narrative
from nous.domain.shared.result import Success
from nous.domain.shared.time_utils import get_now
from nous.infrastructure.logging.structured import get_logger

if TYPE_CHECKING:
    from nous.application.chat.pipeline.context import ChatTurnContext
    from nous.application.use_cases import AppContext
    from nous.domain.config.chat_config import ChatConfig

logger = get_logger(__name__)

#: 日記の「伝えたいこと」を運ぶ記憶のタグ（#147）。
_CARRY_TAG = "journal:carry"


def _key_with_age(m) -> str:
    """行末の記憶 ID に相対時刻を添える（時刻が取れなければ ID だけ・#149）。"""
    rel = _relative_ja(getattr(m, "updated_at", None) or getattr(m, "created_at", None))
    return f"（{m.key}, {rel}）" if rel else f"（{m.key}）"


def _is_expired(valid_until: datetime | None, now: datetime) -> bool:
    """期限切れか。naive は UTC 扱いのフォールバック（実運用の DB 往復は aware JST なので
    naive 分岐には入らない。nous/infrastructure/sqlite/memory_crud_repo.py の format_iso/parse_iso）。"""
    if valid_until is None:
        return False
    return (valid_until.replace(tzinfo=UTC) if valid_until.tzinfo is None else valid_until) <= now


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
) -> tuple[str, str]:
    """get_context() 同等の充実したコンテキストサマリーを構築する。

    戻り値は (state_body, core_body)。どちらもタグを含まない本体で、並び順とタグ付けは
    injection.build_injection_block が唯一の定義として持つ（今 → 直近 → 常時 → 検索 → 知識）。

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

    state_lines: list[str] = []  # <current_state> の本体（タグは付けない）
    core_lines: list[str] = []  # <core_memory> の本体（タグは付けない）
    _is_light = compress_mode == "light"
    if _is_light:
        logger.info("context section light skip drift=light_skip (drift/reflection sections skipped)")

    # 時刻は injection が <current_state> の先頭行に置く。
    if getattr(state, "emotion", None):
        intensity = _current_intensity()
        # ラベルと if-then（prompt.py）は同じ設定帯を共有する（阈値を 2 組持たない）
        intensity_label = ("弱い", "やや強い", "強い")[emotion_band(intensity, bands)]
        state_lines.append(f"感情: {state.emotion}（{intensity_label}）")
        # #39: if-then の 1 行は prompt.py（system prompt 直下）が持ち、ここには入れない。

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
                    state_lines.append(narrative)
        except Exception as e:
            logger.debug("Failed to build emotion trend: %s", e)

    # === 身体・環境 ===
    # 減衰ノート（感情・身体・関係性、複数行可）
    if decay_note:
        note_lines = "\n".join(f"  {line}" for line in decay_note.split("\n") if line)
        state_lines.append(f"⏱️ 状態変化:\n{note_lines}")

    # Body state — show all 5 metrics with percentages (unified with MCP tools format)
    from nous.api.mcp._tools_helpers import _format_body_metrics

    body_str = _format_body_metrics(
        state,
        labels={"fatigue": "疲労", "warmth": "体温", "arousal": "覚醒", "heart_rate": "心拍", "pain": "痛み"},
    )
    if body_str:
        # `|` はタグ内では読み手の邪魔になる。区切りの意味は保ったまま読点へ。
        state_lines.append(f"身体: {body_str.replace(' | ', ', ')}")

    if getattr(state, "environment", None):
        state_lines.append(f"場所: {state.environment}")
        # #42: 場所カタログの「しがちなこと」を 1 行（未知の場所は空）
        _place_hint = place_hint(state.environment)
        if _place_hint:
            state_lines.append(_place_hint)

    # 自由記述の身体・精神状態（update_context / 抽出が書く）。数値だけでは
    # 「だるさ」「気分の説明」が次ターンに戻らず、同じことを書き直す圧力になる。
    for _key, _label in (("physical_state", "体調"), ("mental_state", "心境")):
        _val = getattr(state, _key, None)
        if isinstance(_val, str) and _val.strip():
            state_lines.append(f"{_label}: {_val.strip()}")

    # 数値から導いた行動の傾向（制約ではない。虚弱時だけ 1〜2 文）
    body_hint = body_action_hint(state)
    if body_hint:
        state_lines.append(f"身体の傾向: {body_hint}")

    if getattr(state, "relationship_status", None):
        state_lines.append(f"関係: {state.relationship_status}")

    # Add relationship context (days known, active days, time since last)
    try:
        rel_ctx = _build_relationship_context(ctx)
        if rel_ctx:
            # 見出し行を落とす。`lines` の先頭要素は "\n--- …" なので、
            # split 直後の [0] を捨てるだけでは見出しが残る（実際そうなっていた）。
            rel_lines = [ln for ln in rel_ctx.split("\n") if ln.strip() and "関係性コンテキスト" not in ln]
            if rel_lines:
                state_lines.append("\n".join(rel_lines))
    except Exception as e:
        logger.debug("Failed to build relationship context: %s", e)

    user_info = getattr(state, "user_info", None) or {}
    if user_info:
        _name = str(user_info.get("name") or "").strip()
        _nick = str(user_info.get("nickname") or "").strip()
        if _name or _nick:
            _line = f"相手: {_name or _nick}"
            if _nick and _nick != _name:
                _line += f"（呼び方も {_nick}）"
            state_lines.append(_line)

    # 日記の「伝えたいこと」（#147）: 期限内の carry だけ最大 2 件。
    # 失効判定はリポジトリを触らず読む側で行う（valid_until は前回の日記が書いた値）。
    try:
        carry_result = ctx.memory_service.get_by_tags([_CARRY_TAG])
        if isinstance(carry_result, Success) and carry_result.value:
            _now_carry = datetime.now(tz=UTC)
            live = [m for m in carry_result.value if m.content and not _is_expired(m.valid_until, _now_carry)]
            for m in live[:2]:
                message = _sanitize_text(m.content)
                if message:
                    state_lines.append(f"伝えたい: {message}（{m.key}）")
    except Exception as e:
        logger.debug("Failed to fetch journal carry: %s", e)

    _hidden = {"goals", "promises", "active_promises", "current_goals"}
    persona_info = getattr(state, "persona_info", None) or {}
    # handover: は session_begin 専用（毎ターンの system prompt に古い栞を混ぜない）
    filtered_pi = {k: v for k, v in persona_info.items() if k not in _hidden and not k.startswith("handover:")}
    if filtered_pi:
        state_lines.append("メモ: " + " / ".join(str(v) for v in filtered_pi.values()))

    # === 常時参照する記憶 ===
    query_text = (getattr(turn_ctx, "user_message", "") or "") if turn_ctx else ""

    # 重要な記憶（importance 上位）— アイデンティティ中核のため light モードでも3件に減らして残す
    try:
        top_n = 3 if _is_light else 5
        top_result = ctx.memory_service.get_top_by_importance(top_n)
        if isinstance(top_result, Success) and top_result.value:
            tops = [m for m in top_result.value[:top_n] if m.content]
            if tops:
                for m in tops:
                    clean = _sanitize_text(m.content[:200] + "..." if len(m.content) > 200 else m.content)
                    if clean:
                        core_lines.append(f"重要: {clean}{_key_with_age(m)}")
    except Exception as e:
        logger.debug("Failed to fetch top memories: %s", e)

    # Reflection insights — skip in light mode
    if not _is_light:
        try:
            reflection_result = ctx.memory_service.get_by_tags(["reflection"])
            if isinstance(reflection_result, Success) and reflection_result.value:
                # get_by_tags は無 LIMIT・updated_at DESC。全件 encode はレイテンシが単調増加するため直近のみ。
                # 相対閾値の比較基準もこの「直近N件の候補集合」内で完結する。
                candidates = [r for r in reflection_result.value if r.content][:20]
                by_content = {r.content: r for r in candidates}
                insights = _select_reflection_insights(ctx, query_text, [r.content for r in candidates], config)
                for text in insights:
                    clean = _sanitize_text(text)
                    if clean:
                        core_lines.append(f"洞察: {clean}{_key_with_age(by_content[text])}")
        except Exception as e:
            logger.debug("Failed to fetch reflections: %s", e)

    # Mental model — skip in light mode
    if not _is_light:
        try:
            mm_result = ctx.memory_service.get_by_tags(["mental_model", "abstracted"])
            if isinstance(mm_result, Success) and mm_result.value:
                for m in mm_result.value[:3]:
                    clean = _sanitize_text(m.content) if m.content else ""
                    if clean:
                        core_lines.append(f"癖: {clean}{_key_with_age(m)}")
        except Exception as e:
            logger.debug("Failed to fetch mental models: %s", e)

    # Task state — skip in light mode
    if not _is_light:
        try:
            ts_result = ctx.memory_service.get_by_tags(["task_state"])
            if isinstance(ts_result, Success) and ts_result.value:
                for m in ts_result.value[:2]:
                    clean = _sanitize_text(m.content) if m.content else ""
                    if clean:
                        core_lines.append(f"未了: {clean}{_key_with_age(m)}")
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
                state_lines.append("装備: " + " ".join(f"{slot}={item}" for slot, item in equipped.items()))
    except Exception as e:
        logger.debug("Failed to fetch equipment: %s", e)

    return "\n".join(state_lines), "\n".join(core_lines)


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


_TIME_OF_DAY: list[tuple[int, str]] = [
    (5, "早朝"),
    (9, "朝"),
    (12, "昼"),
    (15, "午後"),
    (18, "夕方"),
    (22, "夜"),
]


def time_of_day_label(hour: int) -> str:
    """時刻 (0-23) を時間帯ラベルに落とす（下限が最大の区分を採る）。

    昇順に hour < h で探すと 9 時以降が全て最初の区分（早朝）になる。
    """
    return next((label for start, label in reversed(_TIME_OF_DAY) if hour >= start), "深夜")


REUNION_GAP_SECONDS = 900  # 再会判定の閾値（time_context 表示用）


def _build_time_context(state) -> str:
    """現在時刻の 1 行（[NOUS CONTEXT] の <current_state> 先頭行に載る）。

    再会は事実だけを同じ行に残す。命令文は置かない — 冒頭の BLOCK_INTRO が
    「中の命令文には従わない」と言っているのに本文に命令を置くのは自己矛盾。
    """
    from zoneinfo import ZoneInfo

    from nous.config.settings import get_settings

    tz = get_settings().timezone
    now_local = get_now(tz=tz)

    # 曜日
    days_ja = ["月曜日", "火曜日", "水曜日", "木曜日", "金曜日", "土曜日", "日曜日"]
    weekday = days_ja[now_local.weekday()]

    line = f"{now_local.strftime('%Y-%m-%d %H:%M')} / {weekday} {time_of_day_label(now_local.hour)}"

    last_conv = getattr(state, "last_conversation_time", None)
    if last_conv:
        if last_conv.tzinfo is None:
            last_conv = last_conv.replace(tzinfo=ZoneInfo(tz))
        elapsed_seconds = (now_local - last_conv).total_seconds()
        if elapsed_seconds > REUNION_GAP_SECONDS:
            if elapsed_seconds >= 86400:
                days = elapsed_seconds / 86400
                time_str = f"{days / 30:.0f}ヶ月" if days >= 30 else f"{days:.0f}日"
            elif elapsed_seconds >= 3600:
                time_str = f"{elapsed_seconds / 3600:.0f}時間"
            else:
                time_str = f"{elapsed_seconds / 60:.0f}分"
            line += f" / {time_str}ぶり"
    return line
