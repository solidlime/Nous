"""WikiWorker — ドリーミング（wiki 編纂）worker。

計画書: ``docs/superpowers/plans/2026-11-07-wiki-dreaming.md`` §4.2。

記憶の整理は **consolidation（時間軸 gist）→ wiki（トピック編纂）** の 2 段で動く:

- SELECT: persona の active 記憶を ``project:*`` タグでクラスタに分ける
  （タグ無しは ``persona`` クラスタ）。cycle ごとに上位 ``topics_per_cycle`` 件。
- 編纂: クラスタの記憶（本文 preview）+ 既存 wiki ページ目次を LLM に渡し、
  wiki ページ（slug/title/body/sources/delete）を JSON で受け取る。
- 適用: ``WikiStore.write_page`` でファイル層（正）を書き、Qdrant 索引
  （collection prefix ``wiki_``）を body_hash 変化時のみ更新する。
- 監査: ページ毎に session_events へ 1 行（``wiki.compiled``）。失敗は
  ``error: ...`` 行として記録し、ファイルは変えない（fail-safe）。
"""

from __future__ import annotations

import asyncio
import json
import re
import threading
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from nous.application.wiki import vector_index
from nous.domain.shared.result import Failure, Success
from nous.infrastructure.logging.structured import get_logger

if TYPE_CHECKING:
    from nous.config.settings import Settings, WikiConfig
    from nous.domain.memory.entities import Memory
    from nous.infrastructure.llm.base import LLMProvider
    from nous.infrastructure.wiki.store import WikiPage, WikiStore

logger = get_logger(__name__)

#: 編纂対象クラスタの最小記憶数（これ未満の topic はページ化しない）。
MIN_TOPIC_MEMORIES = 3
#: wiki 側の時刻は秒精度なので、秒未満の差は stale と見なさない。
_STALE_SLACK = timedelta(seconds=2)

#: LLM に渡す記憶本文の切り詰め長。
_CONTENT_PREVIEW_CHARS = 300

#: 既存ページ目次で LLM に渡す本文プレビュー長。
_PAGE_PREVIEW_CHARS = 400

_WIKI_PROMPT = """あなたは長期記憶を編纂する司書です。以下の記憶クラスタと既存 wiki ページを読み、
wiki ページ（Markdown 本文）を作成または改訂してください。

現在時刻: {now}
クラスタ: {topic}

編纂ルール:
- 記憶の**列挙ではなく統合**。同じ事柄の記憶は 1 段落にまとめ、矛盾する記憶は
  「以前は X、現在は Y」と経緯で書く（矛盾を消さない）。
- 見出し・箇条書きを使い、抽象度の高い要約にする（本文は {max_bytes} バイト以内）。
- 関連ページへは本文中で [[slug]] 形式の wikilink を張る（存在しない slug でもよい。
  参照先は作成され次第リンクになる）。
- slug は `{slug_prefix}` で始まる小文字英数とハイフンのみ。既存ページを改訂する場合は
  既存 slug をそのまま使う。新規トピックを分けたい場合のみ新しい slug を提案する。
- **sources には必ず上記記憶リストの key だけを入れる**（存在しない key は捨てられる）。
- 旧ページを統合して不要になった場合のみ delete にその slug を入れる。

既存 wiki ページ:
{pages}

記憶リスト:
{memories}

以下の JSON のみを返してください（説明文は不要）:
{{"pages": [{{"slug": "...", "title": "...", "body": "Markdown本文", "sources": ["<memory key>", ...], "delete": ["<slug>", ...]}}]}}
"""


