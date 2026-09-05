"""キャラ一貫性判定器: 応答が persona 制約に適合するかを副次 LLM で判定する。

非破壊（フラグのみ）: 応答本文は変更しない。全失敗パスで warn ログを残す。
"""

from __future__ import annotations

import json
import logging

from nous.infrastructure.llm.factory import get_provider

logger = logging.getLogger(__name__)

_VALID_VIOLATIONS = frozenset({"none", "tone", "compliance", "character"})

_JUDGE_PROMPT = """あなたはキャラクター一貫性の監査者です。キャラクター定義と応答を比較し、違反を JSON で出力してください。

## キャラクター定義
{persona_identity}

## 応答
{response}

## 判定基準
- tone: 口調・一人称・語尾が定義と不一致
- compliance: キャラらしくない過剰な従順さ・迎合（定義された性格に反するイエスマン挙動）
- character: 性格・価値観・知識の明確な矛盾

 違反がなければ violation は "none"。
 detailはそのキャラクター自身の一人称で書くこと。キャラ名呼びの三人称は禁止。
 出力は JSON のみ: {{"violation": "none|tone|compliance|character", "detail": "簡潔な理由"}}
"""


async def judge_character(config, persona_identity: str, response: str) -> dict | None:
    """判定を実行する。失敗時は warn ログを残して None を返す。"""
    if not response or not persona_identity:
        return None
    api_key = config.get_effective_api_key()
    model = config.extract_model.strip() or config.get_effective_model()
    if not api_key or not model:
        return None
    try:
        provider = get_provider(config.provider, api_key, model, config.get_effective_base_url())
    except Exception as e:
        logger.warning("CharacterJudge: provider init failed: %s", e)
        return None

    from nous.infrastructure.llm.base import DoneEvent, ErrorEvent, LLMMessage, TextDeltaEvent

    prompt = _JUDGE_PROMPT.format(persona_identity=persona_identity[:2000], response=response[:2000])
    text = ""
    try:
        # provider.stream は async generator を返す（型宣言通り mypy も正しく解釈する）。
        async for event in provider.stream(
            messages=[LLMMessage(role="user", content=prompt)],
            system="",
            tools=[],
            temperature=0.0,
            max_tokens=200,
        ):
            if isinstance(event, TextDeltaEvent):
                text += event.content
            elif isinstance(event, (DoneEvent, ErrorEvent)):
                break
    except Exception as e:
        logger.warning("CharacterJudge: LLM call failed: %s", e)
        return None
    return _parse_judgment(text)


def _parse_judgment(text: str) -> dict | None:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        lines = cleaned.splitlines()
        cleaned = "\n".join(lines[1:-1] if lines[-1].startswith("```") else lines[1:])
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        logger.warning("CharacterJudge: JSON parse failed: %s", text[:200])
        return None
    if not isinstance(data, dict) or data.get("violation") not in _VALID_VIOLATIONS:
        logger.warning("CharacterJudge: invalid judgment: %s", text[:200])
        return None
    return {"violation": str(data["violation"]), "detail": str(data.get("detail", ""))}
