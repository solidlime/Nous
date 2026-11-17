"""プロジェクト文脈ビュー API（kanban #8）.

``project:<slug>`` タグ付きの記憶・未解決の問い・決定事項と、``project`` が一致する
wiki ページを 1 つのビューに集約する。新しい集計ロジックは持たず、既存の
「project:* タグ」規約（``nous/api/mcp/_tools_memory.py``）と未解決質問の規約
（``nous/application/wiki/questions.py``）を読むだけ。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from starlette.responses import JSONResponse

from nous.api.http.deps import _safe_get_context
from nous.application.wiki.questions import (
    is_open_question,
    question_key_of,
)
from nous.domain.memory.type_classifier import classify
from nous.domain.shared.result import Failure
from nous.infrastructure.logging.structured import get_logger
from nous.infrastructure.wiki.store import WikiStore, WikiStoreError

if TYPE_CHECKING:
    from starlette.requests import Request

logger = get_logger(__name__)

#: 1 セクションあたりに返す最大件数。ビューは眺める用なので絞る。
SECTION_LIMIT = 30


def _project_tag(slug: str) -> str:
    return f"project:{slug.strip().lower()}"


def _memories_with(ctx, tag: str) -> list:
    """``tag`` を持つ記憶（新しい順）。repo はペルソナ DB 単位。"""
    result = ctx.memory_repo.find_all()
    if isinstance(result, Failure):
        logger.warning("project context: find_all failed: %s", result.error)
        return []
    found = [m for m in result.value if tag in (getattr(m, "tags", ()) or ())]
    found.sort(key=_timestamp, reverse=True)
    return found


def _timestamp(memory: object) -> float:
    value = getattr(memory, "created_at", None) or getattr(memory, "updated_at", None)
    return float(value.timestamp()) if value is not None and hasattr(value, "timestamp") else 0.0


def _item(memory: object) -> dict:
    """記憶 1 件を JSON 向けに落とす（本文は先頭 400 字）。"""
    created = getattr(memory, "created_at", None)
    return {
        "key": str(getattr(memory, "key", "") or ""),
        "content": str(getattr(memory, "content", "") or "")[:400],
        "created_at": str(created.isoformat()) if created is not None else None,
        "importance": getattr(memory, "importance", None),
        "tags": list(getattr(memory, "tags", ()) or ()),
        "question_key": question_key_of(memory),
    }


def _wiki_pages(store: WikiStore, slug: str) -> list[dict]:
    """``project`` が slug に一致するページ（新しい順）。"""
    needle = slug.strip().lower()
    try:
        pages = store.list_pages()
    except WikiStoreError as exc:
        logger.warning("project context: wiki list failed: %s", exc)
        return []
    return [
        {
            "slug": p.slug,
            "title": p.title,
            "updated": p.updated,
            "sources": list(p.sources),
            "links": list(p.links),
        }
        for p in sorted(pages, key=lambda p: p.updated or "", reverse=True)
        if (p.project or "").strip().lower() == needle
    ]


def register_project_context_routes(mcp) -> None:
    @mcp.custom_route("/api/project/{persona}/{slug}/context", methods=["GET"])
    async def project_context(request: Request) -> JSONResponse:
        """``project:<slug>`` の集約ビュー（決定事項・問い・wiki・タイムライン）。"""
        persona = request.path_params["persona"]
        slug = request.path_params["slug"].strip().lower()
        ctx = _safe_get_context(persona)
        if ctx is None:
            return JSONResponse({"error": "Persona not found"}, status_code=404)
        if not slug:
            return JSONResponse({"error": "project slug is required"}, status_code=400)

        tag = _project_tag(slug)
        memories = _memories_with(ctx, tag)
        questions = [m for m in memories if is_open_question(m)]
        # 決定事項は type タグ（auto_tags が付ける "decision"）で判定する。
        # タグ欠けの古い記憶も拾えるよう、タグ無しは本文分類にフォールバックする。
        decisions = [
            m
            for m in memories
            if "decision" in (getattr(m, "tags", ()) or ())
            or (
                not (set(getattr(m, "tags", ()) or ()) & {"decision", "problem", "milestone"})
                and classify(str(getattr(m, "content", "") or "")) == "decision"
            )
        ]
        try:
            wiki = _wiki_pages(WikiStore(ctx.settings.data_root, persona), slug)
        except WikiStoreError as exc:
            logger.warning("project context: store open failed: %s", exc)
            wiki = []

        return JSONResponse(
            {
                "persona": persona,
                "project": slug,
                "tag": tag,
                "counts": {
                    "memories": len(memories),
                    "decisions": len(decisions),
                    "open_questions": len(questions),
                    "wiki": len(wiki),
                },
                "decisions": [_item(m) for m in decisions[:SECTION_LIMIT]],
                "open_questions": [_item(m) for m in questions[:SECTION_LIMIT]],
                "wiki": wiki[:SECTION_LIMIT],
                "timeline": [_item(m) for m in memories[:SECTION_LIMIT]],
            }
        )
