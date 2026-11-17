"""Web 取得の builtin（#48）。

エージェントが「調べる」を選びやすい形にするための最小の 2 本:

- ``web_search`` — キー無しで叩ける Wikipedia の検索 API（ja/en）だけを見る
- ``fetch_content`` — URL を 1 本取って本文テキストにする

mcp-hub の ``search_tools`` → ``execute_tool`` を通す案（カード #48 の (a)）は実測で
見送った: nous の persona 設定は ``X-MCP-Hub-Tags: nous`` で hub に繋いでおり、その
タグに登録された上流サーバーが 0 件のため ``search_tools`` は常に isError を返す
（pool.list_all_tools() も hub のメタ 3 本しか見えない）。タグ付けは compose 側の
設定なので、このリポジトリの変更だけでは解消できない。

sandbox の ``curl`` は逃げ道として残す。ここは「キー無しで確実に動く」ものだけを置く。
"""

from __future__ import annotations

import html
import ipaddress
import re
import socket
from typing import TYPE_CHECKING, Any
from urllib.parse import quote, urlparse

import httpx

from nous.infrastructure.logging.structured import get_logger

if TYPE_CHECKING:
    from nous.application.context.app_context import AppContext
    from nous.domain.chat_config import ChatConfig

logger = get_logger(__name__)

_TIMEOUT = 15.0
#: 1 ページで読むバイト数の上限（巨大 HTML でメモリを食わないため）。
_MAX_BYTES = 400_000
#: fetch_content が返す本文の既定 / 上限文字数。
_DEFAULT_CHARS = 4000
_MAX_CHARS = 20_000
#: web_search の既定 / 上限件数。
_DEFAULT_LIMIT = 5
_MAX_LIMIT = 10

_UA = "nous/4.0 (+https://github.com/solidlime/Nous)"

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"[ \t\u3000]+")
_BLANKLINES_RE = re.compile(r"\n{3,}")
# 本文でない要素は丸ごと落とす（中身を残すとナビとスクリプトが本文に混ざる）。
_DROP_RE = re.compile(
    r"<(script|style|noscript|svg|head|nav|footer|form)\b[^>]*>.*?</\1\s*>",
    re.S | re.I,
)
_BREAK_RE = re.compile(r"<(?:br|/p|/div|/li|/h[1-6]|/tr)\b[^>]*>", re.I)
# 本文領域があればそこだけ見る（ナビ・サイドバーを本文に混ぜない）。
_MAIN_RE = re.compile(r"<main\b[^>]*>(.*?)</main\s*>", re.S | re.I)
_ARTICLE_RE = re.compile(r"<article\b[^>]*>(.*?)</article\s*>", re.S | re.I)


def _html_to_text(raw: str) -> str:
    """HTML を素の本文テキストにする（依存を増やさないための最小実装）。

    shortcut: ナビ・目次・サイドバーは残る（Wikipedia のように ``<main>`` の中に
    全部入っているサイトでは特に）。readability 相当が要るなら trafilatura 等の
    導入を検討する、本文の精度が問題になった時。
    """
    for pattern in (_MAIN_RE, _ARTICLE_RE):
        found = pattern.search(raw)
        if found:
            raw = found.group(1)
            break
    text = _DROP_RE.sub(" ", raw)
    text = _BREAK_RE.sub("\n", text)
    text = _TAG_RE.sub("", text)
    text = html.unescape(text)
    text = _WS_RE.sub(" ", text)
    text = "\n".join(line.strip() for line in text.splitlines())
    return _BLANKLINES_RE.sub("\n\n", text).strip()


def _is_blocked_host(host: str) -> bool:
    """社内・ループバック宛の取得を弾く（``http://172.17.0.1:...`` 等）。

    sandbox の bash には元から同じことができるので、これは新しい能力の制限ではなく
    チャット経路から Docker ネットワークを覗かせないための最低限の線引き。
    """
    if not host:
        return True
    if host in {"localhost", "localhost.localdomain"} or host.endswith(".local"):
        return True
    try:
        infos = socket.getaddrinfo(host, None)
    except OSError:
        return False  # 解決できないなら httpx 側で失敗する。DNS で弾かない
    for info in infos:
        addr = str(info[4][0])
        try:
            ip = ipaddress.ip_address(addr.split("%", 1)[0])
        except ValueError:
            continue
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
            return True
    return False


