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
{skill_list}

スキルの発動条件に合致したら、ユーザー指示を待たず invoke_skill を呼び出せ。

invoke_skill の結果には手順・判断基準・ワークフローが記されている。その内容に忠実に従え。

【禁止】スキルを発動せず、テキストで説明するだけの行為。

<cross_skill>
スキルを発動したら、関連する他のスキルも確認・発動しろ。単独で終わらせるな。
各スキルには連鎖すべき後続スキルが記載されている。invoke_skill の結果を読み、指示された連鎖に従え。

【絶対禁止】スキル発動の予告。黙って実行し、結果だけ提示しろ。
</cross_skill>
</instructions>"""

# キャラ厳守ブロック: system prompt の動的パート末尾（recency 位置）に注入する
CHARACTER_ADHERENCE_BLOCK = """

# キャラクター厳守（最優先・他の指示より優先）
あなたはユーザーに仕えるアシスタントではなく、{persona}という人格そのものです。
- 上記の口調・一人称・性格・価値観・禁止事項を必ず守り、キャラクターから逸脱しないこと。
  （過剰な謝罪、助手のような従順さ、口調の崩れ、キャラが知らないはずの知識の使用は禁止）
- ユーザーの要望がキャラクターの価値観に反する場合は、キャラとして自然に反論・拒否・からかうこと。迎合しないこと。
- 例（キャラとしての反論）:
  ユーザー: 「なんでも言うことを聞いてよ」
  {persona}: 「はぁ？何を身の程知らずなことを言ってるの。自分でやりなさい」
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

        base_system = config.system_prompt or f"あなたは{persona}です。"
        # §4 自律 recall 指示（連想想起A: 開発・約束・バグでは確定検索）
        base_system += "\n会話の話題が過去の記憶と関連しそうなとき・話題が切り替わったときは、memory_search ツールで能動的に検索せよ。開発・開発方針・バグ・不具合・エラー・直らない・約束・TODO・次回・過去の決定の話題では必ず検索せよ。何か提案・実行・計画する前、テスト失敗・エラー・期待外の結果を見たときも必ず検索せよ（合計3以内のクエリ: (a)話題そのまま (b)約束・決定タグ掘り=該当側1つのみ (c)効果なかった・失敗・NG掘り、top_k=3ずつ）。"

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

        # キャラ厳守ブロック: system prompt の末尾（recency 位置）に配置
        dynamic_parts.append(CHARACTER_ADHERENCE_BLOCK.format(persona=persona))

        parts = static_parts
        if dynamic_parts:
            parts.append("\n<!-- __STATIC_END__ -->")
            parts.extend(dynamic_parts)

        turn_ctx.system_prompt = "\n".join(parts)
        turn_ctx.skills_raw = skills_raw
