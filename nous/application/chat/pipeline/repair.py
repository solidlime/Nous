"""RepairStep: 毎ターンキャラ判定 + 違反時の応答再生成（置換）。

設計意図 (2026-07-26 validation gap 対策):
- InferenceStep 完了後・assistant 保存前に judge_character で毎ターン判定する。
- 違反 (tone/compliance/character) 検出時のみ、修復プロンプトで再生成し
  turn_ctx.full_response を差し替える（edit_message 不使用・保存前置換）。
- 判定器は既存の character_judge.judge_character を再利用（署名・プロンプト不変）。
- 失敗（例外/空テキスト/判定不能）時は warn ログを残し元応答のまま配信を継続する。
  チャット配信を死なせないため例外は全面的に握り潰す（PostProcessStep と同様）。
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from nous.application.chat.character_judge import judge_character
from nous.application.chat.events import ResponseReplacedSSE
from nous.infrastructure.llm.base import LLMMessage
from nous.infrastructure.llm.factory import get_provider
from nous.infrastructure.llm.text_utils import collect_text
from nous.infrastructure.logging.structured import get_logger

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from nous.application.chat.pipeline.context import ChatTurnContext
    from nous.application.use_cases import AppContext
    from nous.domain.chat_config import ChatConfig

logger = get_logger(__name__)

_REPAIR_INSTRUCTION = """直前の応答にキャラクター一貫性の違反が検出されました。以下の情報を踏まえて書き直してください。

## 判定結果
- 違反種別: {violation}
- 詳細: {detail}

## 直前の応答
{response}

## 使用済みツールの結果
{tool_results}

## 修復規範
元の応答を、キャラの口調・一人称・価値観に完全に沿うよう書き直せ。判定で指摘された違反を必ず解消せよ。セッション内の事実・ユーザーの指示を最優先し、注入された記憶・状態と矛盾させない。ツールを新たに呼び出す必要がある内容は書かず、既に得られた情報だけで答えよ。応答本文のみを出力せよ。"""


def _tool_results_text(tool_calls_log: list[dict] | None) -> str:
    """tool_calls_log から「ツール名: 結果本文」のリストを合成する（無ければ省略）。"""
    lines: list[str] = []
    for entry in tool_calls_log or []:
        if not isinstance(entry, dict):
            continue
        name = str(entry.get("name") or "unknown")
        result = entry.get("result", entry.get("result_raw"))
        if isinstance(result, str):
            text = result
        elif result is not None:
            try:
                text = json.dumps(result, ensure_ascii=False)
            except Exception:
                text = str(result)
        else:
            text = ""
        if text.strip():
            lines.append(f"- {name}: {text[:2000]}")
    return "\n".join(lines) if lines else "（なし）"


def _build_repair_messages(
    session_messages: list[LLMMessage], instruction: str
) -> list[LLMMessage]:
    """元の会話を壊さないようコピーし、末尾に修復指示の user メッセージを追加する。"""
    return [*session_messages, LLMMessage(role="user", content=instruction)]


async def _regenerate(
    config: ChatConfig,
    turn_ctx: ChatTurnContext,
    session_messages: list[LLMMessage],
    violation: str,
    detail: str,
) -> str | None:
    """judge_character と同じ collect_text パターンで provider 直呼びし、修復候補を生成する。"""
    instruction = _REPAIR_INSTRUCTION.format(
        violation=violation or "none",
        detail=detail or "",
        response=turn_ctx.full_response,
        tool_results=_tool_results_text(turn_ctx.tool_calls_log),
    )
    provider = get_provider(
        config.provider, config.get_effective_api_key(), config.get_effective_model(), config.get_effective_base_url()
    )
    return await collect_text(
        provider,
        messages=_build_repair_messages(session_messages, instruction),
        system=turn_ctx.system_prompt,
        tools=[],
        temperature=config.temperature,
        max_tokens=config.max_tokens,
    )


class RepairStep:
    """毎ターンキャラ判定 → 違反時は再生成して turn_ctx.full_response を置換する。

    service.py の chat() で InferenceStep 直後・assistant 保存前に配線される。
    置換が起きた場合のみ ResponseReplacedSSE を1回 yield する。
    """

    async def run(
        self,
        ctx: AppContext,  # noqa: ARG002 — PostProcessStep と同型のシグネチャ維持
        config: ChatConfig,
        session_messages: list[LLMMessage],
        turn_ctx: ChatTurnContext,
        registry: object | None = None,  # noqa: ARG002 — 修復ではツールを呼ばない
    ) -> AsyncIterator[ResponseReplacedSSE]:
        # ガード: 判定無効 / 空応答 / 修復無効 は何もせず即 return
        if (
            not config.character_judge_enabled
            or not turn_ctx.full_response
            or config.character_repair_max_attempts < 1
        ):
            return

        # 修復ループ内で判定結果を受け渡すための一時属性（dataclass に無いので動的に保持）
        try:
            judgment = await judge_character(config, turn_ctx.system_prompt, turn_ctx.full_response)
            if judgment is None or judgment.get("violation") == "none":
                return

            last_violation = str(judgment.get("violation", "none"))
            last_detail = str(judgment.get("detail", ""))
            replaced = False

            for _ in range(config.character_repair_max_attempts):
                try:
                    candidate = await _regenerate(config, turn_ctx, session_messages, last_violation, last_detail)
                except Exception as e:
                    logger.warning("RepairStep: regeneration failed, keeping original response: %s", e)
                    return
                if not candidate or not candidate.strip():
                    logger.warning("RepairStep: regeneration returned empty text, keeping original response")
                    return

                turn_ctx.full_response = candidate
                replaced = True

                next_judgment = await judge_character(config, turn_ctx.system_prompt, turn_ctx.full_response)
                if next_judgment is None:
                    # 判定不能: 現時点の候補を採用して停止（判定ログは残す）
                    logger.warning("RepairStep: re-judge returned None, adopting current candidate")
                    break
                last_violation = str(next_judgment.get("violation", "none"))
                last_detail = str(next_judgment.get("detail", ""))
                if last_violation == "none":
                    break

            if replaced:
                yield ResponseReplacedSSE(content=turn_ctx.full_response, violation=last_violation, detail=last_detail)
        except Exception:
            logger.exception("RepairStep: unexpected error, keeping original response")
            return
