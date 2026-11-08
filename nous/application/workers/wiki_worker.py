"""WikiWorker — ドリーミング（wiki 編纂）worker。

計画書: ``docs/superpowers/plans/2026-11-07-wiki-dreaming.md`` §4.2。

既存の FreshnessWorker（記憶の鮮度評価）を置き換えず、**別レイヤ**として動く:

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
from typing import TYPE_CHECKING

from nous.domain.shared.result import Failure, Success
from nous.infrastructure.logging.structured import get_logger

if TYPE_CHECKING:
    from datetime import datetime

    from nous.config.settings import Settings, WikiConfig
    from nous.domain.memory.entities import Memory
    from nous.infrastructure.llm.base import LLMProvider
    from nous.infrastructure.wiki.store import WikiPage, WikiStore

logger = get_logger(__name__)

#: 編纂対象クラスタの最小記憶数（これ未満の topic はページ化しない）。
MIN_TOPIC_MEMORIES = 3

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
    """wiki 編纂 worker（FreshnessWorker と同じ thread + graceful shutdown パターン）。"""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        cfg: WikiConfig = settings.wiki
        self._cfg = cfg
        self.interval_seconds = cfg.interval_seconds
        self._running = False
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        #: テスト用: False にすると Qdrant 索引更新を行わない（既定は有効）。
        self.vector_enabled = True

    # ------------------------------------------------------------------
    # lifecycle（FreshnessWorker と同型）
    # ------------------------------------------------------------------

    def start(self) -> None:
        if self._running:
            return
        self._stop_event.clear()
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True, name="wiki-worker")
        self._thread.start()
        logger.info("WikiWorker started (interval=%ds topics=%d)", self.interval_seconds, self._cfg.topics_per_cycle)

    def stop(self, timeout: float = 5.0) -> None:
        self._running = False
        self._stop_event.set()
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=timeout)
        logger.info("WikiWorker stopped")

    def _run(self) -> None:
        while not self._stop_event.is_set():
            try:
                self.run_cycle()
            except Exception:
                logger.exception("Wiki cycle failed")
            self._stop_event.wait(self.interval_seconds)

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
        topics = [(slug, mems) for slug, mems in buckets.items() if len(mems) >= MIN_TOPIC_MEMORIES]
        topics.sort(key=lambda item: (item[0] not in stale, -len(item[1])))
        selected = topics[: self._cfg.topics_per_cycle]
        return [(slug, self._most_recent(mems)) for slug, mems in selected]

    def _stale_topics(self, store: WikiStore, memories: list[Memory], persona: str) -> set[str]:
        """source が非 active・消滅・または記憶がページより新しい topic を返す。"""
        by_key = {m.key: m for m in memories}
        stale: set[str] = set()
        for page in store.list_pages():
            if not page.sources:
                continue
            topic = f"project-{page.project}" if page.project else "persona"
            for key in page.sources:
                memory = by_key.get(key)
                if memory is None or memory.lifecycle_status != "active":
                    stale.add(topic)
                    break
                if _page_is_behind(page.updated, getattr(memory, "updated_at", None) or memory.created_at):
                    stale.add(topic)
                    break
        return stale

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
                store.write_page(slug, page.title, body, project=page.project, sources=page.sources)
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

        now = get_now()
        store = WikiStore(self._settings.data_root, persona)
        all_result = ctx.memory_repo.find_all()
        memories: list[Memory] = list(all_result.value) if isinstance(all_result, Success) else []
        for topic, selected in self._select_topics(memories, now, store, persona):
            try:
                self._compile_topic(ctx, persona, store, topic, selected, now)
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
    ) -> None:
        pages = store.list_pages()
        raw = self._ask_llm(topic, memories, pages, now)
        if not raw:
            self._record_event(ctx, persona, f"error: llm returned no text for {topic}", None)
            return
        try:
            payload = self._parse_response(raw)
        except Exception as e:
            logger.warning("WikiWorker: invalid LLM response for %s: %s", topic, e)
            self._record_event(ctx, persona, f"error: invalid llm response for {topic}: {e}", None)
            return

        candidate_keys = {m.key for m in memories}
        existing_slugs = {p.slug for p in pages}
        compiled = 0
        for page in payload:
            try:
                if self._apply_page(ctx, persona, store, topic, page, candidate_keys, existing_slugs):
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
        candidate_keys: set[str],
        existing_slugs: set[str],
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

        sources = [s for s in page.get("sources", []) if isinstance(s, str) and s in candidate_keys]
        if not sources:
            raise ValueError(f"page {slug} has no valid sources")
        if len(sources) > self._cfg.max_sources_per_page:
            raise ValueError(f"page {slug} has too many sources ({len(sources)})")

        existing = store.read_page(slug)
        if isinstance(existing, Success) and existing.value.manual:
            # ユーザーがダッシュボードで書いたページは編纂で上書きしない
            # （上書きすると編集が 24h 以内に消える）。監査だけ残して飛ばす。
            self._record_event(ctx, persona, f"skipped {slug}: manual page kept", {"slug": slug, "topic": topic})
            return False

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
        if self.vector_enabled:
            self._sync_vector(persona, slug, title, body)

        for doomed in page.get("delete", []) or []:
            if isinstance(doomed, str) and doomed in existing_slugs and doomed.startswith(f"{topic}-"):
                store.delete_page(doomed)
                if self.vector_enabled:
                    self._drop_vector(persona, doomed)

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
                "page_hash": _hash_of(title, body),
            },
        )
        return True

    # ------------------------------------------------------------------
    # LLM（FreshnessWorker と同じ provider 解決 + テストフック）
    # ------------------------------------------------------------------

    _ask_llm_for_test: str | None = None
    _ask_llm_raise: Exception | None = None

    def _ask_llm(self, topic: str, memories: list[Memory], pages: list[WikiPage], now: datetime) -> str | None:
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
        return asyncio.run(
            collect_text(
                provider,
                messages=[LLMMessage(role="user", content=prompt)],
                system="",
                tools=None,
                temperature=0.0,
                max_tokens=16000,
            )
        )

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
    # Qdrant 索引（collection prefix "wiki_"。失敗してもファイル層は正）
    # ------------------------------------------------------------------

    def _sync_vector(self, persona: str, slug: str, title: str, body: str) -> None:
        from nous.application import use_cases

        cfg = self._settings

        async def _run() -> None:
            mgr = use_cases.QdrantClientManager(cfg.qdrant.url, cfg.qdrant.api_key)
            try:
                await mgr.connect()
                if not await mgr.health_check():
                    return
                store = use_cases.QdrantVectorStore(mgr, _embedding(self._settings), "wiki_")
                await store.ensure_collection(persona)
                await store.upsert(persona, slug, f"{title}\n\n{body}")
            finally:
                close = getattr(mgr, "close", None)
                if close is not None:
                    result = close()
                    if asyncio.iscoroutine(result):
                        await result

        try:
            asyncio.run(_run())
        except Exception as e:
            logger.warning("WikiWorker: vector upsert failed for %s: %s", slug, e)

    def _drop_vector(self, persona: str, slug: str) -> None:
        from nous.application import use_cases

        cfg = self._settings

        async def _run() -> None:
            mgr = use_cases.QdrantClientManager(cfg.qdrant.url, cfg.qdrant.api_key)
            try:
                await mgr.connect()
                if not await mgr.health_check():
                    return
                store = use_cases.QdrantVectorStore(mgr, _embedding(self._settings), "wiki_")
                await store.delete(persona, slug)
            finally:
                close = getattr(mgr, "close", None)
                if close is not None:
                    result = close()
                    if asyncio.iscoroutine(result):
                        await result

        try:
            asyncio.run(_run())
        except Exception as e:
            logger.warning("WikiWorker: vector delete failed for %s: %s", slug, e)

    # ------------------------------------------------------------------
    # session_events 監査
    # ------------------------------------------------------------------

    def _record_event(self, ctx, persona: str, summary: str, detail: dict | None) -> None:
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
    """ページの更新時刻が記憶より古いか（パース不能なら False = 触らない）。"""
    from datetime import datetime

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
        return page_ts.replace(tzinfo=None) < memory_ts.replace(tzinfo=None)
    return page_ts < memory_ts


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


def _embedding(settings: Settings):
    """共有 EmbeddingModel（AppContext と同じ resolution を使う）。"""
    from nous.application.use_cases import AppContextRegistry

    for persona in list(AppContextRegistry._contexts.keys()):
        ctx = AppContextRegistry.get(persona)
        model = getattr(ctx, "embedding_model", None)
        if model is not None:
            return model
    raise RuntimeError("no embedding model available")
