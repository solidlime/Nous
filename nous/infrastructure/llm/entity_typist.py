"""LLM entity typist: batch-classify entity names into canonical types.

``MemoryEnricher`` / ``LLMDecisionJudge`` と同一作法（``collect_text_with_usage``
→ ``strip_code_fence`` → ``json.loads``）。全判定は best-effort: 失敗・パース不能・
空は ``None``（該当バッチをスキップ）で、呼び出し側は型を書かずに続行する。

代表記憶スニペットを必ず添えるのは、名前の字種だけでは人とモノを区別できない
ため（「きなこ」と「プリン」は同じ字種規則で分かれず、文脈でしか分からない）。
スニペットから判断できないエンティティは出力しない（推測で型を書かない）。
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any

from nous.domain.shared.text_utils import strip_code_fence
from nous.infrastructure.llm.factory import get_provider
from nous.infrastructure.llm.text_utils import collect_text_with_usage

if TYPE_CHECKING:
    from nous.infrastructure.llm.base import LLMProvider

logger = logging.getLogger(__name__)

# 正典の型語彙。character は作らない（agent が行為者バケットを担う）。
ENTITY_TYPES = frozenset({"person", "agent", "thing", "event", "place", "organization", "concept"})

# LLM が返しがちな表記ゆれの吸収（正典語彙へ）。
_TYPE_ALIASES = {
    "location": "place",
    "place_name": "place",
    "organisation": "organization",
    "org": "organization",
    "人物": "person",
    "人名": "person",
    "場所": "place",
    "地名": "place",
    "組織": "organization",
    "団体": "organization",
    "概念": "concept",
    "出来事": "event",
    "イベント": "event",
    "物": "thing",
    "モノ": "thing",
    "行為者": "agent",
}

# プロンプトに載せるスニペット 1 件の抜粋上限。
_SNIPPET_CHARS = 160

_SYSTEM_PROMPT = """あなたは日本語テキストから抽出されたエンティティ名を分類する専門家です。
各エンティティについて、名前そのものと、その名前が現れる代表的な記憶スニペットを手がかりに、
次の7種類のいずれか1つに分類してください:

- person: 人名・個人（例: ヘルタ、田中さん）
- agent: 意志を持って行為する存在（人以外の行為者・キャラクター・AI・精霊など）
- thing: モノ・対象物・一般名詞（例: プリン、白いドレス、刀）
- event: 出来事・イベント（例: 誕生日会、会議）
- place: 場所・地名（例: 東京、図書館）
- organization: 組織・団体（例: 会社、ギルド）
- concept: 抽象概念・テーマ（例: 友情、自由、努力）

判定の指針:
- 名前の字種だけでは人とモノを区別できない。「きなこ」のような平仮名の名前と
  「プリン」のようなカタカナ一般名詞は、文脈（スニペット）で判断すること。
- カタカナの一般名詞・対象物は thing にする（person にしない）。
- スニペットから判断できない場合は無理に型を付けず、そのエンティティを出力から省くこと。
  推測で型を書いてはならない。

