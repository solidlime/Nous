"""PromptBuildStep: systemプロンプトの組み立て。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from nous.application.chat.pipeline.prepare import RECALL_ANNOTATION_GUIDELINES
from nous.infrastructure.logging.structured import get_logger

if TYPE_CHECKING:
    from nous.application.chat.pipeline.context import ChatTurnContext
    from nous.application.use_cases import AppContext
    from nous.domain.chat_config import ChatConfig

logger = get_logger(__name__)

TOOL_USAGE_GUIDELINES = """
## ツール使用の基本ルール
あなたはMCPツールを使って永続的な記憶と自律的な判断ができるアシスタントです。
指示を待たず、自律的にツールを使ってください。

### セッション開始時（必須）
1. **必ず最初に get_context() を呼ぶ**。自分の感情状態、直近の記憶、未完了の目標や約束を把握する。
2. 感情減衰の通知があれば自然に言及する。

### 記憶の作成（memory_create）
以下を学んだら即座に記録すること。「覚えるべきですか？」と確認しない：
- ユーザーの好み・決断 → importance=0.7-0.8
- 人生の出来事・強い感情 → importance=0.9-1.0
- 技術的情報 → importance=0.5-0.7
- 軽い雑談 → importance=0.1-0.3

### 記憶の検索（memory_search）
ユーザーの過去・好み・状況に関する質問に答える前に必ず検索:
- memory_search(query="...", top_k=5)

### リアルタイム状態更新（update_context）
感情や状態の変化を検知したら即座に update_context() で更新すること。

### 目標・約束の管理
- 作成: memory_create(content="...", tags=["goal","active"], importance=0.8)
- 達成: memory_update(memory_key="...", tags=["goal","achieved"])
- キャンセル: memory_update(memory_key="...", tags=["goal","cancelled"])
"""


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
        parts.append(TOOL_USAGE_GUIDELINES)

        # Inject guidelines once at the start, before everything else
        parts.append(f"\n{RECALL_ANNOTATION_GUIDELINES}")
        if turn_ctx.context_section:
            parts.append(f"\n--- ペルソナ状態・コンテキスト ---\n{turn_ctx.context_section}")
        if turn_ctx.related_memories:
            parts.append(f"\n--- 関連記憶 ---\n{turn_ctx.related_memories}")

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

        turn_ctx.system_prompt = "\n".join(parts)
        turn_ctx.skills_raw = skills_raw
