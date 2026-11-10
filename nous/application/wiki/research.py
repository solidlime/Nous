"""登録済み MCP ツールだけを使った自走調査（#40）。

計画書: ``docs/superpowers/plans/2026-11-10-journal-conflicts-and-research.md`` §4.3。

編纂中に出た「外部で確かめないと決められない問い」を、persona に**登録済みの MCP
サーバーのツール**だけで調べる。検索 API（ddgs 等）を直接は叩かない:

- 登録サーバーが 0 件 / ツールが 0 件なら**即 return ``{}``**（MCP を張らない。何もしない）
- LLM には 1 手ずつ ``{"tool": .., "args": ..}`` / ``{"answer": ..}`` / ``{"give_up": true}``
  を出させ、ツール結果は 2KB に切り詰めて履歴へ積む。``max_calls`` で打ち切る
- URL の取れない応答は採用しない（``## 外部情報`` に残せない = 後から検証できない）
- 接続失敗・timeout・JSON 破損はすべて握って理由付きで返す（worker を絶対に落とさない）

**戻り値の契約**: 成功は ``{"answer", "calls", "tools", "hits"}``。失敗は
``{"reason": "no_tools" | "no_url" | "failed"}`` のみ。どちらも偽でない dict なので、
呼び出し側は ``result.get("hits")`` の有無で「調査できたか」を判断できる。
「ツールが無い」と「調べたが失敗した」を混ぜないための区別（監査が嘘をつかない）。
"""

from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING, Any

from nous.infrastructure.logging.structured import get_logger

if TYPE_CHECKING:
    from nous.config.settings import WikiConfig

logger = get_logger(__name__)

#: 履歴に積むツール結果の上限（トークン膨張を防ぐ）。
_RESULT_CHARS = 2048
#: LLM に渡すツール説明の先頭文字数。
_TOOL_DESC_CHARS = 120
#: 1 回の調査で採用する hit の上限。
_MAX_HITS = 5
#: 1 手あたりの max_tokens（切れ JSON は 1 回だけ 2 倍で再試行する）。
_MAX_TOKENS = 4000
#: LLM 呼び出しの試行回数（worker の _llm_attempts と同じ流儀）。
_ATTEMPTS = 2

_MD_LINK_RE = re.compile(r"\[([^\]\n]{1,160})\]\((https?://[^)\s>]+)\)")
_BARE_URL_RE = re.compile(r"https?://[^\s)\]<>\"']+")

_STEP_PROMPT = """あなたは記録係です。以下の質問を、提供されているツールだけを使って調べてください。

質問: {question}

使えるツール（これ以外は存在しない。name はそのまま tool に入れる）:
{tools}

これまでの手順:
{history}

次の一手を 1 つだけ、以下の JSON で返してください（説明文は不要）:
- ツールを使う: {{"tool": "<name>", "args": {{...}}}}
- 答えがまとまった: {{"answer": "結論。根拠にした URL を必ず含める"}}
- 調べても分からない: {{"give_up": true}}

ルール:
- ツールは最大 {max_calls} 回まで。同じツールを同じ引数で繰り返さない。
- 推測で答えない。ツールの結果に無いことは書かない。
- answer には根拠の URL を必ず含める（URL の無い答えは採用されない）。
"""


async def research(ctx: Any, persona: str, question: str, *, max_calls: int = 3) -> dict:
    """登録 MCP ツールで ``question`` を調べる。

    戻り値: 成功 ``{"answer": str, "calls": int, "tools": [str], "hits": [{"title", "url"}]}``
    / 失敗 ``{"reason": "no_tools" | "no_url" | "failed"}``。
    """
    if not question.strip():
        return {"reason": "failed"}
    try:
        return await _research(ctx, persona, question, max_calls=max_calls)
    except Exception as e:  # noqa: BLE001 — worker を落とさないのが最優先
        logger.warning("research: persona=%s failed: %s", persona, e)
        return {"reason": "failed"}


async def _research(ctx: Any, persona: str, question: str, *, max_calls: int) -> dict:
    """config → プール → ツール 0 件チェック → 1 手ずつの探索。"""
    from nous.domain.chat_config import ChatConfigFileRepository

    config = ChatConfigFileRepository(ctx.settings.data_root).get(persona)
    if not config.mcp_servers:
        return {"reason": "no_tools"}  # 登録が無いなら MCP を張らない（fetch もしない）

    from nous.infrastructure.mcp_client.pool import MCPClientPool

    async with MCPClientPool(config.mcp_servers) as pool:
        tools = pool.list_all_tools()
        if not tools:
            return {"reason": "no_tools"}
        return await _explore(ctx, pool, tools, question, max_calls=max_calls)