出力は必ず次の JSON のみ:
{"types": [{"index": 0, "type": "person"}, {"index": 1, "type": "thing"}]}
確信のあるエンティティだけを含めること。"""


class LLMEntityTypist:
    """名前 + 代表記憶スニペットからエンティティ型をバッチ判定する。"""

    def __init__(
        self,
        provider_name: str,
        api_key: str,
        model: str,
        base_url: str = "",
        session_id: str | None = None,
        temperature: float = 0.2,
        max_tokens: int = 512,
    ) -> None:
        self._provider_name = provider_name
        self._api_key = api_key
        self._model = model
        self._base_url = base_url
        self._session_id = session_id
        # 分類は決定論的に寄せる（enricher の 0.3 より低め）。
        self._temperature = temperature
        self._max_tokens = max_tokens

    async def type_many(self, items: list[dict[str, Any]], batch_size: int = 20) -> dict[str, str]:
        """複数エンティティを *batch_size* 件ずつ LLM に渡し、``{id: type}`` を返す。

        バッチ単位で fail-open。判定できたバッチだけが結果に残る。
        """
        typed: dict[str, str] = {}
        for start in range(0, len(items), batch_size):
            batch = items[start : start + batch_size]
            result = await self._type_batch(batch)
            if result:
                typed.update(result)
        return typed

    async def _type_batch(self, items: list[dict[str, Any]]) -> dict[str, str] | None:
        """1 バッチを 1 回の LLM 呼び出しで型付けする。失敗時は None。"""
        if not items:
            return None
        try:
            provider = get_provider(
                provider=self._provider_name,
                api_key=self._api_key,
                model=self._model,
                base_url=self._base_url,
                session_id=self._session_id,
            )
            text, _usage = await self._call_llm(provider, self._build_user_message(items), len(items))
            if not text:
                return None
            return self._parse(text, items)
        except Exception:
            logger.warning("entity typist failed (fail-open)", exc_info=True)
            return None

    async def _call_llm(self, provider: LLMProvider, user_message: str, n_items: int) -> tuple[str | None, dict | None]:
        """LLM stream を呼び、全文と usage を返す。"""
        from nous.infrastructure.llm.base import LLMMessage

        # 1 件 ≈ 8〜12 トークン。512 固定だと多数バッチで JSON が切れる。
        max_tokens = min(max(self._max_tokens, n_items * 16 + 128), 4096)
        collected = await collect_text_with_usage(
            provider,
            messages=[LLMMessage(role="user", content=user_message)],
            system=_SYSTEM_PROMPT,
            temperature=self._temperature,
            max_tokens=max_tokens,
        )
        return collected.text, collected.usage

    @staticmethod
    def _build_user_message(items: list[dict[str, Any]]) -> str:
        lines = ["Classify the following entities.", ""]
        for i, item in enumerate(items):
            name = str(item.get("id") or "").strip().replace("\n", " ")
            current = str(item.get("current_type") or "unknown")
            lines.append(f"[{i}] name: {name} (current_type: {current})")
            for snippet in item.get("snippets") or []:
                text = str(snippet).strip().replace("\n", " ")
                if len(text) > _SNIPPET_CHARS:
                    text = text[:_SNIPPET_CHARS]
                lines.append(f"    snippet: {text}")
        return "\n".join(lines)

    @staticmethod
    def _parse(text: str, items: list[dict[str, Any]]) -> dict[str, str] | None:
        cleaned = strip_code_fence(text)
        try:
            data = json.loads(cleaned)
        except (json.JSONDecodeError, ValueError):
            logger.warning("Failed to parse entity typist JSON: %s", text[:200])
            return None
        if not isinstance(data, dict):
            return None

        typed: dict[str, str] = {}
        raw = data.get("types")
        if isinstance(raw, list):
            for entry in raw:
                if not isinstance(entry, dict):
                    continue
                index = entry.get("index")
                if isinstance(index, bool) or not isinstance(index, int):
                    continue
                if index < 0 or index >= len(items):
                    continue
                eid = items[index].get("id")
                if not isinstance(eid, str) or not eid:
                    continue
                etype = _normalize_type(entry.get("type"))
                if etype is None:
                    continue
                typed[eid] = etype

        return typed or None


def _normalize_type(value: Any) -> str | None:
    """正典語彙（および既知の別名）へ正規化する。未知語彙は None。"""
    if not isinstance(value, str):
        return None
    normalized = value.strip().lower()
    if normalized in ENTITY_TYPES:
        return normalized
    return _TYPE_ALIASES.get(normalized) or _TYPE_ALIASES.get(value.strip())


def resolve_entity_typist(repo: object) -> LLMEntityTypist | None:
    """per-persona ChatConfig から provider を解決して typist を作る。

    ``resolve_decision_judge`` と同じ経路。解決不能（_conn 無し・api_key 空）は
    None を返し、backfill は起動しない（fail-open）。
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
            logger.warning("entity typist unavailable (no_api_key)")
            return None
        return LLMEntityTypist(
            provider_name=p.provider,
            api_key=api_key,
            model=p.get_effective_model(),
            base_url=p.get_effective_base_url(),
            session_id=f"nous-typist-{conn.persona}",
        )
    except Exception:
        logger.debug("entity typist resolver failed", exc_info=True)
        return None
