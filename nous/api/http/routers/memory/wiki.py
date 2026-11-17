"""wiki 手動トリガ API（ドリーミング）— 計画書 §4.2「周期 cycle + 手動トリガ API」.

周期 worker は 24h 間隔なので、初回検証やページ修復を即座に流すための入口。
認証は events/ingest と同型（plugin API key）— 外部から書き込みを起こせる面は
既存の外部トリガ面と同じ鍵で守る。
"""

from __future__ import annotations

import asyncio
import re
import secrets
import threading
from typing import TYPE_CHECKING

from starlette.responses import JSONResponse

from nous.api.http.deps import _safe_get_context
from nous.application.wiki.categories import categorize
from nous.application.wiki.vector_index import async_drop_page, async_sync_page
from nous.domain.shared.result import Failure, Success
from nous.infrastructure.logging.structured import get_logger
from nous.infrastructure.wiki.store import WikiStore, WikiStoreError, page_hash

if TYPE_CHECKING:
    from starlette.requests import Request

logger = get_logger(__name__)

#: 手動再編纂のクールダウン（persona → monotonic 秒）。連打で LLM 費用を焼かないため。
_RECOMPILE_COOLDOWN = 60.0
_last_recompile: dict[str, float] = {}


def _audit(ctx, persona: str, summary: str, detail: dict, *, event_type: str = "wiki.compiled") -> None:
    """ダッシュボード発の書込みを session_events に残す（best-effort）。"""
    try:
        import json

        from nous.domain.memory.session_event import SessionEvent
        from nous.domain.shared.time_utils import get_now
        from nous.infrastructure.sqlite.session_event_repo import SessionEventRepository

        SessionEventRepository(ctx.connection).insert(
            SessionEvent(
                session_id="wiki_worker",
                persona=persona,
                event_type=event_type,
                timestamp=get_now(),
                summary=summary[:200],
                detail=json.dumps(detail, ensure_ascii=False),
                metadata=None,
            )
        )
    except Exception:
        logger.warning("wiki audit event failed: %s", summary, exc_info=True)


def _plugin_key_gate(request: Request, ctx) -> JSONResponse | None:
    """plugin API key を検査する（events/ingest と同じ規則）。"""
    plugin_cfg = ctx.settings.plugin
    if not plugin_cfg.enabled:
        return JSONResponse({"error": "Plugin API is disabled"}, status_code=403)
    if not plugin_cfg.api_key:
        return JSONResponse({"error": "Plugin API misconfigured: api_key not set"}, status_code=500)
    auth_header = request.headers.get("authorization", "")
    if not auth_header.startswith("Bearer "):
        return JSONResponse({"error": "Missing or invalid Authorization header"}, status_code=401)
    token = auth_header.removeprefix("Bearer ").strip()
    if not secrets.compare_digest(token, plugin_cfg.api_key):
        return JSONResponse({"error": "Invalid API key"}, status_code=401)
    return None


def _match_lines(body: str, query: str, limit: int = 50) -> list[dict]:
    """本文中の一致行（検索ハイライト用）。``query`` が空なら空リスト。"""
    if not query:
        return []
    regex = re.compile(re.escape(query), re.IGNORECASE)
    return [
        {"line": line_no, "text": line.strip()[:300]}
        for line_no, line in enumerate(body.splitlines(), start=1)
        if regex.search(line)
    ][:limit]


def _backlinks(store: WikiStore, slug: str) -> list[str]:
    """``slug`` を ``[[..]]`` で指しているページ（逆リンク）。"""
    try:
        return sorted(page.slug for page in store.list_pages() if slug in page.links)
    except Exception:
        logger.warning("wiki backlinks failed for %s", slug, exc_info=True)
        return []