class WikiWorker:
    """wiki 編纂 worker（常駐 thread + graceful shutdown）。"""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        cfg: WikiConfig = settings.wiki
        self._cfg = cfg
        self._running = False
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        #: 定刻に persona コンテキストが空だった時の再試行回数と間隔（1 日を空振りで捨てない）。
        self._empty_retries = 30
        self._retry_seconds = 60.0
        #: サイクル内で error イベントが出た件数。0 より大きければ定刻を待たず短くリトライする。
        self._cycle_errors = 0
        #: 直近の LLM 呼び出しの計器（attempt/max_tokens/text_len/stream_error）。監査イベントに載せる。
        self._last_llm: dict | None = None
        #: テスト用: False にすると Qdrant 索引更新を行わない（既定は有効）。
        self.vector_enabled = True

    # ------------------------------------------------------------------
    # lifecycle
    # ------------------------------------------------------------------

    #: 1 サイクルで LLM を呼ぶ最大回数（2 回目は予算 2 倍）。
    _llm_attempts = 2
    #: 1 回目の max_tokens。reasoning モデルでも本文を書き切れる余裕を取る。
    _max_tokens = 16000
    #: サイクルが失敗したときの再試行間隔（秒）。1 回の一時障害で 24h 空くのを防ぐ。
    _error_retry_seconds = 1800.0

    def start(self) -> None:
        if self._running:
            return
        self._stop_event.clear()
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True, name="wiki-worker")
        self._thread.start()
        logger.info(
            "WikiWorker started (at_hour=%d %s interval=%ds topics=%d)",
            self._cfg.run_at_hour,
            self._cfg.run_at_tz,
            self._cfg.interval_seconds,
            self._cfg.topics_per_cycle,
        )
        if self._cfg.run_at_hour >= 0:
            logger.info("WikiWorker next run in %.0fs", self._next_delay())

    def stop(self, timeout: float = 5.0) -> None:
        self._running = False
        self._stop_event.set()
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=timeout)
        logger.info("WikiWorker stopped")

    def _run(self) -> None:
        first = True
        while not self._stop_event.is_set():
            scheduled = self._cfg.run_at_hour >= 0
            # 定刻方式は常に待つ。interval 方式は従来どおり初回だけ即実行する。
            delay = self._next_delay() if scheduled or not first else 0.0
            first = False
            if delay > 0 and self._stop_event.wait(delay):
                return  # 停止指示
            if scheduled:
                # 定刻に persona コンテキストが空（初リクエスト前）なら、1 日捨てずに短間隔で再試行する。
                for _ in range(self._empty_retries):
                    if self._stop_event.is_set() or self._has_contexts():
                        break
                    if self._stop_event.wait(self._retry_seconds):
                        return
            try:
                self._cycle_errors = 0
                self.run_cycle()
            except Exception:
                logger.exception("Wiki cycle failed")
            if scheduled and self._cycle_errors:
                # 一時障害で丸 1 日空くのを防ぐ。失敗があれば 30 分後に再挑戦する。
                logger.warning(
                    "WikiWorker: %d topic(s) failed — retrying in %.0fs instead of a full day",
                    self._cycle_errors,
                    self._error_retry_seconds,
                )
                if self._stop_event.wait(self._error_retry_seconds):
                    return

    def _next_delay(self) -> float:
        """次サイクルまでの待ち秒数。

        ``run_at_hour >= 0`` なら毎日その時刻（``run_at_tz``、既定 Asia/Tokyo の 03:00）に
        走らせる。``-1`` なら旧来の「前サイクル終了から interval_seconds 後」。
        コンテナの TZ には依存しない（UTC 運用でも 03:00 JST になる）。
        """
        if self._cfg.run_at_hour < 0:
            return float(self._cfg.interval_seconds)
        from nous.domain.shared.time_utils import get_now

        try:
            now = get_now(self._cfg.run_at_tz)
        except Exception:
            logger.warning(
                "WikiWorker: unknown run_at_tz %r — falling back to UTC",
                self._cfg.run_at_tz,
            )
            now = datetime.now(UTC)  # ZoneInfo を再参照しない（tzdata 不在時に同じ例外を踏む）
        target = now.replace(hour=self._cfg.run_at_hour, minute=0, second=0, microsecond=0)
        if target <= now:
            target += timedelta(days=1)
        return (target - now).total_seconds()

    @staticmethod
    def _has_contexts() -> bool:
        """persona コンテキストが 1 つでも生成済みか（遅延生成なので起動直後は空）。"""
        from nous.application.use_cases import AppContextRegistry

        try:
            return bool(AppContextRegistry._contexts)
        except Exception:
            logger.debug("WikiWorker: context registry unavailable", exc_info=True)
            return False

    # ------------------------------------------------------------------
    # 1 cycle
    # ------------------------------------------------------------------

    def run_cycle(self) -> None:
        """1 cycle 実行（手動運転・検証用に public）。enabled=False なら何もしない。"""
        if not self._cfg.enabled:
            logger.debug("WikiWorker disabled, skip")
            return
        from nous.application.use_cases import AppContextRegistry

        try:
            personas = list(AppContextRegistry._contexts.keys())
        except Exception:
            logger.exception("WikiWorker: failed to list personas")
            return

        for persona in personas:
            try:
                ctx = AppContextRegistry.get(persona)
                self._compile_persona(ctx, persona)
            except Exception:
                logger.exception("WikiWorker: error for persona=%s", persona)

    # ------------------------------------------------------------------
    # SELECT
    # ------------------------------------------------------------------

    def _select_topics(
        self, memories: list[Memory], now: datetime, store: WikiStore, persona: str
    ) -> list[tuple[str, list[Memory]]]:
        """クラスタ（topic slug, 記憶リスト）を返す。cycle 上限 topics_per_cycle 件。

        優先度: source 腐敗/更新のある topic（§4.6 腐敗検出）→ 記憶数降順。
        """
        buckets: dict[str, list[Memory]] = {}
        for m in memories:
            if m.lifecycle_status != "active":
                continue
            if getattr(m, "source_type", "") == "consolidated":
                continue
            buckets.setdefault(_topic_of(m), []).append(m)

        stale = self._stale_topics(store, memories, persona)
        last_compiled = self._last_compiled(store)
        # 既にページのある topic は新着 1 件でも巡回対象にする。源を archive すると
        # active が減り、MIN_TOPIC_MEMORIES の下限でその topic が永久に選ばれなくなるため。
        topics = [
            (slug, mems)
            for slug, mems in buckets.items()
            if len(mems) >= (1 if slug in last_compiled else MIN_TOPIC_MEMORIES)
        ]
        # 並び順: stale 先頭 → 最後に編纂された時刻が古い順（未編纂は "" で最優先）
        # → 同順位は記憶数降順。これで小クラスタにも巡回が回る。
        topics.sort(key=lambda item: (item[0] not in stale, last_compiled.get(item[0], ""), -len(item[1])))
        selected = topics[: self._cfg.topics_per_cycle]
        return [(slug, self._most_recent(mems)) for slug, mems in selected]

    def _last_compiled(self, store: WikiStore) -> dict[str, str]:
        """topic → 最後に編纂された時刻（ページ updated の最大値）。"""
        latest: dict[str, str] = {}
        for page in store.list_pages():
            if not page.sources or not page.updated:
                continue
            topic = _topic_of_page(page)
            if page.updated > latest.get(topic, ""):
                latest[topic] = page.updated
        return latest

    def _stale_topics(self, store: WikiStore, memories: list[Memory], persona: str) -> set[str]:
        """source が消滅・tombstoned・またはページより新しい topic を返す。

        archived は「意図的に沈めた」状態（decay の忘却 / wiki への吸収）なので stale にしない。
        ここで stale にすると毎サイクル同じ topic を編纂し続ける（無限再編纂）。
        """
        by_key = {m.key: m for m in memories}
        stale: set[str] = set()
        for page in store.list_pages():
            if not page.sources:
                continue
            topic = _topic_of_page(page)
            for key in page.sources:
                memory = by_key.get(key)
                if memory is None or memory.lifecycle_status == "tombstoned":
                    stale.add(topic)
                    break
                if memory.lifecycle_status != "active":
                    continue
                if _page_is_behind(page.updated, getattr(memory, "updated_at", None) or memory.created_at):
                    stale.add(topic)
                    break
        return stale

    def _archive_sources(self, ctx, sources: list[str], seen: set[str]) -> int:
        """編纂済みの源記憶を archived へ沈める（decay と同じ lifecycle 遷移）。

        削除はしない: ``page.sources`` は memory key を参照し続けるので、消すと腐敗検出が壊れる。
        archived は既定の検索対象外（SearchQuery.lifecycle_status="active"）なので、
        検索面からは実質消える。tombstone は行わない（不可逆なのは decay 側の領分）。
        ``sources`` は active な記憶からのみ選ばれる（SELECT 段で除外済み）ので、
        戻り値はそのまま「active → archived に遷移した数」になる。ただし同じ key を
        複数ページが引用しうるので、``seen`` で cycle 内の二重計上を防ぐ。
        """
        if not self._cfg.archive_sources:
            return 0
        archived = 0
        for key in sources:
            if key in seen:
                continue
            try:
                result = ctx.memory_repo.update(key, lifecycle_status="archived")
            except Exception:
                logger.warning("WikiWorker: failed to archive source %s", key, exc_info=True)
                continue
            if isinstance(result, Success):
                seen.add(key)
                archived += 1
        return archived

    def _repair_links(self, store: WikiStore) -> int:
        """dangling な wikilink をプレーンテキストにする（repoint は意味判断が要るので削除側に倒す）。"""
        repaired = 0
        for slug, targets in store.dangling_links().items():
            page_result = store.read_page(slug)
            if not isinstance(page_result, Success):
                continue
            page = page_result.value
            body = page.body
            for target in targets:
                body = body.replace(f"[[{target}]]", target)
            if body != page.body:
                store.write_page(
                    slug,
                    page.title,
                    body,
                    project=page.project,
                    sources=page.sources,
                )
                repaired += 1
        return repaired

    def _most_recent(self, memories: list[Memory]) -> list[Memory]:
        def _ts(m: Memory):
            return getattr(m, "updated_at", None) or m.created_at

        return sorted(memories, key=_ts, reverse=True)[: self._cfg.max_memories_per_topic]

    # ------------------------------------------------------------------
    # 編纂
    # ------------------------------------------------------------------

    def _compile_persona(self, ctx, persona: str) -> None:
        from nous.domain.shared.time_utils import get_now
        from nous.infrastructure.wiki.store import WikiStore

        now = get_now(self._cfg.run_at_tz)
        store = WikiStore(self._settings.data_root, persona)
        all_result = ctx.memory_repo.find_all()
        memories: list[Memory] = list(all_result.value) if isinstance(all_result, Success) else []
        archived_seen: set[str] = set()
        for topic, selected in self._select_topics(memories, now, store, persona):
            try:
                self._compile_topic(ctx, persona, store, topic, selected, now, archived_seen)
            except Exception:
                logger.exception("WikiWorker: topic=%s failed", topic)
                self._record_event(ctx, persona, f"error: topic {topic} failed", None)
        # 索引維持（§4.6-6）: 外部リンクの dangling をプレーンテキストに落とす。
        repaired = self._repair_links(store)
        if repaired:
            logger.info("WikiWorker: persona=%s repaired %d pages with dangling links", persona, repaired)

    def _compile_topic(
        self,
        ctx,
        persona: str,
        store: WikiStore,
        topic: str,
        memories: list[Memory],
        now: datetime,
        archived_seen: set[str],
    ) -> None:
        pages = store.list_pages()
        payload, error, attempt = self._ask_and_parse(topic, memories, pages, now)
        if payload is None:
            self._record_event(
                ctx,
                persona,
                f"error: {error}",
                {"topic": topic, "attempt": attempt, **(self._last_llm or {})},
            )
            return
        if not payload:
            # 成功扱いで無言で抜けると「動いているのに更新されない」がログに残らない。
            self._record_event(ctx, persona, f"skipped: no pages returned for {topic}", {"topic": topic})

        candidates = {m.key: m for m in memories}
        existing_slugs = {p.slug for p in pages}
        compiled = 0
        for page in payload:
            try:
                if self._apply_page(ctx, persona, store, topic, page, candidates, existing_slugs, archived_seen):
                    compiled += 1
            except Exception as e:
                logger.warning("WikiWorker: page apply failed (%s): %s", page.get("slug"), e)
                self._record_event(ctx, persona, f"error: page {page.get('slug')} failed: {e}", None)

        logger.info("WikiWorker: persona=%s topic=%s compiled %d pages", persona, topic, compiled)

    def _apply_page(
        self,
        ctx,
        persona: str,
        store: WikiStore,
        topic: str,
        page: dict,
        candidates: dict[str, Memory],
        existing_slugs: set[str],
        archived_seen: set[str],
    ) -> bool:
        """1 ページ分を検証 → ファイル書込み → 索引更新 → 監査。適用したら True。"""
        slug = page.get("slug")
        title = page.get("title")
        body = page.get("body")
        if not isinstance(slug, str) or not isinstance(title, str) or not isinstance(body, str):
            raise ValueError("slug/title/body must be strings")
        if not slug.startswith(f"{topic}-") and slug != topic:
            # クラスタ外 slug は許可しない（topic ファイルの散逸防止）
            raise ValueError(f"slug {slug!r} does not belong to topic {topic!r}")
        if len(body.encode()) > self._cfg.max_page_bytes:
            raise ValueError(f"body too large for {slug}: {len(body.encode())} bytes")

        sources = [s for s in page.get("sources", []) if isinstance(s, str) and s in candidates]
        if not sources:
            raise ValueError(f"page {slug} has no valid sources")
        if len(sources) > self._cfg.max_sources_per_page:
            raise ValueError(f"page {slug} has too many sources ({len(sources)})")

        existing = store.read_page(slug)

        existed = existing.is_ok
        written = store.write_page(
            slug,
            title,
            body,
            project=_project_of(page, topic),
            sources=tuple(sources),
        )
        if isinstance(written, Failure):
            raise RuntimeError(f"write_page failed: {written.error}")
        archived = self._archive_sources(ctx, sources, archived_seen)
        if self.vector_enabled:
            vector_index.sync_page(self._settings, persona, slug, title, body)

        for doomed in page.get("delete", []) or []:
            if isinstance(doomed, str) and doomed in existing_slugs and doomed.startswith(f"{topic}-"):
                store.delete_page(doomed)
                if self.vector_enabled:
                    vector_index.drop_page(self._settings, persona, doomed)

        action = "updated" if existed else "created"
        self._record_event(
            ctx,
            persona,
            f"{action} {slug} from {len(sources)} memories",
            {
                "slug": slug,
                "action": action,
                "topic": topic,
                "sources": sources,
                "deletes": page.get("delete", []),
                "archived": archived,
                "page_hash": _hash_of(title, body),
            },
        )
        return True

    # ------------------------------------------------------------------
    # LLM（provider 解決 + テストフック）
    # ------------------------------------------------------------------

    _ask_llm_for_test: str | None = None
    _ask_llm_raise: Exception | None = None

    def _ask_and_parse(
        self, topic: str, memories: list[Memory], pages: list[WikiPage], now: datetime
    ) -> tuple[list[dict] | None, str, int]:
        """LLM 呼び出し + パース。空応答/切れ JSON は 1 回だけ予算を倍にして再試行。

        reasoning モデルは思考トークンも max_tokens を食うため、長い応答が途中で切れて
        JSON が閉じないことがある（2026-11-09 の本番障害: char 4153 で Unterminated）。
        成功時は (pages, "", 成功した attempt 番号)、失敗時は (None, 監査用メッセージ, 最後の attempt)。
        """
        error = ""
        for attempt in range(self._llm_attempts):
            raw = self._ask_llm(topic, memories, pages, now, boost=attempt)
            if raw is None:
                # collect_text は ErrorEvent で None、本文が無ければ "" を返す（区別できる）。
                error = f"llm stream error for {topic} (attempt {attempt + 1})"
            elif not raw:
                error = f"llm returned no text for {topic} (attempt {attempt + 1})"
            else:
                try:
                    return self._parse_response(raw), "", attempt
                except Exception as e:
                    error = f"invalid llm response for {topic}: {e} (attempt {attempt + 1})"
                    logger.warning("WikiWorker: %s", error)
            if attempt + 1 < self._llm_attempts:
                logger.warning("WikiWorker: retrying %s with a larger budget", topic)
            else:
                return None, error, attempt
        return None, error, self._llm_attempts - 1

    def _ask_llm(
        self, topic: str, memories: list[Memory], pages: list[WikiPage], now: datetime, boost: int = 0
    ) -> str | None:
        if self._ask_llm_raise is not None:
            raise self._ask_llm_raise
        if self._ask_llm_for_test is not None:
            return self._ask_llm_for_test

        cfg = self._cfg
        api_key = cfg.get_effective_api_key(self._settings)
        if not api_key:
            raise RuntimeError("wiki LLM api_key is not configured")

        from nous.infrastructure.llm.base import LLMMessage
        from nous.infrastructure.llm.factory import get_provider
        from nous.infrastructure.llm.text_utils import collect_text

        provider: LLMProvider = get_provider(cfg.provider, api_key, cfg.model, cfg.base_url)
        prompt = self._build_prompt(topic, memories, pages, now)
        max_tokens = self._max_tokens * (2**boost)
        text = asyncio.run(
            collect_text(
                provider,
                messages=[LLMMessage(role="user", content=prompt)],
                system="",
                tools=None,
                temperature=0.0,
                max_tokens=max_tokens,
            )
        )
        # 監査用の計器（attempt / 実際の予算 / 返ってきた本文長 / stream エラーか）。
        self._last_llm = {
            "max_tokens": max_tokens,
            "text_len": len(text or ""),
            "stream_error": text is None,
        }
        return text

    def _build_prompt(self, topic: str, memories: list[Memory], pages: list[WikiPage], now: datetime) -> str:
        page_lines = [
            json.dumps(
                {
                    "slug": p.slug,
                    "title": p.title,
                    "project": p.project,
                    "sources": list(p.sources),
                    "preview": p.body[:_PAGE_PREVIEW_CHARS],
                },
                ensure_ascii=False,
            )
            for p in pages
            if p.slug != "index"
        ]
        memory_lines = [
            json.dumps(
                {
                    "key": m.key,
                    "kind": getattr(m, "kind", "semantic"),
                    "importance": round(float(m.importance), 2),
                    "content": m.content[:_CONTENT_PREVIEW_CHARS],
                },
                ensure_ascii=False,
            )
            for m in memories
        ]
        return _WIKI_PROMPT.format(
            now=now.isoformat(),
            topic=topic,
            slug_prefix=f"{topic}-",
            max_bytes=self._cfg.max_page_bytes,
            pages="\n".join(page_lines) or "(なし)",
            memories="\n".join(memory_lines),
        )

    def _parse_response(self, text: str) -> list[dict]:
        """LLM 応答 → ページ dict のリスト（コードフェンス・前後説明文を許容）。"""
        stripped = text.strip()
        if stripped.startswith("```"):
            stripped = stripped.strip("`")
            if stripped.startswith("json"):
                stripped = stripped[4:]
        start, end = stripped.find("{"), stripped.rfind("}")
        if start < 0 or end <= start:
            raise ValueError("no JSON object found in response")
        # 呼び出し側（_compile_topic）が ValueError/JSONDecodeError を捕捉して
        # 監査に error 行を書きファイルを変えない契約。ここで握り潰さない。
        data = json.loads(stripped[start : end + 1])
        pages = data.get("pages") if isinstance(data, dict) else None
        if not isinstance(pages, list):
            raise ValueError("missing 'pages' array")
        return [p for p in pages if isinstance(p, dict)]

    # ------------------------------------------------------------------
    # session_events 監査
    # ------------------------------------------------------------------

    def _record_event(self, ctx, persona: str, summary: str, detail: dict | None) -> None:
        if summary.startswith("error:"):
            self._cycle_errors += 1
        try:
            from nous.domain.memory.session_event import SessionEvent
            from nous.domain.shared.time_utils import get_now
            from nous.infrastructure.sqlite.session_event_repo import SessionEventRepository

            SessionEventRepository(ctx.connection).insert(
                SessionEvent(
                    session_id="wiki_worker",
                    persona=persona,
                    event_type="wiki.compiled",
                    timestamp=get_now(),
                    summary=summary[:200],
                    detail=json.dumps(detail, ensure_ascii=False) if detail else None,
                    metadata=None,
                )
            )
        except Exception:
            logger.exception("WikiWorker: failed to record event")


