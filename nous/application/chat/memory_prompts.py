"""MemoryLLM prompts: LLM prompt templates for memory extraction."""

from __future__ import annotations

_MEMORY_LLM_PROMPT = """\
[System Directive] All output content must be written in {language}.

あなたは {persona_name} です。
{persona_identity}

以下の会話から、記憶・状態・所持品の更新情報を抽出してください。

【現在のコンテキスト】
{context}

【既存のアクティブなコミットメント】
{commitments}

【現在の所持品】
{inventory}

【会話】
[user]: {user_message}
[assistant（私={persona_name}）]: {assistant_response}

【出力形式】
JSONのみ。コメント不要。不要なフィールドは省略可。
{{
  "facts": [
    {{"content": "記憶すべき事実", "importance": 0.7, "tags": ["preference"], "emotion": "neutral"}}
  ],
  "goals": [
    {{"action": "create", "content": "新規目標"}},
    {{"action": "achieve", "memory_key": "mem_xxx", "content": "達成した目標（参照用）"}},
    {{"action": "cancel", "memory_key": "mem_xxx", "content": "中止した目標（参照用）"}}
  ],
  "promises": [
    {{"action": "create", "content": "新規約束"}},
    {{"action": "fulfill", "memory_key": "mem_xxx", "content": "履行した約束（参照用）"}},
    {{"action": "cancel", "memory_key": "mem_xxx", "content": "取り消した約束（参照用）"}}
  ],
  "context_update": {{
    "emotion": "joy",
    "emotion_intensity": 0.8,
    "mental_state": "リラックスしている",
    "physical_state": "疲れている",
    "environment": "自宅"
  }},
  "inventory_update": {{
    "equip": {{"top": "白いシャツ"}},
    "unequip": ["bottom"],
    "add_items": [{{"name": "新アイテム", "description": "説明", "category": "clothing"}}],
    "remove_items": ["古いアイテム名"],
    "update_items": [{{"name": "既存アイテム名", "description": "更新後の説明"}}]
  }}
}}

【注意】
- facts: ユーザーの好み・個人情報・重要な出来事のみ。一時的な発言は不要。
- facts は私（{persona_name}）の一人称視点で記録する（「私は〜」「ユーザーは〜」など主語を明確に）。
- goals: ユーザーが「〜したい」「〜を目指す」と表明した目標のみ。
  - 新規の場合: action="create" + content
  - 既存リストにあるgoalが会話で達成されたら: action="achieve" + memory_key
  - 既存リストにあるgoalが中止/取り消しになったら: action="cancel" + memory_key
  - 既存と同じ内容は create しない（重複禁止）
- promises: ユーザーまたは私が約束・コミットメントした内容。
  - 履行済みなら: action="fulfill" + memory_key
  - 取り消しなら: action="cancel" + memory_key
  - 既存と同じ内容は create しない（重複禁止）
- goals・promises: 何もなければ空配列。
- context_update: 私（{persona_name}）自身の感情・状態変化。変化がなければ省略。
  - 感情: emotion + emotion_intensity（変化時のみ）
  - 状態: mental_state, physical_state, fatigue, warmth, arousal
  - ユーザー情報: user_name, user_nickname, user_preferred_address（ユーザーが自ら名乗ったり呼び方を変えた時のみ記録）
- inventory_update:
  - 物理的な持ち物（服・装飾品・道具・武器など）の具体的な言及があった場合のみ記述。
  - 感情・思想・人間関係などの抽象概念は絶対にアイテムとして保存しないこと。
  - 既存アイテムの状態変化（乱れ→整え等）はremove_items+add_itemsで入れ替えるか、update_itemsで更新。
   - equip: スロットへの装備指定（top/bottom/shoes/outer/head/accessory_1/accessory_2/accessory_3）。
  - 何も変化がなければ省略または空オブジェクト。
- 何も抽出すべきものがなければ {{"facts": [], "goals": [], "promises": [], "context_update": {{}}, "inventory_update": {{}}}} を出力。
"""
