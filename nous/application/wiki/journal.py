"""日記（journal）編纂 — WikiWorker から移設した日記担当の mixin。

計画書: ``docs/archive/superpowers/plans/2026-11-07-wiki-dreaming.md`` §4.2 の日記パート。

``WikiWorker`` が継承する。``_cfg`` / ``_settings`` / ``vector_enabled`` / ``_last_llm`` と
``_record_event`` / ``_ask_text`` はホスト（``WikiWorker``）側が提供する。
移設のみでロジックは変えていない。
"""

from __future__ import annotations

import json
from datetime import date, datetime, time, timedelta, tzinfo
from typing import TYPE_CHECKING

from nous.application.wiki import vector_index
from nous.domain.shared.result import Failure, Success
from nous.domain.value_objects import normalize_emotion, normalize_importance
from nous.infrastructure.logging.structured import get_logger

if TYPE_CHECKING:
    from nous.config.settings import Settings, WikiConfig
    from nous.domain.memory.entities import Memory
    from nous.infrastructure.wiki.store import WikiPage, WikiStore

logger = get_logger(__name__)

#: 日記ページの slug 接頭辞（``journal-YYYY-MM-DD``）。topic 編纂の巡回対象外。
_JOURNAL_SLUG_PREFIX = "journal-"
#: LLM に渡す記憶本文の切り詰め長。
_CONTENT_PREVIEW_CHARS = 300

_JOURNAL_PROMPT = """あなたは日記を書く記録係です。{day} の記憶と営みを材料に、その日の記録を Markdown で書いてください。

現在時刻: {now}

書き方:
- 見出しは必ず次の 6 つだけを、この順・この表記で使う:
  ## 活動
  ## やったこと
  ## 感想
  ## 決めたこと
  ## 引っかかったこと
  ## 未解決
- ## 活動 は「その日の本人が何をしていたか」の記録。営みの材料にある時刻を使う。
  仕事の中身より生活の動き（作りもの・片づけ・移動・休憩・雑談）を優先して拾う。
- **各見出しは、その見出しに書ける材料が無ければ省略してよい**（空見出しを並べない）。
  行数は材料にある事実の数まで。材料が少ない日に埋め草を書かない。
- 場所・天気・相手など、材料に書かれていない設定は書かない（推測で補わない）。
- ## やったこと は作業とその成果を書く。
- ## 感想 は「その日に起きたことに対して何を感じたか・どう思ったか」を本人の口調で書く。事実の列挙にはしない。
- 材料に無い事実は書かない（推測・脚色・一般論での補完は禁止）。
- {length_hint}
- 既存ページへは [[slug]] 形式でリンクしてよい（存在しない slug はプレーンテキストに落ちる）:
{pages}
- 本文は {max_bytes} バイト以内。

材料（{day} の記憶）:
{memories}

材料（{day} の営み・時刻昇順）:
{activity}

JSON ではなく Markdown 本文だけを返してください（説明文は不要）。
"""

_STATE_PROMPT = """以下はある人物の今日の日記とその材料です。この日の出来事を経て、いまの感情・体調・精神状態を推定してください。

日記:
{body}

材料:
{memories}

以下の JSON のみを返してください（説明文は不要。推定できない項目は省略）:
{{"emotion": "喜/怒/哀/楽 などの一語", "emotion_intensity": 0.0〜1.0, "physical_state": "体の状態の短文", "mental_state": "精神状態の短文", "body_state": {{"fatigue": 0.0〜1.0}}}}
"""