def register_wiki_routes(mcp) -> None:
    @mcp.custom_route("/api/wiki/{persona}", methods=["GET"])
    async def wiki_pages(request: Request) -> JSONResponse:
        """wiki ページの一覧（ダッシュボード閲覧用・読み取り専用）。

        ``q`` を渡すと slug / title / 本文のどれかに部分一致するページだけを返す
        （大文字小文字無視。本文一致は一致行数も返す）。
        """
        persona = request.path_params["persona"]
        ctx = _safe_get_context(persona)
        if ctx is None:
            return JSONResponse({"error": "Persona not found"}, status_code=404)
        query = (request.query_params.get("q") or "").strip()
        try:
            store = WikiStore(ctx.settings.data_root, persona)
            pages = store.list_pages()
        except WikiStoreError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)

        body_hits: dict[str, int] = {}
        if query:
            pages, body_hits = _filter_by_query(store, pages, query)
        items = [
            {
                "slug": p.slug,
                "title": p.title,
                "project": p.project,
                "tags": list(p.tags),
                "sources": list(p.sources),
                "links": list(p.links),
                "updated": p.updated,
                "category": categorize(p, persona),
                "body_hits": body_hits.get(p.slug, 0),
            }
            for p in sorted(pages, key=lambda p: p.updated or "", reverse=True)
        ]
        return JSONResponse({"persona": persona, "q": query, "pages": items})

    def _filter_by_query(store: WikiStore, pages: list, query: str) -> tuple[list, dict[str, int]]:
        """slug / title / 本文の部分一致で絞る。

        本文は ``WikiStore.grep``（regex をエスケープしてから渡す）で探す。
        ユーザーの入力をそのまま正規表現にしない（``(`` だけで 500 になる）。
        """
        needle = query.lower()
        hits: dict[str, int] = {}
        try:
            for slug, _line, _text in store.grep(re.escape(query), limit=1000):
                hits[slug] = hits.get(slug, 0) + 1
        except WikiStoreError:
            hits = {}
        kept = []
        for page in pages:
            if needle in page.slug.lower() or needle in page.title.lower() or page.slug in hits:
                kept.append(page)
        return kept, hits

    # 履歴系は ``{slug:path}`` より先に登録する（path 変換が貪欲に食うため）。
    # ``_history`` / ``_restore`` / ``_recompile`` は slug に使えない文字で始まる予約名。
    @mcp.custom_route("/api/wiki/{persona}/_history/{rev:int}/{slug:path}", methods=["GET"])
    async def wiki_revision(request: Request) -> JSONResponse:
        """過去の版 1 つ（本文込み）を返す。"""
        persona = request.path_params["persona"]
        slug = request.path_params["slug"]
        ctx = _safe_get_context(persona)
        if ctx is None:
            return JSONResponse({"error": "Persona not found"}, status_code=404)
        try:
            store = WikiStore(ctx.settings.data_root, persona)
            found = store.read_revision(slug, int(request.path_params["rev"]))
        except WikiStoreError as exc:
            return JSONResponse({"error": str(exc)}, status_code=404)
        if isinstance(found, Failure):
            return JSONResponse({"error": str(found.error)}, status_code=404)
        page = found.value
        current = store.read_page(slug)
        return JSONResponse(
            {
                "slug": slug,
                "rev": int(request.path_params["rev"]),
                "title": page.title,
                "updated": page.updated,
                "sources": list(page.sources),
                "links": list(page.links),
                "body": page.body,
                "current_body": current.value.body if isinstance(current, Success) else "",
            }
        )

    @mcp.custom_route("/api/wiki/{persona}/_history/{slug:path}", methods=["GET"])
    async def wiki_history(request: Request) -> JSONResponse:
        """改訂履歴（新しい順・本文なし）。"""
        persona = request.path_params["persona"]
        slug = request.path_params["slug"]
        ctx = _safe_get_context(persona)
        if ctx is None:
            return JSONResponse({"error": "Persona not found"}, status_code=404)
        try:
            revisions = WikiStore(ctx.settings.data_root, persona).history(slug)
        except WikiStoreError as exc:
            return JSONResponse({"error": str(exc)}, status_code=404)
        return JSONResponse({"slug": slug, "revisions": revisions})

    @mcp.custom_route("/api/wiki/{persona}/_restore/{rev:int}/{slug:path}", methods=["POST"])
    async def wiki_restore(request: Request) -> JSONResponse:
        """過去の版を書き戻す（書き戻し自体も 1 リビジョンとして残る）。"""
        persona = request.path_params["persona"]
        slug = request.path_params["slug"]
        rev = int(request.path_params["rev"])
        ctx = _safe_get_context(persona)
        if ctx is None:
            return JSONResponse({"error": "Persona not found"}, status_code=404)
        try:
            store = WikiStore(ctx.settings.data_root, persona)
            restored = store.restore_revision(slug, rev)
        except WikiStoreError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        if isinstance(restored, Failure):
            return JSONResponse({"error": str(restored.error)}, status_code=404)
        page = restored.value
        try:
            asyncio.create_task(async_sync_page(ctx.settings, persona, page.slug, page.title, page.body))
        except Exception as e:
            logger.warning("wiki restore: vector sync not scheduled for %s: %s", slug, e)
        _audit(ctx, persona, f"restored {slug} to rev {rev}", {"slug": slug, "rev": rev, "via": "dashboard"})
        logger.info("wiki page restored from dashboard: persona=%s slug=%s rev=%s", persona, slug, rev)
        return JSONResponse({"slug": page.slug, "rev": rev, "restored": True, "body": page.body})

    @mcp.custom_route("/api/wiki/{persona}/_recompile", methods=["POST"])
    async def wiki_recompile(request: Request) -> JSONResponse:
        """ダッシュボードからの手動再編纂（プラグイン鍵なし・クールダウン付き）。

        ``POST /api/wiki/run/{persona}`` は plugin API key 前提なのでブラウザからは
        叩けない。ダッシュボード自体が無認証なので別の鍵は持たせられない代わりに、
        persona 単位のクールダウンで連打を防ぐ（逆向きプロキシで認証をかける前提）。
        """
        import time

        persona = request.path_params["persona"]
        ctx = _safe_get_context(persona)
        if ctx is None:
            return JSONResponse({"error": "Persona not found"}, status_code=404)
        if not ctx.settings.wiki.enabled:
            return JSONResponse({"error": "wiki worker is disabled (NOUS_WIKI__ENABLED=false)"}, status_code=409)
        now = time.monotonic()
        last = _last_recompile.get(persona, 0.0)
        if now - last < _RECOMPILE_COOLDOWN:
            wait = int(_RECOMPILE_COOLDOWN - (now - last)) + 1
            return JSONResponse(
                {"error": f"recompile already requested; retry in {wait}s", "retry_after": wait}, status_code=429
            )
        _last_recompile[persona] = now

        def _run() -> None:
            try:
                from nous.application.workers.wiki_worker import WikiWorker

                WikiWorker(ctx.settings)._compile_persona(ctx, persona)
            except Exception:
                logger.exception("wiki dashboard recompile failed for persona=%s", persona)

        threading.Thread(target=_run, daemon=True, name=f"wiki-dashboard-{persona}").start()
        _audit(ctx, persona, "recompile requested from dashboard", {"via": "dashboard"}, event_type="wiki.run")
        logger.info("wiki recompile accepted from dashboard for persona=%s", persona)
        return JSONResponse({"accepted": True, "persona": persona}, status_code=202)

    # GET / PUT / DELETE を 1 つの Route に載せる: 同一 path を複数回 custom_route すると
    # PUT 側で request.json() が空になり "Invalid JSON body" になる（実測）。
    @mcp.custom_route("/api/wiki/{persona}/{slug:path}", methods=["GET", "PUT", "DELETE"])
    async def wiki_page(request: Request) -> JSONResponse:
        """GET: 本文（markdown 生）を返す。PUT: ダッシュボードから保存。DELETE: 削除。"""
        if request.method == "PUT":
            return await _save_page(request)
        if request.method == "DELETE":
            return await _delete_page(request)
        persona = request.path_params["persona"]
        slug = request.path_params["slug"]
        ctx = _safe_get_context(persona)
        if ctx is None:
            return JSONResponse({"error": "Persona not found"}, status_code=404)
        try:
            store = WikiStore(ctx.settings.data_root, persona)
            result = store.read_page(slug)
        except WikiStoreError as exc:
            # 不正 slug / traversal 試行もここに落ちる（存在を漏らさない 404）。
            return JSONResponse({"error": str(exc)}, status_code=404)
        if isinstance(result, Failure):
            return JSONResponse({"error": str(result.error)}, status_code=404)
        page = result.value
        query = (request.query_params.get("q") or "").strip()
        return JSONResponse(
            {
                "slug": page.slug,
                "title": page.title,
                "project": page.project,
                "tags": list(page.tags),
                "sources": list(page.sources),
                "links": list(page.links),
                "backlinks": _backlinks(store, page.slug),
                "matches": _match_lines(page.body, query),
                "q": query,
                "updated": page.updated,
                "body": page.body,
            }
        )

    async def _save_page(request: Request) -> JSONResponse:
        """ダッシュボードからの保存。

        既存ページなら sources / project を引き継ぐ。新規 slug なら空 sources で作る。
        保存後はベクトル索引へ best-effort で反映する（失敗しても保存は成り立つ）。
        """
        persona = request.path_params["persona"]
        slug = request.path_params["slug"]
        ctx = _safe_get_context(persona)
        if ctx is None:
            return JSONResponse({"error": "Persona not found"}, status_code=404)
        try:
            raw = await request.json()
        except Exception as exc:
            logger.warning("wiki save: invalid json body: %s", exc)
            return JSONResponse({"error": "Invalid JSON body"}, status_code=400)
        if not isinstance(raw, dict):
            return JSONResponse({"error": "Invalid JSON body"}, status_code=400)
        body = raw.get("body")
        if not isinstance(body, str) or not body.strip():
            return JSONResponse({"error": "body is required"}, status_code=400)
        try:
            store = WikiStore(ctx.settings.data_root, persona)
        except WikiStoreError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)

        existing = store.read_page(slug)
        prior = existing.value if isinstance(existing, Success) else None
        title = raw.get("title")
        if not isinstance(title, str) or not title.strip():
            title = prior.title if prior else slug
        project = raw.get("project")
        if not isinstance(project, str):
            project = prior.project if prior else None

        written = store.write_page(
            slug,
            title,
            body,
            project=project,
            sources=prior.sources if prior else (),
            tags=prior.tags if prior else (),
        )
        if isinstance(written, Failure):
            return JSONResponse({"error": str(written.error)}, status_code=400)
        page = written.value
        # 索引更新は PUT の成否に影響させない（ファイル層が正）。
        # async_sync_page は内部で失敗を warning にするので、ここは起動失敗だけ拾う。
        try:
            asyncio.create_task(async_sync_page(ctx.settings, persona, page.slug, page.title, page.body))
        except Exception as e:
            logger.warning("wiki save: vector sync not scheduled for %s: %s", slug, e)
        previous = None
        if prior is not None:
            previous = page_hash(prior.title, prior.body)
        _audit(
            ctx,
            persona,
            f"saved {slug} from dashboard",
            {
                "slug": slug,
                "via": "dashboard",
                "action": "updated" if prior is not None else "created",
                "previous_hash": previous,
                "page_hash": page_hash(page.title, page.body),
                "sources": list(page.sources),
                "source_count": len(page.sources),
            },
            event_type="wiki.saved",
        )
        logger.info("wiki page saved from dashboard: persona=%s slug=%s", persona, slug)
        return JSONResponse(
            {
                "slug": page.slug,
                "title": page.title,
                "project": page.project,
                "tags": list(page.tags),
                "sources": list(page.sources),
                "links": list(page.links),
                "updated": page.updated,
                "body": page.body,
            }
        )

    async def _delete_page(request: Request) -> JSONResponse:
        """ダッシュボードからの削除。

        存在しない slug は 404（「消した」と言い切らない）。削除後の索引落としは
        best-effort（ファイル層が正。索引は次サイクルの再同期で追いつく）。
        """
        persona = request.path_params["persona"]
        slug = request.path_params["slug"]
        ctx = _safe_get_context(persona)
        if ctx is None:
            return JSONResponse({"error": "Persona not found"}, status_code=404)
        try:
            store = WikiStore(ctx.settings.data_root, persona)
        except WikiStoreError as exc:
            return JSONResponse({"error": str(exc)}, status_code=404)
        existing = store.read_page(slug)
        if isinstance(existing, Failure):
            return JSONResponse({"error": f"wiki page not found: {slug}"}, status_code=404)
        result = store.delete_page(slug)
        if isinstance(result, Failure):
            return JSONResponse({"error": str(result.error)}, status_code=400)
        try:
            asyncio.create_task(async_drop_page(ctx.settings, persona, slug))
        except Exception as e:
            logger.warning("wiki delete: vector drop not scheduled for %s: %s", slug, e)
        logger.info("wiki page deleted from dashboard: persona=%s slug=%s", persona, slug)
        _audit(
            ctx,
            persona,
            f"deleted {slug} from dashboard",
            {"slug": slug, "title": existing.value.title, "via": "dashboard"},
            event_type="wiki.deleted",
        )
        return JSONResponse({"slug": slug, "deleted": True, "title": existing.value.title})

    @mcp.custom_route("/api/wiki/run/{persona}", methods=["POST"])
    async def wiki_run(request: Request) -> JSONResponse:
        """1 cycle を即時実行する（非同期・202 で受付だけ返す）。"""
        persona = request.path_params["persona"]
        ctx = _safe_get_context(persona)
        if ctx is None:
            return JSONResponse({"error": "Persona not found"}, status_code=404)

        rejected = _plugin_key_gate(request, ctx)
        if rejected is not None:
            return rejected
        if not ctx.settings.wiki.enabled:
            return JSONResponse({"error": "wiki worker is disabled (NOUS_WIKI__ENABLED=false)"}, status_code=409)

        def _run() -> None:
            try:
                from nous.application.workers.wiki_worker import WikiWorker

                WikiWorker(ctx.settings)._compile_persona(ctx, persona)
            except Exception:
                logger.exception("wiki manual run failed for persona=%s", persona)

        threading.Thread(target=_run, daemon=True, name=f"wiki-manual-{persona}").start()
        logger.info("wiki run accepted for persona=%s", persona)
        return JSONResponse({"accepted": True, "persona": persona}, status_code=202)