def _normalize_url(raw: str) -> str:
    url = (raw or "").strip()
    if url and "://" not in url:
        url = "https://" + url
    return url


async def _get(url: str, *, params: dict[str, Any] | None = None) -> httpx.Response:
    async with httpx.AsyncClient(
        timeout=_TIMEOUT,
        follow_redirects=True,
        headers={"User-Agent": _UA},
    ) as client:
        return await client.get(url, params=params)


async def handle_fetch_content(ctx: AppContext, config: ChatConfig, tool_input: dict) -> dict:
    """URL を取得して本文らしきテキストを返す。"""
    del ctx, config
    url = _normalize_url(str(tool_input.get("url") or ""))
    if not url:
        return {"status": "error", "message": "url が空"}
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        return {"status": "error", "message": f"http/https 以外は取得できない: {parsed.scheme or '(なし)'}"}
    if _is_blocked_host(parsed.hostname or ""):
        return {"status": "error", "message": "内部ネットワーク宛の URL は取得しない"}

    max_chars = tool_input.get("max_chars")
    try:
        limit = min(int(max_chars), _MAX_CHARS) if max_chars else _DEFAULT_CHARS
    except (TypeError, ValueError):
        limit = _DEFAULT_CHARS

    try:
        resp = await _get(url)
    except httpx.TimeoutException:
        return {"status": "error", "message": f"取得がタイムアウトした（{_TIMEOUT:.0f}s）"}
    except httpx.HTTPError as exc:
        return {"status": "error", "message": f"取得できなかった: {type(exc).__name__}: {exc}"}

    if resp.status_code >= 400:
        return {"status": "error", "message": f"HTTP {resp.status_code} / {url}"}

    ctype = resp.headers.get("content-type", "")
    body = resp.content[:_MAX_BYTES].decode(resp.encoding or "utf-8", errors="replace")
    text = body if "html" not in ctype.lower() else _html_to_text(body)
    truncated = len(text) > limit
    if truncated:
        text = text[:limit]
    logger.info("fetch_content: %s (%d chars, %s)", url, len(text), ctype[:40])
    return {
        "status": "success",
        "url": str(resp.url),
        "text": text,
        "chars": len(text),
        "truncated": truncated,
        "content_type": ctype.split(";")[0],
    }


async def handle_web_search(ctx: AppContext, config: ChatConfig, tool_input: dict) -> dict:
    """Wikipedia（ja/en）の全文検索で候補を返す。"""
    del ctx, config
    query = str(tool_input.get("query") or "").strip()
    if not query:
        return {"status": "error", "message": "query が空"}
    try:
        limit = min(int(tool_input.get("limit") or _DEFAULT_LIMIT), _MAX_LIMIT)
    except (TypeError, ValueError):
        limit = _DEFAULT_LIMIT

    hits: list[dict[str, Any]] = []
    seen: set[str] = set()
    errors: list[str] = []
    for lang in ("ja", "en"):
        params = {
            "action": "query",
            "list": "search",
            "srsearch": query,
            "srlimit": limit,
            "srprop": "snippet",
            "format": "json",
        }
        url = f"https://{lang}.wikipedia.org/w/api.php"
        try:
            resp = await _get(url, params=params)
            resp.raise_for_status()
            data = resp.json()
        except httpx.HTTPError as exc:
            errors.append(f"{lang}: {type(exc).__name__}")
            continue
        except ValueError:
            errors.append(f"{lang}: JSON でない応答")
            continue
        for item in (data.get("query") or {}).get("search") or []:
            title = str(item.get("title") or "")
            if not title or title in seen:
                continue
            seen.add(title)
            hits.append(
                {
                    "title": title,
                    "url": f"https://{lang}.wikipedia.org/wiki/{quote(title.replace(' ', '_'))}",
                    "snippet": _html_to_text(str(item.get("snippet") or "")),
                    "lang": lang,
                }
            )

    if not hits:
        if errors:
            return {"status": "error", "message": "検索できなかった: " + ", ".join(errors)}
        return {"status": "success", "query": query, "results": [], "note": "該当なし"}
    logger.info("web_search: %r -> %d hits", query, len(hits))
    return {
        "status": "success",
        "query": query,
        "source": "wikipedia",
        "results": hits[: limit * 2],
    }