class JournalMixin:
    """日記の編纂と日記からの状態反映（``WikiWorker`` の mixin）。"""

    if TYPE_CHECKING:
        # ホスト（WikiWorker）が提供する属性・メソッドの型宣言（mixin 公式パターン）。
        _cfg: WikiConfig
        _settings: Settings
        _last_llm: dict | None
        vector_enabled: bool

        def _record_event(
            self, ctx, persona: str, summary: str, detail: dict | None, *, event_type: str = ...
        ) -> None: ...

        def _ask_text(self, prompt: str, boost: int = 0) -> str | None: ...

    def _compile_journal(self, ctx, persona: str, store: WikiStore, now: datetime) -> list[str]:
        """前日（JST）の記憶を 1 ページの日記にまとめる。取り込んだ sources を返す。

        同じ日に 2 回走っても ``journal-YYYY-MM-DD`` の上書きで 1 ページのまま。
        失敗は監査に残してサイクルは続ける（日記は編纂の前提条件ではない）。
        """
        if not self._cfg.journal_enabled:
            return []
        day = (now - timedelta(days=1)).date()
        start, end = self._journal_window(day, now.tzinfo)
        try:
            memories = self._journal_memories(ctx, start, end, now.tzinfo)
            activity = self._journal_activity(ctx, persona, start, end, now.tzinfo)
            # 記憶が 0 件でも、その日の営みが読めれば日記は作る（活動だけの日がある）。
            if not memories and not activity:
                return []
            slug = f"{_JOURNAL_SLUG_PREFIX}{day.isoformat()}"
            title = f"{day.isoformat()} の記録"
            existed = store.read_page(slug).is_ok
            # 源記憶は物理削除されるので、2 回目サイクルでは材料が 0 件になる。
            # その状態で書き直すと痩せた日記で上書きするので、既存ページを残す。
            if existed and not memories:
                return []
            # sources は候補（その日の記憶）からだけ作る。LLM に選ばせない。
            # 営み（session_events）は記憶ではないので sources には入れない。
            sources = tuple(m.key for m in memories)
            tag = day.strftime("%Y-%m")
            # 本文予算は「frontmatter を引いた残り」。write_page は frontmatter 込みで
            # max_page_bytes を見るので、sources が多い日は本文を減らさないと必ず落ちる。
            budget = self._cfg.max_page_bytes - _frontmatter_bytes(slug, title, sources, tag)
            raw = self._ask_text(
                self._build_journal_prompt(day, memories, store.list_pages(), now, activity=activity, max_bytes=budget)
            )
            body = _strip_code_fence(raw or "")
            if not body:
                raise ValueError("llm returned no journal body")
            written = store.write_page(slug, title, body, sources=sources, tags=("journal", tag))
            if isinstance(written, Failure):
                raise RuntimeError(f"write_page failed: {written.error}")
            if self.vector_enabled:
                vector_index.sync_page(self._settings, persona, slug, title, body)
            action = "updated" if existed else "created"
            self._record_event(
                ctx,
                persona,
                f"{action} {slug} from {len(sources)} memories",
                {
                    "slug": slug,
                    "action": action,
                    "day": day.isoformat(),
                    "sources": list(sources),
                    "activity_lines": activity.count("\n") + 1 if activity else 0,
                    "page_hash": _hash_of(title, body),
                    **(self._last_llm or {}),
                },
            )
            self._apply_journal_state(ctx, persona, slug, memories, body)
        except Exception as e:
            logger.warning("WikiWorker: journal %s failed: %s", day, e)
            self._record_event(ctx, persona, f"error: journal {day}: {e}", None)
            return []
        return list(sources)

    def _apply_journal_state(self, ctx, persona: str, slug: str, memories: list[Memory], body: str) -> None:
        """日記から感情・体調を 1 回だけ推定して persona 状態へ反映する。

        値が取れない（JSON でない・空）なら何もしない。失敗は 1 行残して続行（日記自体は正）。
        """
        if not self._cfg.journal_apply_state:
            return
        service = getattr(ctx, "persona_service", None)
        if service is None:
            self._record_event(ctx, persona, "skipped: journal state (no persona_service)", {"slug": slug})
            return
        try:
            raw = self._ask_text(self._build_state_prompt(memories, body)) or ""
            try:
                state = _parse_json_object(raw)
            except ValueError:
                logger.warning("WikiWorker: journal state is not JSON (%s)", slug)
                return

            applied: dict[str, object] = {}
            emotion = state.get("emotion")
            intensity = state.get("emotion_intensity")
            if isinstance(emotion, str) and emotion and isinstance(intensity, (int, float)):
                result = service.update_emotion(persona, emotion, float(intensity), context=f"journal:{slug}")
                if isinstance(result, Failure):
                    raise RuntimeError(f"update_emotion failed: {result.error}")
                # 保存された値を残す（正規化・クランプ後に何が入ったかが監査の事実）。
                applied["emotion"] = normalize_emotion(emotion)
                applied["emotion_intensity"] = normalize_importance(float(intensity))

            physical = state.get("physical_state")
            mental = state.get("mental_state")
            body_state = state.get("body_state")
            states: dict[str, object] = {}
            if isinstance(physical, str) and physical:
                states["physical_state"] = physical
            if isinstance(mental, str) and mental:
                states["mental_state"] = mental
            if isinstance(body_state, dict) and isinstance(body_state.get("fatigue"), (int, float)):
                states["fatigue"] = float(body_state["fatigue"])
            if states:
                result = service.update_physical_state(persona, **states)
                if isinstance(result, Failure):
                    raise RuntimeError(f"update_physical_state failed: {result.error}")
                applied.update(states)

            if not applied:
                return
            self._record_event(
                ctx,
                persona,
                f"applied state emotion={applied.get('emotion', '-')}"
                f" intensity={applied.get('emotion_intensity', '-')}",
                {"slug": slug, **applied},
            )
        except Exception as e:
            # "error:" を付けると cycle 失敗として数えられ 30 分後の再挑戦を誘発する。
            # 日記本体は書けているので、状態反映の失敗は warning 扱いにする。
            logger.warning("WikiWorker: journal state %s failed: %s", slug, e)
            self._record_event(ctx, persona, f"warning: journal state {slug}: {e}", None)

    def _build_state_prompt(self, memories: list[Memory], body: str) -> str:
        material = "\n".join(m.content[:_CONTENT_PREVIEW_CHARS] for m in memories)
        return _STATE_PROMPT.format(body=body, memories=material)

    def _journal_window(self, day: date, tz: tzinfo | None) -> tuple[datetime, datetime]:
        """日記 1 日分の窓 ``[start, end)``。日界は ``run_at_hour``（既定 03:00）。

        カレンダー日で切ると、00:00〜run_at_hour の記憶が「当日の topic 編纂」で先に
        物理削除され、翌日の日記（同じ記憶を材料にする）から抜け落ちる。
        """
        hour = self._cfg.run_at_hour if self._cfg.run_at_hour >= 0 else 0
        start = datetime.combine(day, time(hour=hour), tzinfo=tz)
        return start, start + timedelta(days=1)

    def _journal_memories(self, ctx, start: datetime, end: datetime, tz: tzinfo | None) -> list[Memory]:
        """``[start, end)``（日記の 1 日）に作られた記憶を created_at 昇順で上限まで。

        tombstoned 以外は拾う。同日 2 回目のサイクルでは 1 回目が源記憶を物理削除して
        いるので、材料 0 件での上書きを呼び出し側が避ける（``existed and not memories``）。
        """
        result = ctx.memory_repo.find_all()
        memories: list[Memory] = list(result.value) if isinstance(result, Success) else []
        picked = []
        for memory in memories:
            if memory.lifecycle_status == "tombstoned":
                continue
            at = _aware(memory.created_at, tz)
            if start <= at < end:
                picked.append(memory)
        picked.sort(key=lambda m: _aware(m.created_at, tz))
        return picked[: self._cfg.journal_max_sources]

    def _journal_activity(self, ctx, persona: str, start: datetime, end: datetime, tz: tzinfo | None) -> str:
        """``day``（JST）の営みをプロンプト用の 1 行/件の文字列にする。

        材料は pi hook が残した ``session_events``（``turn.completed`` の発話、
        ``session.started`` のプロジェクト名、``place.moved`` の移動）。記憶は要点抽出後なので、
        「何をしていたか」が落ちる。日記に生活の営みを残すには生ログを読むしかない。

        ``timestamp`` は offset 混在の ISO 文字列（hook は UTC の ``Z``、worker は JST）
        なので文字列比較では日を切れない。``julianday()`` で引数側も同じ形式に変換して
        範囲にする。失敗は空文字で返し、日記は記憶だけで書く。
        """
        if not self._cfg.journal_include_activity:
            return ""
        try:
            from nous.infrastructure.sqlite.session_event_repo import SessionEventRepository

            repo = SessionEventRepository(ctx.connection)
            limit = self._cfg.journal_activity_max_events
            window = {"since": start.isoformat(), "until": end.isoformat()}
            events = list(repo.get_by_persona(persona, event_type="turn.completed", limit=limit, **window))
            events += list(repo.get_by_persona(persona, event_type="session.started", limit=limit, **window))
            # 移動は行数が読みにくいので独立の小さい上限（会話行の予算を食い潰さない）
            events += list(repo.get_by_persona(persona, event_type="place.moved", limit=min(limit, 50), **window))
            picked = sorted((e for e in events if e.timestamp is not None), key=lambda e: _aware(e.timestamp, tz))
            lines = [line for line in (_activity_line(e, tz) for e in picked) if line]
        except Exception:
            logger.warning("WikiWorker: journal activity query failed", exc_info=True)
            return ""
        if not lines:
            return ""
        # 1 件あたりの予算は件数で割る。それでも溢れる日は**等間隔に抜く**
        # （先頭から詰めて末尾を切ると、朝の「起きていた」だけ残って夜が消える）。
        cap = self._cfg.journal_activity_chars
        per_line = max(20, cap // len(lines))
        texts = [_clip(line, per_line) for line in lines]
        total = sum(len(t) + 1 for t in texts)
        if total > cap:
            keep = min(max(1, cap // (per_line + 1)), len(texts))
            if keep == 1:
                texts = [texts[0]]
            else:
                # 両端を必ず含める（朝と夜が抜けないように等間隔で写す）。
                idx = [round(i * (len(texts) - 1) / (keep - 1)) for i in range(keep)]
                texts = [texts[i] for i in idx]
        return "\n".join(texts)

    def _build_journal_prompt(
        self,
        day: date,
        memories: list[Memory],
        pages: list[WikiPage],
        now: datetime,
        *,
        activity: str = "",
        max_bytes: int | None = None,
    ) -> str:
        page_lines = [
            json.dumps({"slug": p.slug, "title": p.title}, ensure_ascii=False)
            for p in pages
            if p.slug != "index" and not p.slug.startswith(_JOURNAL_SLUG_PREFIX)
        ]
        memory_lines = [
            json.dumps(
                {
                    "key": m.key,
                    "created_at": m.created_at.isoformat(),
                    "content": m.content[:_CONTENT_PREVIEW_CHARS],
                },
                ensure_ascii=False,
            )
            for m in memories
        ]
        length_hint = (
            "材料が 5 件未満なので短く書く（各見出し 1〜3 行、水増し禁止）"
            if len(memories) < 5
            else "材料が多い日は列挙せず、要点を統合して書く"
        )
        return _JOURNAL_PROMPT.format(
            day=day.isoformat(),
            now=now.isoformat(),
            length_hint=length_hint,
            max_bytes=self._cfg.max_page_bytes if max_bytes is None else max_bytes,
            pages="\n".join(page_lines) or "(なし)",
            memories="\n".join(memory_lines) or "(なし)",
            activity=activity or "(なし)",
        )


def _clip(text: str, limit: int) -> str:
    """空白を潰して 1 行にする。``limit`` を超えたら末尾を切る（材料の膨張を防ぐ）。"""
    flat = " ".join(text.split())
    return flat if len(flat) <= limit else flat[: max(0, limit - 1)] + "…"


def _aware(ts: datetime, tz: tzinfo | None) -> datetime:
    """naive な timestamp にも tz を当てて比較可能にする。

    ``session_events.timestamp`` は hook が UTC の ``Z``、``nous/api/http/routers/events.py``
    がクライアント省略時に ``datetime.now()``（naive・ローカル）を書くため混在する。
    naive と aware を混ぜて ``sorted`` すると ``TypeError`` で日記が丸ごと落ちる。
    """
    if ts.tzinfo is None and tz is not None:
        return ts.replace(tzinfo=tz)
    return ts


def _activity_line(event, tz: tzinfo | None) -> str:
    """session_event 1 件を「HH:MM 何をしていたか」の 1 行にする（取れなければ空）。"""
    detail = event.detail
    if isinstance(detail, str):
        try:
            detail = json.loads(detail)
        except ValueError:
            detail = None
    if not isinstance(detail, dict):
        detail = {}
    ts = event.timestamp
    if ts is None:
        return ""
    clock = _aware(ts, tz).astimezone(tz).strftime("%H:%M") if tz is not None else ts.strftime("%H:%M")
    if event.event_type == "turn.completed":
        parts = [str(detail.get(k) or "").strip() for k in ("user_text", "assistant_text")]
        body = " / ".join(p for p in parts if p)
    elif event.event_type == "place.moved":
        to = str(detail.get("to") or "").strip()
        body = f"{to} へ移動" if to else ""
    else:
        name = str(detail.get("name") or "").strip()
        project = str(detail.get("project") or "").strip()
        if not name and not project:
            return ""  # 情報ゼロの行で営みの枠を埋めない
        body = "セッション開始" + f"（{name}{'/' + project if project else ''}）"
    return f"- {clock} {body}" if body else ""


def _parse_json_object(text: str) -> dict:
    """LLM 応答から最初の JSON オブジェクトを取り出す（コードフェンス・前後説明文を許容）。"""
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = stripped.strip("`")
        if stripped.startswith("json"):
            stripped = stripped[4:]
    start, end = stripped.find("{"), stripped.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("no JSON object found in response")
    data = json.loads(stripped[start : end + 1])
    if not isinstance(data, dict):
        raise ValueError("response is not a JSON object")
    return data


def _strip_code_fence(text: str) -> str:
    """LLM 本文のコードフェンス（markdown の 3 連バックティック）を剥がす。

    閉じフェンスより後ろ（説明文など）は捨てる。閉じフェンスが無ければ全部本文。
    """
    stripped = text.strip()
    if not stripped.startswith("```"):
        return stripped
    lines = stripped.splitlines()[1:]
    for i, line in enumerate(lines):
        if line.strip() == "```":
            lines = lines[:i]
            break
    return "\n".join(lines).strip()


def _frontmatter_bytes(slug: str, title: str, sources: tuple[str, ...], tag: str) -> int:
    """frontmatter の実測バイト数（本文予算 = max_page_bytes - これ）。"""
    from nous.infrastructure.wiki.store import WikiPage, render_page

    page = WikiPage(
        slug=slug,
        title=title,
        body="",
        project=None,
        sources=tuple(sources),
        tags=("journal", tag),
        updated="",
        links=(),
    )
    return len(render_page(page).encode("utf-8"))


def _hash_of(title: str, body: str) -> str:
    from nous.infrastructure.wiki.store import page_hash

    return page_hash(title, body)
