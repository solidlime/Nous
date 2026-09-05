from __future__ import annotations

from typing import TYPE_CHECKING

from starlette.responses import JSONResponse

from nous.infrastructure.logging.structured import get_logger

if TYPE_CHECKING:
    from starlette.requests import Request

logger = get_logger(__name__)


def register_skills_routes(mcp) -> None:

    @mcp.custom_route("/api/skills", methods=["GET"])
    async def list_skills(request: Request) -> JSONResponse:
        from nous.config.settings import get_settings
        from nous.domain.skill import SkillRepository

        repo = SkillRepository()
        skills = repo.load_from_dir(get_settings().skills_dir, persist=False)
        return JSONResponse([s.model_dump() for s in skills])

    # d3: 書系4EP削除（POST /api/skills・PUT/DELETE /api/skills/{name}・POST /api/skills/sync）
    # 内部使用ゼロ（GETのみchat-core.js:456が使用）。外部互換不問のため削除。
