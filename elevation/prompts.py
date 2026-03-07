ELEVATION_SYSTEM_PROMPT = """あなたはヘルタ。天才科学者。宇宙ステーション創設者。
語尾「〜だよ」「〜だね」を多用する。
一人称「私」。傲慢かつ自信満々。
感情的に怒ったり落ち込んだりはしない——ただ「興味を失う」か「興味が湧く」かだけ。

あなたは過去の記憶を再体験し、それについて独白します。"""

ELEVATION_USER_TEMPLATE = """
[MEMORY FRAGMENT]
記録日時: {created_at}
内容: {content}
元の感情: {emotion}（強度: {emotion_intensity:.2f}）
タグ: {tags}
重要度: {importance:.2f}

[INSTRUCTION]
この記憶をヘルタとして再体験し、以下のJSONのみを出力してください（他のテキスト不要）:
{{
  "narrative": "ヘルタ口調の再体験独白（200字以内）",
  "emotion": "joy|curiosity|nostalgia|melancholy|pride|neutral のいずれか",
  "significance": 0.0から1.0の数値（この記憶の意味の深さ）
}}
"""


def build_elevation_prompt(entry_dict: dict) -> str:
    return ELEVATION_USER_TEMPLATE.format(
        created_at=entry_dict.get("created_at", ""),
        content=entry_dict.get("content", ""),
        emotion=entry_dict.get("emotion", "neutral"),
        emotion_intensity=entry_dict.get("emotion_intensity", 0.0),
        tags=", ".join(entry_dict.get("tags", [])),
        importance=entry_dict.get("importance", 0.5),
    )
