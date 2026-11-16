from __future__ import annotations

import os
import re
from typing import TYPE_CHECKING, Any

from starlette.responses import JSONResponse

from nous.infrastructure.logging.structured import get_logger

if TYPE_CHECKING:
    from starlette.requests import Request

logger = get_logger(__name__)

# パストラバーサル防止。persona 名はディレクトリ名になる。
_PERSONA_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,62}$")


def register_skills_routes(mcp) -> None:

    def _merged(persona: str | None) -> list[dict[str, Any]]:
        """グローバル → ペルソナの順に読み、同名はペルソナで上書きする。"""
        from nous.config.settings import get_settings
        from nous.domain.skill import SkillRepository

        settings = get_settings()
        repo = SkillRepository()
        merged: dict[str, Any] = {}
        for skill in repo.load_from_dir(settings.skills_dir, persist=False):
            merged[skill.name] = skill
        if persona and _PERSONA_RE.match(persona):
            persona_dir = os.path.join(settings.persona_dir, persona, "skills")
            if os.path.isdir(persona_dir):
                for skill in repo.load_from_dir(persona_dir, persist=False):
                    merged[skill.name] = skill
        return [s.model_dump() for s in merged.values()]

    @mcp.custom_route("/api/skills", methods=["GET"])
    async def list_skills(request: Request) -> JSONResponse:
        return JSONResponse(_merged(None))

    @mcp.custom_route("/api/skills/{persona}", methods=["GET"])
    async def list_persona_skills(request: Request) -> JSONResponse:
        """ペルソナ専用スキルをグローバルに重ねた一覧（sandbox 内の見え方と同じ）。"""
        return JSONResponse(_merged(request.path_params["persona"]))

    # d3: 書系4EP削除（POST /api/skills・PUT/DELETE /api/skills/{name}・POST /api/skills/sync）
    # 内部使用ゼロ（GETのみchat-core.js:456が使用）。外部互換不問のため削除。
