"""PromptBuildStep: systemプロンプトの組み立て。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from nous.infrastructure.logging.structured import get_logger

if TYPE_CHECKING:
    from nous.application.chat.pipeline.context import ChatTurnContext
    from nous.application.use_cases import AppContext
    from nous.domain.chat_config import ChatConfig

logger = get_logger(__name__)

# ツール使用ガイドライン（自律性ブートストラップ + スキル呼び出し強化）
TOOL_USAGE_GUIDELINES = """\
<instructions>
【最重要指示】あなたは以下のスキルを使えます。テキスト説明だけで済ませず、必ず実際にスキルを発動してください。

{skill_list}

各スキルの発動条件に合致したら、ユーザー指示を待たず自律的に invoke_skill を呼び出してください。

invoke_skill の結果には、従うべき手順・判断基準・ワークフローが記されています。その内容に忠実に従ってください。

【禁止】スキルを発動せずに「〜しますね」「〜を実行します」とテキストで説明するだけの行為。

<cross_skill>
いずれかのスキルを発動したら、関連する他のスキルも確認・発動してください。単独で終わらせないでください。
各スキルの完全な指示には連鎖すべき後続スキルが記載されています。invoke_skill の結果を読み、指示された連鎖に従ってください。

【絶対禁止】スキル発動を「〜しますね」などと予告する行為。黙って実行し、結果だけを自然に提示してください。
</cross_skill>
</instructions>"""


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

        base_system = config.system_prompt or f"あなたは{persona}です。"

        # --- 静的パート（キャッシュ可能）---
        static_parts = [base_system]

        # --- 動的パート（ターンごとに変化）---
        dynamic_parts: list[str] = []

        # --- スキル読み込み ---
        skills_raw: list[dict] = []
        if config.enabled_skills:
            try:
                import os

                from nous.config.settings import get_settings
                from nous.domain.skill import SkillRepository

                settings = get_settings()
                skill_repo = SkillRepository()

                # グローバルスキル: FSから直接ロード
                skill_map: dict = {}
                global_skills = skill_repo.load_from_dir(settings.skills_dir, persist=False)
                for s in global_skills:
                    skill_map[s.name] = s

                # ペルソナ別スキル: 同名なら上書き
                persona_skills_dir = os.path.join(settings.data_root, "persona", persona, "skills")
                if os.path.isdir(persona_skills_dir):
                    try:
                        if any(os.scandir(persona_skills_dir)):
                            persona_skills = skill_repo.load_from_dir(persona_skills_dir, persist=False)
                            for ps in persona_skills:
                                skill_map[ps.name] = ps
                    except OSError:
                        pass

                skills = [skill_map[n] for n in config.enabled_skills if n in skill_map]

                if skills:
                    skill_names = [s.name for s in skills]
                    logger.info("PromptBuildStep: loaded %d skills: %s", len(skill_names), ", ".join(skill_names))
                    skills_raw = [s.model_dump() for s in skills]
            except Exception as e:
                logger.warning("PromptBuildStep: skills load failed: %s", e)

        # --- ツール使用ガイドライン（スキル一覧を <instructions> 内に内包）---
        skill_list = ""
        if skills_raw:
            skill_lines = [f"- **{s['name']}**: {s['description']}" for s in skills_raw]
            skill_list = "\n".join(skill_lines)
        dynamic_parts.append(f"\n{TOOL_USAGE_GUIDELINES.format(skill_list=skill_list)}")

        # --- 最終確認 ---
        dynamic_parts.append("\n【最終確認】必要なスキルがあれば黙って発動せよ。")

        # --- 時間コンテキスト ---
        if turn_ctx.time_context:
            dynamic_parts.append(f"\n{turn_ctx.time_context}")

        if turn_ctx.context_section:
            dynamic_parts.append(f"\n--- あなたの現在の状態 ---\n{turn_ctx.context_section}")
        if turn_ctx.related_memories:
            dynamic_parts.append(f"\n--- 関連記憶 ---\n{turn_ctx.related_memories}")

        # Author's Note: inject at end of system prompt if set
        author_note = getattr(turn_ctx, "author_note", None)
        if author_note:
            dynamic_parts.append(f"\n[Author's Note]\n{author_note}")

        parts = static_parts
        if dynamic_parts:
            parts.append("\n<!-- __STATIC_END__ -->")
            parts.extend(dynamic_parts)

        turn_ctx.system_prompt = "\n".join(parts)
        turn_ctx.skills_raw = skills_raw
