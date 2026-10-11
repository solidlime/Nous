"""Jev 型判定ゲート: query と候補群を 1 回の LLM 呼び出しで一起判定する。

Avi Chawla 'Jev + RAG' 方式の踏襲のみ: query を shared state に置き、候補を
個別に採/除し、閾値でフィルタする。logprobs は使わず、JSON の probability を
テキストで受け取る（``OpenAICompatProvider`` の stream 拡張はしない）。

``MemoryEnricher`` と同一作法（``collect_text_with_usage`` → ``strip_code_fence``
→ ``json.loads``）。全判定は best-effort: 失敗・パース不能・空は ``None`` を返し、
呼び出し側（gate）は全候補採用で続行する（never blocks the caller 契約踏襲）。
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any

from nous.domain.search.judge import DecisionJudge, JudgeVerdict
from nous.domain.shared.text_utils import strip_code_fence
from nous.infrastructure.llm.factory import get_provider
from nous.infrastructure.llm.text_utils import collect_text_with_usage

if TYPE_CHECKING:
    from nous.infrastructure.llm.base import LLMProvider

logger = logging.getLogger(__name__)

# 候補 content の抜粋上限（プロンプトを bounded に保つ）。
_CONTENT_EXCERPT_CHARS = 200

_SYSTEM_PROMPT = """あなたは記憶検索の判定器です。検索クエリと候補記憶の一覧を受け取り、
各候補が「クエリに答えるために採るべきか」を 0.0〜1.0 の確率で個別に判定してください。

判定基準:
- 1.0 に近い: 候補がクエリの答え・必要な文脈に直接寄与する
- 0.0 に近い: 候補が無関係、またはクエリの主題から外れている

さらに sufficiency（候補群全体がクエリに答えるのに足りるか）を 0.0〜1.0 で返してください。

出力は必ず次の JSON のみ:
{"decisions": [{"index": 0, "probability": 0.8}, {"index": 1, "probability": 0.2}], "sufficiency": 0.6}
decisions には入力候補の全 index を含めてください。"""


class LLMDecisionJudge:
    """1 回の LLM 呼び出しで query に対する候補群を個別判定する（契約は DecisionJudge）。"""

    def __init__(
        self,
        provider_name: str,
        api_key: str,
        model: str,
        base_url: str = "",
        session_id: str | None = None,
        temperature: float = 0.3,
        max_tokens: int = 512,
    ) -> None:
        self._provider_name = provider_name
        self._api_key = api_key
        self._model = model
        self._base_url = base_url
        self._session_id = session_id
        # enricher に合わせる（既定 temperature 0.3 / max_tokens 512）。
        self._temperature = temperature
        self._max_tokens = max_tokens

    async def judge(
        self,
        query_text: str,
        candidates: list[dict[str, Any]],
        model: str | None = None,
    ) -> JudgeVerdict | None:
        """query と候補群を一起判定する。失敗時は None（呼び出し側は全採用）。"""
        if not query_text.strip() or not candidates:
            return None
        try:
            from nous.infrastructure.llm.base import LLMMessage

            provider = self._provider(model)
            # 候補数に比例させる: 1候補 ≈ 8〜12 トークンだが余裕を見て 24、上限 8192。
            # 512 固定だと 50 件超で JSON が切れ、パース不能 → fail-open でゲートが黙って無効化される。
            max_tokens = min(max(self._max_tokens, len(candidates) * 24 + 128), 8192)
            collected = await collect_text_with_usage(
                provider,
                messages=[LLMMessage(role="user", content=self._build_user_message(query_text, candidates))],
                system=_SYSTEM_PROMPT,
                temperature=self._temperature,
                max_tokens=max_tokens,
            )
            if not collected.text:
                return None
            return self._parse(collected.text, candidates)
        except Exception:
            logger.warning("decision judge failed", exc_info=True)
            return None

    def _provider(self, model: str | None = None) -> LLMProvider:
        return get_provider(
            provider=self._provider_name,
            api_key=self._api_key,
            model=model or self._model,
            base_url=self._base_url,
            session_id=self._session_id,
        )

    @staticmethod
    def _build_user_message(query_text: str, candidates: list[dict[str, Any]]) -> str:
        lines = [f"Query: {query_text.strip()}", "", "Candidates:"]
        for i, cand in enumerate(candidates):
            content = str(cand.get("content") or "").strip().replace("\n", " ")
            if len(content) > _CONTENT_EXCERPT_CHARS:
                content = content[:_CONTENT_EXCERPT_CHARS]
            lines.append(f"[{i}] {content}")
        return "\n".join(lines)

    @staticmethod
    def _parse(text: str, candidates: list[dict[str, Any]]) -> JudgeVerdict | None:
        cleaned = strip_code_fence(text)
        try:
            data = json.loads(cleaned)
        except (json.JSONDecodeError, ValueError):
            logger.warning("Failed to parse decision judge JSON: %s", text[:200])
            return None
        if not isinstance(data, dict):
            return None

        verdicts: dict[str, float] = {}
        raw = data.get("decisions")
        if isinstance(raw, list):
            for item in raw:
                if not isinstance(item, dict):
                    continue
                index = item.get("index")
                if isinstance(index, bool) or not isinstance(index, int):
                    continue
                if index < 0 or index >= len(candidates):
                    continue
                prob = item.get("probability")
                if isinstance(prob, bool) or not isinstance(prob, (int, float)):
                    continue
                key = candidates[index].get("key")
                if not isinstance(key, str):
                    continue
                verdicts[key] = max(0.0, min(1.0, float(prob)))

        # 有効な判定が 1 件も取れなければ None（呼び出し側は全採用フォールバック）。
        if not verdicts:
            return None

        suff = data.get("sufficiency", 1.0)
        if isinstance(suff, bool) or not isinstance(suff, (int, float)):
            suff = 1.0
        return JudgeVerdict(verdicts=verdicts, sufficiency=max(0.0, min(1.0, float(suff))))


def resolve_decision_judge(repo: object) -> DecisionJudge | None:
    """per-persona ChatConfig から provider を解決して judge を作る。

    ``resolve_brain_config``（query_service）と同じ ``repo._conn`` 経路で config.json を
    解決する。解決不能（repo/_conn 無し・config 無し・api_key 空）は None を返し、
    engine 側の gate は完全 no-op になる（fail-open）。provider/model は既定
    （``provider_config`` の effective 値）、``decision_model`` は呼び出し毎に上書き。
    """
    try:
        from nous.domain.chat_config import resolve_persona_chat_config

        cfg = resolve_persona_chat_config(repo)
        if cfg is None:
            return None
        conn = getattr(repo, "_conn", None)
        if conn is None:
            return None
        p = cfg.provider_config
        api_key = p.get_effective_api_key()
        if not api_key:
            logger.warning("decision judge unavailable (no_api_key): gate is a no-op")
            try:
                from nous.domain.memory import wiring_events

                wiring_events.emit("decision_bypass", meta={"persona": conn.persona, "reason": "no_api_key"})
            except Exception:
                logger.debug("decision bypass emit failed", exc_info=True)
            return None
        return LLMDecisionJudge(
            provider_name=p.provider,
            api_key=api_key,
            model=p.get_effective_model(),
            base_url=p.get_effective_base_url(),
            session_id=f"nous-judge-{conn.persona}",
        )
    except Exception:
        logger.debug("decision judge resolver failed", exc_info=True)
        return None
