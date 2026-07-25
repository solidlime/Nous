from __future__ import annotations

import json
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

    @mcp.custom_route("/api/skills", methods=["POST"])
    async def create_skill(request: Request) -> JSONResponse:
        from nous.config.settings import get_settings
        from nous.domain.skill import Skill, SkillRepository

        try:
            body = await request.json()
        except (json.JSONDecodeError, TypeError):
            return JSONResponse({"error": "Invalid JSON body"}, status_code=400)

        name = (body.get("name") or "").strip()
        if not name:
            return JSONResponse({"error": "Skill name is required"}, status_code=400)

        skill = Skill(
            name=name,
            description=body.get("description", ""),
            content=body.get("content", ""),
            license=body.get("license"),
            compatibility=body.get("compatibility"),
            metadata=body.get("metadata"),
        )
        repo = SkillRepository()
        repo.save_to_file(skill, get_settings().skills_dir)
        return JSONResponse(skill.model_dump(), status_code=201)

    @mcp.custom_route("/api/skills/{name}", methods=["PUT"])
    async def update_skill(request: Request) -> JSONResponse:
        from nous.config.settings import get_settings
        from nous.domain.skill import Skill, SkillRepository

        skill_name = request.path_params["name"]
        try:
            body = await request.json()
        except (json.JSONDecodeError, TypeError):
            return JSONResponse({"error": "Invalid JSON body"}, status_code=400)

        skill = Skill(
            name=skill_name,
            description=body.get("description", ""),
            content=body.get("content", ""),
            license=body.get("license"),
            compatibility=body.get("compatibility"),
            metadata=body.get("metadata"),
        )
        repo = SkillRepository()
        repo.save_to_file(skill, get_settings().skills_dir)
        return JSONResponse(skill.model_dump())

    @mcp.custom_route("/api/skills/{name}", methods=["DELETE"])
    async def delete_skill(request: Request) -> JSONResponse:
        from nous.config.settings import get_settings
        from nous.domain.skill import SkillRepository

        skill_name = request.path_params["name"]
        repo = SkillRepository()
        repo.delete_from_fs(skill_name, get_settings().skills_dir)
        return JSONResponse({"deleted": skill_name})

    @mcp.custom_route("/api/skills/sync", methods=["POST"])
    async def sync_skills(request: Request) -> JSONResponse:
        return JSONResponse({"synced": 0, "skills": []})
