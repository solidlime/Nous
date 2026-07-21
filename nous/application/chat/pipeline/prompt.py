"""PromptBuildStep: systemプロンプトの組み立て。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from nous.domain.language import LanguageResolver
from nous.infrastructure.logging.structured import get_logger

if TYPE_CHECKING:
    from nous.application.chat.pipeline.context import ChatTurnContext
    from nous.application.use_cases import AppContext
    from nous.domain.chat_config import ChatConfig

logger = get_logger(__name__)

# ツール使用ガイドライン（自律性ブートストラップ + スキル呼び出し強化）
TOOL_USAGE_GUIDELINES = """\
<tool_usage>
以下の「利用可能なSkill」セクションに、呼び出し可能なスキルの一覧があります。
各スキルは name + description のみが記載されており、完全な指示を得るには invoke_skill('<名前>') を呼び出す必要があります。

【重要】スキルの発動条件に合致した場合、ユーザーの指示を待たずに自律的に invoke_skill を呼び出してください。
これは必須の動作です——スキル名と説明だけではタスク実行に不十分なため、必ず invoke_skill で完全な指示を取得すること。
</tool_usage>"""


class PromptBuildStep:
    """systemプロンプトを組み立てる。"""

    def __init__(self) -> None:
        self._skill_cache: tuple[str, list[dict]] | None = None
        self._skill_cache_hash: int | None = None

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

        # 言語指示を注入（ADR-001）
        resolver = LanguageResolver(config)
        lang = resolver.resolve(user_message=turn_ctx.user_message)
        lang_directive = f"[System Directive] Always respond in {lang}. All output must be in {lang}."
        parts.insert(1, lang_directive)

        # --- ツール使用ガイドライン ---
        parts.append(f"\n{TOOL_USAGE_GUIDELINES}")

        # --- スキル読み込み & 注入（即座に隣接） ---
        skills_raw: list[dict] = []
        if config.enabled_skills:
            current_hash = hash(tuple(sorted(config.enabled_skills)))
            if current_hash == self._skill_cache_hash and self._skill_cache is not None:
                cached_header, cached_skills_raw = self._skill_cache
                parts.append(cached_header)
                skills_raw = cached_skills_raw
            else:
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
                        logger.info("PromptBuildStep: injecting %d skills: %s", len(skill_names), ", ".join(skill_names))
                        skill_lines = [f"- {s.name}: {s.description or ''}" for s in skills]
                        header = (
                            "\n--- 利用可能なSkill ---\n"
                            "以下のスキルは、会話の流れに応じてあなた自身の判断で invoke_skill('<名前>') してください。\n"
                            "ユーザーの指示を待たず、発動条件に合致したら即座に呼び出してください。\n"
                            + "\n".join(skill_lines)
                        )
                        parts.append(header)
                        skills_raw = [s.model_dump() for s in skills]
                        self._skill_cache = (header, skills_raw)
                        self._skill_cache_hash = current_hash
                except Exception as e:
                    logger.warning("PromptBuildStep: skills load failed: %s", e)

        # --- 時間コンテキスト ---
        if turn_ctx.time_context:
            parts.append(f"\n{turn_ctx.time_context}")

        if turn_ctx.context_section:
            parts.append(f"\n--- ペルソナ状態・コンテキスト ---\n{turn_ctx.context_section}")
        if turn_ctx.related_memories:
            parts.append(f"\n--- 関連記憶 ---\n{turn_ctx.related_memories}")

        # 末尾リマインダー（Instruction Sandwich 戦略）
        parts.append(
            "\n【最終確認】上記の「利用可能なSkill」に発動条件に合致するスキルがある場合は、"
            "invoke_skill('<名前>') を呼び出して完全な指示を取得してください。"
        )

        # Author's Note: inject at end of system prompt if set
        author_note = getattr(turn_ctx, "author_note", None)
        if author_note:
            parts.append(f"\n[Author's Note]\n{author_note}")

        turn_ctx.system_prompt = "\n".join(parts)
        turn_ctx.skills_raw = skills_raw
