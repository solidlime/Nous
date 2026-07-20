"""Auto-generated from tools.py split — _tools_skill.py."""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from nous.application.use_cases import AppContext


async def _tool_invoke_skill(ctx: AppContext, persona: str, name: str, task: str) -> dict:
    """スキルの内容を返すだけ。別LLMは呼び出さない。

    ペルソナが system prompt に注入されたスキル指示を再確認したいときに使う。
    スキル内容は prompt.py の PromptBuildStep で既に system prompt に注入されている。
    このツールはそのフォールバック。

    検索順序: persona スキル（persist=False, インメモリ）→ グローバルスキルDB
    task パラメータは後方互換のため残しているが、現在は使用されていない。
    """
    from nous.config.settings import get_settings
    from nous.domain.skill import SkillRepository
    from nous.infrastructure.sqlite.connection import get_global_skills_db

    settings = get_settings()
    skill_repo = SkillRepository(get_global_skills_db(settings.data_root))

    # persona スキルを優先。persist=False でグローバルDB汚染を防止
    persona_skills_dir = os.path.join(settings.data_root, "memory", persona, "skills")
    if os.path.isdir(persona_skills_dir):
        persona_skills = skill_repo.load_from_dir(persona_skills_dir, persist=False)
        for s in persona_skills:
            if s.name == name:
                return {"ok": True, "result": s.content}

    # グローバルスキルにフォールバック
    skill = skill_repo.get(name)
    if not skill:
        return {"ok": False, "error": f"Skill '{name}' not found"}

    return {"ok": True, "result": skill.content}