async def _explore(ctx: Any, pool: Any, tools: list, question: str, *, max_calls: int) -> dict:
    """LLM に 1 手ずつ出させ、ツールを実行する（``max_calls`` でハードストップ）。"""
    names = {tool.name for tool in tools}
    history: list[str] = []
    used: list[str] = []
    answers: list[str] = []
    pairs: list[tuple[str, str]] = []
    for _ in range(max(0, max_calls)):
        step = await _ask_step(ctx, tools, question, history, max_calls=max_calls)
        if step is None:
            # LLM が応答を返さなかった（モデル側の障害）。ツール未到達と区別する。
            return {"reason": "failed"}
        if step.get("give_up"):
            break
        answer = step.get("answer")
        if isinstance(answer, str) and answer.strip():
            answers.append(answer.strip())
            pairs.extend(_links(answer))
            break
        name = str(step.get("tool") or "")
        if name not in names:
            # 登録外のツールは実行しない（幻覚名はツール呼び出し回数に数えない）。
            history.append(f"{name!r} は一覧に無い。一覧の name だけを使う。")
            continue
        args = step.get("args") if isinstance(step.get("args"), dict) else {}
        used.append(name)
        ok, excerpt = _excerpt(await pool.call_tool(name, args))
        if ok:
            # エラー本文に URL が混ざっていても根拠にしない（根拠抽出は成功時のみ）。
            pairs.extend(_links(excerpt))
        history.append(f"{name}({json.dumps(args, ensure_ascii=False)}) -> {excerpt}")

    hits = _hits(pairs)
    if not hits:
        # 調査は走ったが URL が取れなかった（LLM 障害の `failed` と区別する）。
        return {"reason": "no_url"}
    return {"answer": "\n".join(answers), "calls": len(used), "tools": used, "hits": hits}


async def _ask_step(ctx: Any, tools: list, question: str, history: list[str], *, max_calls: int) -> dict | None:
    """LLM に次の一手を出させる（切れ JSON は 1 回だけ予算 2 倍で再試行）。"""
    cfg: WikiConfig = ctx.settings.wiki
    api_key = cfg.get_effective_api_key(ctx.settings)
    if not api_key:
        raise RuntimeError("research LLM api_key is not configured")
    prompt = _build_step_prompt(tools, question, history, max_calls=max_calls)
    for attempt in range(_ATTEMPTS):
        raw = await _ask(cfg, api_key, prompt, boost=attempt)
        if not raw:
            logger.warning("research: empty llm response (attempt %d)", attempt + 1)
            continue
        try:
            return _parse_step(raw)
        except Exception as e:  # noqa: BLE001 — JSON 破損は再試行で拾う
            logger.warning("research: invalid llm step (attempt %d): %s", attempt + 1, e)
    return None


async def _ask(cfg: WikiConfig, api_key: str, prompt: str, *, boost: int = 0) -> str | None:
    """プロンプト 1 本を LLM に渡す（計器は持たない。監査は呼び出し側）。"""
    from nous.infrastructure.llm.base import LLMMessage
    from nous.infrastructure.llm.factory import get_provider
    from nous.infrastructure.llm.text_utils import collect_text

    provider = get_provider(cfg.provider, api_key, cfg.model, cfg.base_url)
    return await collect_text(
        provider,
        messages=[LLMMessage(role="user", content=prompt)],
        system="",
        tools=None,
        temperature=0.0,
        max_tokens=_MAX_TOKENS * (2**boost),
    )


def _build_step_prompt(tools: list, question: str, history: list[str], *, max_calls: int) -> str:
    tool_lines = [
        json.dumps(
            {
                "name": tool.name,
                "description": (tool.description or "")[:_TOOL_DESC_CHARS],
                "args": getattr(tool, "input_schema", {}) or {},
            },
            ensure_ascii=False,
        )
        for tool in tools
    ]
    return _STEP_PROMPT.format(
        question=question,
        tools="\n".join(tool_lines),
        history="\n".join(history) or "(まだ何も実行していない)",
        max_calls=max_calls,
    )


def _parse_step(text: str) -> dict:
    """LLM 応答 1 手分の JSON（コードフェンス・前後の説明文を許容）。"""
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = stripped.strip("`")
        if stripped.startswith("json"):
            stripped = stripped[4:]
    start, end = stripped.find("{"), stripped.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("no JSON object found in response")
    data = json.loads(stripped[start : end + 1])
    if not isinstance(data, dict):
        raise ValueError("response is not a JSON object")
    return data


def _excerpt(result: Any) -> tuple[bool, str]:
    """ツール結果 → (成功か, 履歴に積む 2KB の抜粋)。

    失敗時は ``False`` を返し、呼び出し側は URL 抽出に使わない（エラー本文の
    URL を根拠にしない）。
    """
    if isinstance(result, dict):
        if result.get("error"):
            return False, f"error: {result['error']}"[:_RESULT_CHARS]
        if result.get("isError") or result.get("is_error"):
            return False, "error: tool returned isError" + " " + str(result.get("result", ""))[: _RESULT_CHARS // 2]
        value = result.get("result", result)
    else:
        value = result
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, default=str)
    return True, text[:_RESULT_CHARS]


def _links(text: str) -> list[tuple[str, str]]:
    """テキスト中の (title, url)。markdown リンク優先、裸 URL は title=URL。"""
    pairs = [(m.group(1).strip(), m.group(2)) for m in _MD_LINK_RE.finditer(text or "")]
    seen = {url for _, url in pairs}
    for match in _BARE_URL_RE.finditer(text or ""):
        url = match.group(0).rstrip(".,;:")
        if url in seen:
            continue
        seen.add(url)
        pairs.append((url, url))
    return pairs


def _hits(pairs: list[tuple[str, str]]) -> list[dict]:
    """(title, url) → 重複を落とした hits（最大 ``_MAX_HITS`` 件）。"""
    hits: list[dict] = []
    seen: set[str] = set()
    for title, url in pairs:
        if url in seen:
            continue
        seen.add(url)
        hits.append({"title": title or url, "url": url})
        if len(hits) >= _MAX_HITS:
            break
    return hits
