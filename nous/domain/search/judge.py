"""Jev 型判定ゲートが使う一起判定契約。

ここで定義する契約は「複数候補を確率で一括判定する」judge のみを表す。
単一ラベル判定（contradiction / character_judge）や抽出系（memory_extractor /
memory_enricher）は戻り値形状が異なるため、この契約には乗らない。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


@dataclass(frozen=True)
class JudgeVerdict:
    """一起判定の結果。

    verdicts: 候補 key -> 0-1 の確率。
    sufficiency: 候補全体が問いに十分答えたかの自己申告（0-1）。
    """

    verdicts: dict[str, float] = field(default_factory=dict)
    sufficiency: float = 0.0

    def probability(self, key: str) -> float:
        """key の確率を返す。欠落 key は 1.0（fail-open: 採用側に倒す）。"""
        return self.verdicts.get(key, 1.0)


@runtime_checkable
class DecisionJudge(Protocol):
    """Jev 型判定ゲートが使う一起判定器の最小契約（LLMDecisionJudge と構造互換）。

    契約:
    - never-raise: 実装は例外を投げず、失敗時は None を返す。
    - None は fail-open を意味し、呼び出し側（decision gate）は全候補を採用する。
    - candidates は {"key": str, "content": str} の dict 列。
    - model は呼び出しごとの上書き（None なら実装の既定）。
    """

    async def judge(
        self,
        query_text: str,
        candidates: list[dict[str, Any]],
        model: str | None = None,
    ) -> JudgeVerdict | None: ...
