"""CurationWorker — 日次 curation（B-6）＋ 素材集約（B-7）.

ASIST フェーズB item 4 の nous 実装。1 日 1 回、前日の会話を 1 回の LLM
呼び出しで「プロフィール文書 + 日記」にまとめ、journal を memories に、
profile を memory_blocks に書き戻す。

設計判断の要点（設計書 §2）:
- 状態機械は純関数 :func:`curation_due` に切り出し、単体テスト可能にする。
- 失敗は翌日まで再試行しない（status='failed' を記録、連続 7 日で halted）。
- journal は ``tags=["journal", "journal:{date}"]`` で検索して **upsert**
  （同日再実行で二重化しない。profile は全体リライトで冪等）。
- B-7: 直近 reflection 記憶 / 当日 monologue / drift.violation を素材として
  読み取り専用でプロンプトに載せる（生成経路は変更しない）。
"""

from __future__ import annotations

import asyncio
import json
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from nous.domain.profile.tokens import estimate_tokens
from nous.domain.shared.text_utils import strip_code_fence
from nous.domain.shared.time_utils import get_now
from nous.infrastructure.logging.structured import get_logger

if TYPE_CHECKING:
    from collections.abc import Callable

logger = get_logger(__name__)

#: 7 日連続失敗で halted（設計書 §2-6。人手リセットまで止まる）
DEFAULT_MAX_CONSECUTIVE_FAILURES = 7
#: journal 全文の推定トークン上限（設計書 §2-4）
DEFAULT_JOURNAL_MAX_TOKENS = 1500
#: 追いかける未整理日の上限（設計書 §2-2）
DEFAULT_MAX_BACKLOG_DAYS = 7
#: transcript 1 行の文字数上限（ASIST renderTranscript 相当）
_MAX_LINE_CHARS = 500

_CURATION_PROMPT = """あなたは {persona} です。以下の資料をもとに、前日（{day}）を振り返って
プロフィール文書と日記を JSON で出力せよ。

## 前日の会話
{transcript}

## 素材（内省・独り言・キャラクタ逸脱）
{materials}

## 出力規約
- 一人称で書く（三人称の議事録にしない）
- ユーザーが「忘れてほしい」と言った内容はどこにも書かない。既に書かれていたら今日の版から外す
- 構造化スロットに書くべき単一値（身長・好物など）は profile 文章に埋め込まない
- journal_sections は 1〜5 個。各 body は数行。全体で 1500 トークン以内
- 日本語で出力する
- コードフェンスなしの JSON のみ:

{{
  "profile_me": "（{persona}自身のプロフィール全文リライト）",
  "profile_user": "（ユーザーのプロフィール全文リライト）",
  "journal_heading": "{day}",
  "journal_sections": [{{"title": "見出し", "body": "本文"}}],
  "journal_self_today": "## 今日の私 の本文"
}}"""


class CurationDecision(StrEnum):
    """curation_due の判定結果."""

    RUN = "run"
    SKIP_TODAY = "skip_today"
    SKIP_ZERO_SPEECH = "skip_zero_speech"
    HALTED = "halted"


@dataclass(frozen=True)
class CurationOutput:
    """検証済みの curation LLM 出力."""

    profile_me: str
    profile_user: str
    heading: str
    journal: str


@dataclass
class _RunState:
    last_done_at: datetime | None = None
    last_failure_at: datetime | None = None
    consecutive_failures: int = 0


# ----------------------------------------------------------------------
# 純関数: 状態機械 / バリデータ
# ----------------------------------------------------------------------


def curation_due(
    *,
    last_done_at: datetime | None,
    last_failure_at: datetime | None,
    consecutive_failures: int,
    speech_count: int,
    now: datetime,
    max_consecutive_failures: int = DEFAULT_MAX_CONSECUTIVE_FAILURES,
) -> CurationDecision:
    """翌日 curation を走らせるべきかを判定する純関数（設計書 §2-6）.

    対象は常に「昨日」。昨日分の整理が済んでいれば（last_done が昨日以降）
    skip_today。本日失敗済みなら翌日まで再試行しない。
    """
    if consecutive_failures >= max_consecutive_failures:
        return CurationDecision.HALTED
    today = now.date()
    yesterday = today - timedelta(days=1)
    if last_done_at is not None and last_done_at.date() >= yesterday:
        return CurationDecision.SKIP_TODAY
    if last_failure_at is not None and last_failure_at.date() >= today:
        return CurationDecision.SKIP_TODAY
    if speech_count <= 0:
        return CurationDecision.SKIP_ZERO_SPEECH
    return CurationDecision.RUN


