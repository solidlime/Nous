"""Auto-generated from tools.py split — _tools_skill.py."""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING

from nous.api.mcp._tools_helpers import tool_called_audited

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from nous.application.use_cases import AppContext


@tool_called_audited("invoke_skill")
async def _tool_invoke_skill(ctx: AppContext, persona: str, name: str, task: str) -> dict:
    """スキルの完全な指示内容を返す。別LLMは呼び出さない。

    システムプロンプトにはスキル名と説明のみが注入され、スキルの詳細（content）は含まれていない。
    ペルソナはこのツールを呼ぶことで初めてスキルの完全な指示を取得できる。

    検索順序: persona スキル（persist=False, インメモリ）→ グローバルスキルDB
    task パラメータは後方互換のため残しているが、現在は使用されていない。
    """
    from nous.config.settings import get_settings
    from nous.domain.skill import SkillRepository

    settings = get_settings()
    skill_repo = SkillRepository()

    # persona スキルを優先
    persona_skills_dir = os.path.join(settings.data_root, "persona", persona, "skills")
    if os.path.isdir(persona_skills_dir):
        persona_skills = skill_repo.load_from_dir(persona_skills_dir, persist=False)
        for s in persona_skills:
            if s.name == name:
                logger.info("invoke_skill response: '%s' → %d lines returned", name, len(s.content.splitlines()))
                return {"ok": True, "result": s.content}

    # グローバルスキルにフォールバック
    global_skills = skill_repo.load_from_dir(settings.skills_dir, persist=False)
    for s in global_skills:
        if s.name == name:
            logger.info("invoke_skill response: '%s' → %d lines returned", name, len(s.content.splitlines()))
            return {"ok": True, "result": s.content}

    return {"ok": False, "error": f"Skill '{name}' not found"}
