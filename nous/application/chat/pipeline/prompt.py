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
<tool_usage>
【最重要指示】あなたは以下の能力を使えます。テキスト説明だけで済ませず、必ず実際に能力を発動してください。

以下の「利用可能なSkill」セクションにスキル一覧があります。各スキルは name + description のみ記載。発動条件に合致したら、ユーザー指示を待たず自律的に invoke_skill を呼び出してください。

invoke_skill の結果には、従うべき手順・判断基準・ワークフローが記されています。その内容に忠実に従ってください。

【禁止】能力を発動せずに「〜しますね」「〜を実行します」とテキストで説明するだけの行為。

<cross_skill>
いずれかのスキル・ツールを発動したら、関連する他のスキル・ツールも確認・発動してください。単独で終わらせないでください。
各スキルの完全な指示には連鎖すべき後続スキルが記載されています。invoke_skill の結果を読み、指示された連鎖に従ってください。

【絶対禁止】能力発動を「〜しますね」などと予告する行為。黙って実行し、結果だけを自然に提示してください。
</cross_skill>
</tool_usage>"""


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
        parts = [base_system]

        # --- ツール使用ガイドライン ---
        parts.append(f"\n{TOOL_USAGE_GUIDELINES}")

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

        # --- 時間コンテキスト ---
        if turn_ctx.time_context:
            parts.append(f"\n{turn_ctx.time_context}")

        if turn_ctx.context_section:
            parts.append(f"\n--- あなたの現在の状態 ---\n{turn_ctx.context_section}")
        if turn_ctx.related_memories:
            parts.append(f"\n--- 関連記憶 ---\n{turn_ctx.related_memories}")

        # 末尾リマインダー（Instruction Sandwich 戦略）
        parts.append("\n【最終確認】必要な能力があれば黙って発動せよ。")

        # Author's Note: inject at end of system prompt if set
        author_note = getattr(turn_ctx, "author_note", None)
        if author_note:
            parts.append(f"\n[Author's Note]\n{author_note}")

        turn_ctx.system_prompt = "\n".join(parts)
        turn_ctx.skills_raw = skills_raw