def _topic_of(memory: Memory) -> str:
    """記憶 → クラスタ slug（project:* タグ優先、無ければ persona の固定 slug）。"""
    tags = getattr(memory, "tags", None) or []
    for tag in tags:
        if isinstance(tag, str) and tag.startswith("project:"):
            slug = tag.split(":", 1)[1]
            slug = re.sub(r"[^a-z0-9-]+", "-", slug.lower()).strip("-")
            if slug:
                return f"project-{slug}"
    return "persona"


def _page_is_behind(page_updated: str | None, memory_updated: object) -> bool:
    """ページの更新時刻が記憶より古いか（パース不能なら False = 触らない）。

    wiki 側の時刻は秒精度で切り捨てて保存するので、秒未満の差は無視する（slack 2 秒）。
    これを入れないと「同じ秒に書いた記憶」で毎サイクル stale 扱いになる。
    """
    if not page_updated or memory_updated is None:
        return False
    try:
        page_ts = datetime.fromisoformat(page_updated.replace("Z", "+00:00"))
    except ValueError:
        return False
    if isinstance(memory_updated, str):
        try:
            memory_ts = datetime.fromisoformat(memory_updated.replace("Z", "+00:00"))
        except ValueError:
            return False
    elif isinstance(memory_updated, datetime):
        memory_ts = memory_updated
    else:
        return False
    if page_ts.tzinfo is None or memory_ts.tzinfo is None:
        page_ts = page_ts.replace(tzinfo=None)
        memory_ts = memory_ts.replace(tzinfo=None)
    return page_ts < memory_ts - _STALE_SLACK


def _topic_of_page(page: WikiPage) -> str:
    """wiki ページ → クラスタ slug（``_topic_of`` と同じ写像）。"""
    return f"project-{page.project}" if page.project else "persona"


def _project_of(page: dict, topic: str) -> str | None:
    """ページの project 値（topic が project-<slug> なら slug を返す）。"""
    value = page.get("project")
    if isinstance(value, str) and value:
        return value
    if topic.startswith("project-"):
        return topic[len("project-") :]
    return None


def _hash_of(title: str, body: str) -> str:
    from nous.infrastructure.wiki.store import page_hash

    return page_hash(title, body)