def _sanitize(text: str) -> str:
    """異常 Unicode を除去する（10% 超なら全文棄却）。context_loader と同流儀."""
    if not text:
        return text
    try:
        from nous.application.chat.pipeline.context_loader import _is_suspicious_cp
    except Exception:
        return text
    suspicious = [ch for ch in text if _is_suspicious_cp(ord(ch))]
    if not suspicious:
        return text
    if len(suspicious) / len(text) > 0.1:
        logger.warning("curation: discarding content with %.0f%% suspicious chars", len(suspicious) / len(text) * 100)
        return ""
    return "".join(ch for ch in text if not _is_suspicious_cp(ord(ch)))


def validate_curation_output(
    raw: str | None,
    *,
    journal_max_tokens: int = DEFAULT_JOURNAL_MAX_TOKENS,
    profile_max_tokens: int = 3000,
) -> CurationOutput | None:
    """LLM 出力 JSON を検証する（設計書 §2-6 の 5 条件）.

    1. JSON パース（コードフェンス許容）
    2. 必須キー存在・型
    3. profile トークン上限（超過は空にして書き込みを止める）
    4. journal: 見出し ≥1 / 「今日の私」存在 / 合計トークン上限
    5. 異常 Unicode のサニタイズ

    失敗は None（呼び出し側は再試行せず failed を記録する）。
    """
    if not raw:
        return None
    try:
        data = json.loads(strip_code_fence(raw))
    except (json.JSONDecodeError, TypeError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    for key in ("profile_me", "profile_user", "journal_heading", "journal_sections", "journal_self_today"):
        if key not in data:
            return None

    sections = data["journal_sections"]
    if not isinstance(sections, list) or not sections:
        return None
    rendered: list[str] = []
    for section in sections:
        if not isinstance(section, dict):
            return None
        title = _sanitize(str(section.get("title", "")))
        body = _sanitize(str(section.get("body", "")))
        if not title and not body:
            continue
        rendered.append(f"## {title}\n{body}")
    if not rendered:
        return None
    self_today = _sanitize(str(data["journal_self_today"]))
    if not self_today:
        return None
    rendered.append(f"## 今日の私\n{self_today}")
    journal = "\n".join(rendered)
    if estimate_tokens(journal) > journal_max_tokens:
        return None

    profile_me = _sanitize(str(data["profile_me"]))
    profile_user = _sanitize(str(data["profile_user"]))
    if estimate_tokens(profile_me) > profile_max_tokens:
        profile_me = ""
    if estimate_tokens(profile_user) > profile_max_tokens:
        profile_user = ""

    heading = str(data["journal_heading"])[:32]
    return CurationOutput(profile_me=profile_me, profile_user=profile_user, heading=heading, journal=journal)


# ----------------------------------------------------------------------
# 設定・LLM 解決ヘルパ
# ----------------------------------------------------------------------


def _cfg(config: Any, name: str, default: Any) -> Any:
    """設定値を防御的に読む（テストの mock 属性を誤って有効化しない）."""
    if config is None:
        return default
    value = getattr(config, name, default)
    if isinstance(value, (bool, int, float, str)):
        return value
    return default


def _resolve_curation_llm(settings: Any) -> tuple[str, str, str, str] | None:
    """curation LLM の (provider, api_key, model, base_url) を解決する.

    curation.* が空なら memory_enrichment.* を再利用（consolidation と同じ流儀）。
    """
    cfg = getattr(settings, "curation", None)
    enrichment = getattr(settings, "memory_enrichment", None)
    provider = str(_cfg(cfg, "provider", "") or _cfg(enrichment, "provider", "openrouter"))
    model = str(_cfg(cfg, "model", "") or _cfg(enrichment, "model", ""))
    base_url = str(_cfg(cfg, "base_url", "") or _cfg(enrichment, "base_url", ""))
    api_key = str(_cfg(cfg, "api_key", "") or "")
    if not api_key and enrichment is not None:
        resolver = getattr(enrichment, "get_effective_api_key", None)
        if callable(resolver):
            try:
                api_key = str(resolver(settings) or "")
            except Exception:
                logger.debug("curation: key resolution failed", exc_info=True)
                api_key = ""
    if not api_key or not model:
        return None
    return provider, api_key, model, base_url


async def _generate_curation_async(
    prompt: str,
    *,
    provider_name: str,
    api_key: str,
    model: str,
    base_url: str,
    max_tokens: int,
    temperature: float,
) -> str | None:
    from nous.infrastructure.llm.base import LLMMessage
    from nous.infrastructure.llm.factory import get_provider
    from nous.infrastructure.llm.text_utils import collect_text

    provider = get_provider(provider_name, api_key, model, base_url)
    return await collect_text(
        provider,
        messages=[LLMMessage(role="user", content=prompt)],
        system="",
        tools=[],
        temperature=temperature,
        max_tokens=max_tokens,
    )


def default_curation_llm(settings: Any) -> Callable[[str, str], str | None] | None:
    """本番用 LLM 呼び出し（同期 wrapper）。credentials が無ければ None."""
    resolved = _resolve_curation_llm(settings)
    if resolved is None:
        return None
    provider_name, api_key, model, base_url = resolved
    cfg = getattr(settings, "curation", None)
    max_tokens = int(_cfg(cfg, "llm_max_tokens", 4096))
    temperature = float(_cfg(cfg, "llm_temperature", 0.3))

    def _call(prompt: str, persona: str) -> str | None:
        try:
            return asyncio.run(
                _generate_curation_async(
                    prompt,
                    provider_name=provider_name,
                    api_key=api_key,
                    model=model,
                    base_url=base_url,
                    max_tokens=max_tokens,
                    temperature=temperature,
                )
            )
        except Exception:
            logger.warning("CurationWorker: LLM call failed", exc_info=True)
            return None

    return _call


# ----------------------------------------------------------------------
# DB ヘルパ
# ----------------------------------------------------------------------


def _parse_dt(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.replace(tzinfo=None) if value.tzinfo else value
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    return parsed.replace(tzinfo=None) if parsed.tzinfo else parsed


def _read_run_state(db: Any, persona: str) -> _RunState:
    """curation_runs から最後の成功/失敗と連続失敗数を読む."""
    state = _RunState()
    try:
        rows = db.execute(
            "SELECT status, finished_at FROM curation_runs WHERE persona=? ORDER BY id DESC",
            (persona,),
        ).fetchall()
    except Exception:
        logger.debug("curation: curation_runs read failed", exc_info=True)
        return state
    counting = True
    for row in rows:
        status = row["status"]
        ts = _parse_dt(row["finished_at"])
        if status == "done":
            if state.last_done_at is None:
                state.last_done_at = ts
            counting = False
        elif status == "failed":
            if state.last_failure_at is None:
                state.last_failure_at = ts
            if counting:
                state.consecutive_failures += 1
    return state


def _record_run(db: Any, persona: str, status: str, error: str | None, started: datetime, finished: datetime) -> None:
    try:
        db.execute(
            "INSERT INTO curation_runs (persona, status, error, started_at, finished_at) VALUES (?, ?, ?, ?, ?)",
            (persona, status, error, started.isoformat(), finished.isoformat()),
        )
        db.commit()
    except Exception:
        logger.warning("curation: failed to record run (%s)", status, exc_info=True)


def _transcript_for_range(db: Any, persona: str, start: Any, end: Any) -> tuple[str, int]:
    """chat_sessions（main）から [start, end] の会話を組み立てる（ASIST renderTranscript 相当）.

    返り値=(transcript, 期間内のユーザー発話数). 1 行は 500 字でトランケート。
    """
    try:
        row = db.execute(
            "SELECT messages FROM chat_sessions WHERE persona=? AND session_id='main'",
            (persona,),
        ).fetchone()
    except Exception:
        logger.debug("curation: chat_sessions read failed", exc_info=True)
        return "", 0
    if row is None:
        return "", 0
    raw = row["messages"] if hasattr(row, "keys") else row[0]
    try:
        data = json.loads(raw) if raw else []
    except (json.JSONDecodeError, TypeError):
        return "", 0

    entries: list[dict] = []
    if isinstance(data, dict):
        nodes = {n["id"]: n for n in data.get("nodes", [])}
        current = data.get("active_leaf_id")
        while current is not None:
            node = nodes.get(current)
            if node is None:
                break
            entries.append(node)
            current = node.get("parent_id")
        entries.reverse()
    elif isinstance(data, list):
        entries = [e for e in data if isinstance(e, dict)]

    lines: list[str] = []
    user_count = 0
    for entry in entries:
        role = entry.get("role")
        content = entry.get("content")
        ts = entry.get("created_at") or entry.get("timestamp")
        if role not in ("user", "assistant") or not content or ts is None:
            continue
        when = _parse_dt(ts)
        if when is None or not (start <= when.date() <= end):
            continue
        if role == "user":
            user_count += 1
        speaker = "User" if role == "user" else persona
        lines.append(f"[{when.strftime('%H:%M')}] {speaker}: {str(content)[:_MAX_LINE_CHARS]}")
    return "\n".join(lines), user_count


def _gather_materials(ctx: Any, persona: str, day: Any) -> str:
    """B-7: 直近 reflection / 当日 monologue / drift.violation を読み取り専用で集める."""
    parts: list[str] = []
    service = getattr(ctx, "memory_service", None)
    if service is not None:
        for tag, label in (("reflection", "直近の内省"), ("character_drift", "キャラクタ逸脱")):
            try:
                result = service.get_by_tags([tag])
            except Exception:
                continue
            if not getattr(result, "is_ok", False):
                continue
            for mem in (getattr(result, "value", None) or [])[:3]:
                content = str(getattr(mem, "content", "") or "")[:200]
                if content:
                    parts.append(f"- {label}: {content}")
    repo = getattr(ctx, "_session_event_repo", None)
    if repo is not None:
        try:
            events = repo.get_by_persona(persona, "brain.monologue", 10)
        except Exception:
            events = []
        for event in events:
            ts = _parse_dt(getattr(event, "timestamp", None))
            if ts is None or ts.date() != day:
                continue
            summary = str(getattr(event, "summary", "") or "")[:200]
            if summary:
                parts.append(f"- {persona}の独り言: {summary}")
    return "\n".join(parts) if parts else "（なし）"


# ----------------------------------------------------------------------
# Worker
# ----------------------------------------------------------------------


class CurationWorker:
    """日次 curation を回す background worker（60s ポーリング）."""

    def __init__(
        self,
        settings: Any,
        llm: Callable[[str, str], str | None] | None = None,
        interval_seconds: int | None = None,
    ) -> None:
        self._settings = settings
        cfg = getattr(settings, "curation", None)
        self._journal_max_tokens = int(_cfg(cfg, "journal_max_tokens", DEFAULT_JOURNAL_MAX_TOKENS))
        self._profile_max_tokens = int(_cfg(cfg, "profile_max_tokens", 3000))
        self._max_failures = int(_cfg(cfg, "max_consecutive_failures", DEFAULT_MAX_CONSECUTIVE_FAILURES))
        self._max_backlog_days = int(_cfg(cfg, "max_backlog_days", DEFAULT_MAX_BACKLOG_DAYS))
        default_interval = int(_cfg(cfg, "check_interval_seconds", 60))
        self.interval_seconds = int(interval_seconds) if interval_seconds is not None else default_interval
        self._llm = llm if llm is not None else default_curation_llm(settings)
        self._running = False
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()

    # -- lifecycle ------------------------------------------------------

    def start(self) -> None:
        if self._running:
            return
        self._stop_event.clear()
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True, name="curation-worker")
        self._thread.start()
        logger.info("CurationWorker started (interval=%ss)", self.interval_seconds)

    def stop(self, timeout: float = 5.0) -> None:
        self._running = False
        self._stop_event.set()
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=timeout)
        logger.info("CurationWorker stopped")

    def _run(self) -> None:
        while not self._stop_event.is_set():
            try:
                self._run_cycle()
            except Exception:
                logger.exception("Curation cycle failed")
            self._stop_event.wait(self.interval_seconds)

    def _run_cycle(self) -> None:
        from nous.application.use_cases import AppContextRegistry

        try:
            personas = list(AppContextRegistry._contexts.keys())
        except Exception:
            logger.exception("CurationWorker: failed to list personas")
            return
        for persona in personas:
            try:
                ctx = AppContextRegistry.get(persona)
                self._curate_persona(ctx, persona)
            except Exception:
                logger.exception("CurationWorker: error for persona=%s", persona)

    # -- one persona ----------------------------------------------------

    def _curate_persona(self, ctx: Any, persona: str, *, force: bool = False) -> None:
        if self._llm is None:
            logger.warning("CurationWorker: no LLM configured; skipping persona=%s", persona)
            return
        try:
            db = ctx.connection.get_memory_db()
        except Exception:
            logger.warning("CurationWorker: no DB for persona=%s", persona, exc_info=True)
            return

        now = get_now()
        target_day = now.date() - timedelta(days=1)
        state = _read_run_state(db, persona)
        # 未整理の先頭日から昨日まで（バックログ上限で古い未整理日は放棄）
        window_start = max(
            state.last_done_at.date() + timedelta(days=1) if state.last_done_at else target_day,
            target_day - timedelta(days=self._max_backlog_days - 1),
        )
        transcript, speech_count = _transcript_for_range(db, persona, window_start, target_day)
        decision = curation_due(
            last_done_at=state.last_done_at,
            last_failure_at=state.last_failure_at,
            consecutive_failures=state.consecutive_failures,
            speech_count=speech_count,
            now=now,
            max_consecutive_failures=self._max_failures,
        )
        if not force:
            if decision is CurationDecision.HALTED:
                logger.warning(
                    "CurationWorker: halted after %d consecutive failures (persona=%s)",
                    state.consecutive_failures,
                    persona,
                )
                return
            if decision in (CurationDecision.SKIP_TODAY, CurationDecision.SKIP_ZERO_SPEECH):
                logger.debug("CurationWorker: %s (persona=%s)", decision.value, persona)
                return

        prompt = self._build_prompt(ctx, persona, window_start, target_day, transcript)
        try:
            raw = self._llm(prompt, persona)
        except Exception as exc:
            _record_run(db, persona, "failed", f"llm error: {exc}"[:500], now, get_now())
            logger.warning("CurationWorker: LLM raised for persona=%s", persona, exc_info=True)
            return

        output = validate_curation_output(
            raw,
            journal_max_tokens=self._journal_max_tokens,
            profile_max_tokens=self._profile_max_tokens,
        )
        if output is None:
            _record_run(db, persona, "failed", "output rejected by validator", now, get_now())
            logger.warning("CurationWorker: output rejected for persona=%s", persona)
            return

        try:
            self._write_journal(ctx, persona, target_day, output)
            self._write_profile(ctx, persona, output)
        except Exception as exc:
            _record_run(db, persona, "failed", f"write error: {exc}"[:500], now, get_now())
            logger.warning("CurationWorker: write failed for persona=%s", persona, exc_info=True)
            return
        _record_run(db, persona, "done", None, now, get_now())
        logger.info("CurationWorker: curated %s for persona=%s", target_day.isoformat(), persona)

    def _build_prompt(self, ctx: Any, persona: str, window_start: Any, target_day: Any, transcript: str) -> str:
        materials = _gather_materials(ctx, persona, target_day)
        if window_start == target_day:
            day_label = target_day.isoformat()
        else:
            day_label = f"{window_start.isoformat()} 〜 {target_day.isoformat()}"
        return _CURATION_PROMPT.format(
            persona=persona,
            day=day_label,
            transcript=transcript or "（会話なし）",
            materials=materials,
        )

    def _write_journal(self, ctx: Any, persona: str, target_day: Any, output: CurationOutput) -> None:
        date_str = target_day.isoformat()
        content = f"# {date_str}\n{output.journal}"
        existing = ctx.memory_repo.get_by_tags(["journal", f"journal:{date_str}"])
        before = getattr(existing, "value", None) if getattr(existing, "is_ok", False) else None
        if before:
            ctx.memory_repo.update(before[0].key, content=content, importance=0.7)
            return
        asyncio.run(
            ctx.memory_service.create_memory(
                content=content,
                importance=0.7,
                tags=["journal", f"journal:{date_str}"],
                kind="episodic",
                source_type="reflected",
                skip_duplicate_check=True,
                persona=persona,
            )
        )

    def _write_profile(self, ctx: Any, persona: str, output: CurationOutput) -> None:
        upsert = getattr(ctx.memory_service, "upsert_profile_block", None)
        for name, content in (("me", output.profile_me), ("user", output.profile_user)):
            if not content:
                continue
            if callable(upsert):
                upsert(persona, name, content)
            else:
                ctx.memory_repo.upsert_profile_block(persona, name, content)
