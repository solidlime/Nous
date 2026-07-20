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
        from nous.domain.skill import SkillRepository
        from nous.config.settings import get_settings

        repo = SkillRepository()
        skills = repo.load_from_dir(get_settings().skills_dir, persist=False)
        return JSONResponse([s.model_dump() for s in skills])

    @mcp.custom_route("/api/skills", methods=["POST"])
    async def create_skill(request: Request) -> JSONResponse:
        return JSONResponse({"error": "Not implemented — skills are managed via filesystem"}, status_code=501)

    @mcp.custom_route("/api/skills/{name}", methods=["PUT"])
    async def update_skill(request: Request) -> JSONResponse:
        return JSONResponse({"error": "Not implemented — skills are managed via filesystem"}, status_code=501)

    @mcp.custom_route("/api/skills/{name}", methods=["DELETE"])
    async def delete_skill(request: Request) -> JSONResponse:
        return JSONResponse({"error": "Not implemented — skills are managed via filesystem"}, status_code=501)

    @mcp.custom_route("/api/skills/sync", methods=["POST"])
    async def sync_skills(request: Request) -> JSONResponse:
        return JSONResponse({"synced": 0, "skills": []})
