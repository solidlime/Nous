"""PromptBuildStep: systemプロンプトの組み立て。"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from nous.application.chat.pipeline.prepare import RECALL_ANNOTATION_GUIDELINES
from nous.infrastructure.logging.structured import get_logger

if TYPE_CHECKING:
    from nous.application.chat.pipeline.context import ChatTurnContext
    from nous.application.use_cases import AppContext
    from nous.domain.chat_config import ChatConfig

logger = get_logger(__name__)


def _build_relationship_context(db, persona: str) -> str:
    """Build relationship context summary from interaction history.
    Returns empty string if no interaction history exists."""
    # First interaction time
    row = db.execute(
        "SELECT MIN(created_at) FROM session_events WHERE persona = ?",
        (persona,),
    ).fetchone()
    first_at_str = row[0] if row and row[0] else None
    if not first_at_str:
        return ""  # No history at all

    first_at = datetime.fromisoformat(first_at_str)
    now = datetime.now(UTC)
    days_known = (now - first_at.replace(tzinfo=UTC)).days

    # Active days (distinct dates with events)
    row = db.execute(
        "SELECT COUNT(DISTINCT DATE(created_at)) FROM session_events WHERE persona = ?",
        (persona,),
    ).fetchone()
    active_days = row[0] if row else 0

    # Time since last conversation
    row = db.execute(
        "SELECT value FROM context_state WHERE persona = ? AND key = 'last_conversation_time' AND valid_until IS NULL",
        (persona,),
    ).fetchone()
    last_time_str = row[0] if row else None
    days_since_last = None
    if last_time_str:
        try:
            last_at = datetime.fromisoformat(last_time_str)
            days_since_last = (now - last_at.replace(tzinfo=UTC)).days
        except (ValueError, TypeError):
            pass

    lines = ["\n--- 関係性コンテキスト ---"]
    if days_known == 0:
        lines.append("このユーザーと初めて会話する。")
    elif days_known == 1:
        lines.append(f"昨日から知り合った。これまで {active_days} 日会話した。")
    else:
        lines.append(f"{days_known}日前から知り合い。これまで {active_days} 日会話した。")

    if days_since_last is not None:
        if days_since_last == 0:
            pass  # Same day, skip
        elif days_since_last == 1:
            lines.append("前回の会話から1日経過。")
        elif days_since_last < 7:
            lines.append(f"前回の会話から{days_since_last}日経過。")
        elif days_since_last < 30:
            lines.append(f"前回の会話から{days_since_last}日経過。しばらく話していない。")
        else:
            lines.append(f"前回の会話から{days_since_last}日経過。長い間話していなかった。")

    return "\n".join(lines)


class PromptBuildStep:
    """systemプロンプトを組み立てる。"""

    def __init__(self) -> None:
        pass

    def run(
        self,
        ctx: AppContext,
        config: ChatConfig,
        turn_ctx: ChatTurnContext,
    ) -> None:
        """ChatTurnContext.system_prompt を設定する。同期メソッド。"""
        persona = ctx.persona

        base_system = config.system_prompt or f"あなたは{persona}という名前のアシスタントです。"
        parts = [base_system]

        if turn_ctx.context_section:
            parts.append(f"\n--- ペルソナ状態・コンテキスト ---\n{turn_ctx.context_section}")
        if turn_ctx.related_memories:
            parts.append(f"\n{RECALL_ANNOTATION_GUIDELINES}\n--- 関連記憶 ---\n{turn_ctx.related_memories}")

        skills_raw: list[dict] = []
        if config.enabled_skills:
            try:
                from nous.config.settings import get_settings
                from nous.domain.skill import SkillRepository
                from nous.infrastructure.sqlite.connection import get_global_skills_db

                skill_repo = SkillRepository(get_global_skills_db(get_settings().data_root))
                skills = [skill_repo.get(n) for n in config.enabled_skills]
                skill_lines = []
                for s in skills:
                    if not s:
                        continue
                    # L1: name + short description only (~100 tokens/skill)
                    desc = (s.description or "")[:120]
                    line = f"- {s.name}: {desc}"
                    skill_lines.append(line)
                skills_raw = [s.model_dump() for s in skills if s]
                if skill_lines:
                    parts.append(
                        "\n--- 利用可能なSkill ---\n"
                        + "\n".join(skill_lines)
                        + "\n\n各スキルの詳細な使い方は invoke_skill ツールで読み込めます。"
                    )
            except Exception as e:
                logger.warning("PromptBuildStep: skills load failed: %s", e)

        # Author's Note: inject at end of system prompt if set
        author_note = getattr(turn_ctx, "author_note", None)
        if author_note:
            parts.append(f"\n[Author's Note]\n{author_note}")

        # Relationship context: inject interaction history summary
        try:
            relationship_ctx = _build_relationship_context(ctx.connection.get_memory_db(), persona)
            if relationship_ctx:
                parts.append(relationship_ctx)
        except Exception as e:
            logger.warning("PromptBuildStep: relationship context build failed: %s", e)

        turn_ctx.system_prompt = "\n".join(parts)
        turn_ctx.skills_raw = skills_raw
