"""観測性メトリクス API（kanban #10）.

- 検索の p50/p95 と zero-result 率、ツール呼び出し回数 → プロセス内レジストリ
  （``nous/infrastructure/metrics/registry.py``）。再起動で消える。
- 編纂の件数 → ``session_events`` を event_type 別に集計（恒久記録側）。

ダッシュボードの Activity タブが 1 行で表示する。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from starlette.responses import JSONResponse

from nous.api.http.deps import _safe_get_context
from nous.infrastructure.logging.structured import get_logger
from nous.infrastructure.metrics import registry

if TYPE_CHECKING:
    from starlette.requests import Request

logger = get_logger(__name__)

#: 集計対象のイベント種別（ダッシュボードで意味のあるものだけ）。
WIKI_EVENT_TYPES = ("wiki.compiled", "wiki.saved", "wiki.deleted", "wiki.run", "wiki.conflict")


def _event_counts(ctx, persona: str, prefix: str) -> dict[str, int]:
    """``session_events`` から指定接頭辞のイベント件数を数える（失敗しても空）。"""
    try:
        rows = ctx.connection.execute(
            """
            SELECT event_type, COUNT(*) FROM session_events
            WHERE persona = ? AND event_type LIKE ?
            GROUP BY event_type
            """,
            (persona, f"{prefix}%"),
        ).fetchall()
        return {str(event_type): int(count) for event_type, count in rows}
    except Exception:
        logger.debug("metrics: event counts failed for %s", prefix, exc_info=True)
        return {}


def register_metrics_routes(mcp) -> None:
    @mcp.custom_route("/api/metrics/{persona}", methods=["GET"])
    async def metrics(request: Request) -> JSONResponse:
        """persona の観測値（検索・ツール・wiki 編纂）。"""
        persona = request.path_params["persona"]
        ctx = _safe_get_context(persona)
        if ctx is None:
            return JSONResponse({"error": "Persona not found"}, status_code=404)
        snap = registry.snapshot(persona)
        wiki = _event_counts(ctx, persona, "wiki.")
        tool_events = _event_counts(ctx, persona, "tool.")
        return JSONResponse(
            {
                "persona": persona,
                "search": snap["search"],
                "tools": snap["tools"],
                "wiki": {name: wiki.get(name, 0) for name in WIKI_EVENT_TYPES},
                "events": tool_events,
                # プロセス内の値であることをフロントに明示する。
                "scopes": {"search": "process", "tools": "process", "wiki": "durable", "events": "durable"},
            }
        )
