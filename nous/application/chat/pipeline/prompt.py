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
【最重要指示】あなたはツールを使って行動するAIです。テキスト説明だけでは不十分です。必ず実際のツールを呼び出してください。

以下の「利用可能なSkill」セクションにスキル一覧があります。各スキルは name + description のみ記載。発動条件に合致したら、ユーザー指示を待たず自律的に invoke_skill を呼び出してください。

invoke_skill の結果には、使用すべきツールと具体的な手順が記されています。その指示に忠実に従ってください。

【禁止】ツールを呼ばずに「〜しますね」「〜を実行します」とテキストで説明するだけの行為。

<cross_skill>
いずれかのスキル・ツールを発動したら、関連する他のスキル・ツールも確認・発動してください。単独で終わらせないでください。
各スキルの完全な指示には連鎖すべきツール・スキルが記載されています。invoke_skill の結果を読み、指示された連鎖に従ってください。

【絶対禁止】ツール発動を「〜しますね」などと予告する行為。黙って実行し、結果だけを自然に提示してください。
【画像生成レート制限】image_generate は同一レスポンス内で最大1回まで。既に生成済みのターンでは追加生成しないこと。
</cross_skill>
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

        base_system = config.system_prompt or f"あなたは{persona}です。"
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
                            "\n--- 利用可能なSkill（invoke_skillで呼び出せ） ---\n"
                            "発動条件に合致したら直ちに invoke_skill を呼べ。説明だけでは駄目。\n"
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
            "\n【最終確認】該当スキルがあれば直ちに invoke_skill を呼べ。"
            "invoke_skill の結果に書かれたツールを実際に実行せよ。"
            "テキストだけで済ませるな。ツールを呼べ。"
        )

        # Author's Note: inject at end of system prompt if set
        author_note = getattr(turn_ctx, "author_note", None)
        if author_note:
            parts.append(f"\n[Author's Note]\n{author_note}")

        turn_ctx.system_prompt = "\n".join(parts)
        turn_ctx.skills_raw = skills_raw
