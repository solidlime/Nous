"""web builtin（#48）のテスト。ネットワークは張らずに ``_get`` を差し替える。"""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from nous.application.chat.tools import web

# ハンドラは AppContext / ChatConfig を要求するが、ここで見たいのは入出力だけ。
_ANY_CTX: Any = None
_ANY_CFG: Any = None


def _resp(
    status: int,
    body: bytes | str | dict,
    url: str = "https://example.com/",
    ctype: str = "text/html",
) -> httpx.Response:
    request = httpx.Request("GET", url)
    headers = {"content-type": ctype}
    if isinstance(body, dict):
        return httpx.Response(status, json=body, headers=headers, request=request)
    content = body.encode() if isinstance(body, str) else body
    return httpx.Response(status, content=content, headers=headers, request=request)


# ── 純関数 ──


def test_html_to_text_drops_script_and_style() -> None:
    raw = "<html><head><title>t</title></head><body><script>var x=1;</script><p>本文</p></body></html>"
    out = web._html_to_text(raw)
    assert "本文" in out
    assert "var x=1" not in out  # script は丸ごと落とす


def test_html_to_text_keeps_block_breaks() -> None:
    out = web._html_to_text("<p>一行目</p><p>二行目</p>")
    assert out.splitlines() == ["一行目", "二行目"]


def test_html_to_text_prefers_main_region() -> None:
    raw = '<div id="nav">ナビ</div><main><p>本文</p></main><footer>フッタ</footer>'
    assert web._html_to_text(raw) == "本文"  # main の外は読まない


def test_html_to_text_falls_back_to_article() -> None:
    raw = "<nav>ナビ</nav><article><p>記事</p></article>"
    assert web._html_to_text(raw) == "記事"


def test_html_to_text_unescapes_entities() -> None:
    assert web._html_to_text("<p>a &amp; b &lt;c&gt;</p>") == "a & b <c>"


def test_normalize_url_adds_scheme() -> None:
    assert web._normalize_url("example.com/x") == "https://example.com/x"
    assert web._normalize_url(" http://a.b ") == "http://a.b"
    assert web._normalize_url("") == ""


def test_is_blocked_host_rejects_internal() -> None:
    assert web._is_blocked_host("localhost") is True
    assert web._is_blocked_host("172.17.0.1") is True
    assert web._is_blocked_host("127.0.0.1") is True
    assert web._is_blocked_host("") is True


def test_is_blocked_host_allows_public_ip() -> None:
    # 名前解決を挟まない IP 直指定で確認する（DNS 依存にしない）
    assert web._is_blocked_host("93.184.216.34") is False


# ── fetch_content ──


async def test_fetch_content_rejects_empty_url() -> None:
    out = await web.handle_fetch_content(_ANY_CTX, _ANY_CFG, {})
    assert out["status"] == "error"


async def test_fetch_content_rejects_non_http_scheme() -> None:
    out = await web.handle_fetch_content(_ANY_CTX, _ANY_CFG, {"url": "ftp://example.com/x"})
    assert out["status"] == "error"
    assert "http" in out["message"]


async def test_fetch_content_rejects_internal_host() -> None:
    out = await web.handle_fetch_content(_ANY_CTX, _ANY_CFG, {"url": "http://172.17.0.1:26262/health"})
    assert out["status"] == "error"
    assert "内部" in out["message"]


async def test_fetch_content_returns_text(monkeypatch) -> None:
    async def fake_get(url: str, *, params=None):
        return _resp(200, "<html><body><script>x</script><p>こんにちは</p></body></html>")

    monkeypatch.setattr(web, "_get", fake_get)
    out = await web.handle_fetch_content(_ANY_CTX, _ANY_CFG, {"url": "https://example.com/"})
    assert out["status"] == "success"
    assert out["text"] == "こんにちは"
    assert out["truncated"] is False


async def test_fetch_content_truncates(monkeypatch) -> None:
    async def fake_get(url: str, *, params=None):
        return _resp(200, "<p>" + "あ" * 500 + "</p>")

    monkeypatch.setattr(web, "_get", fake_get)
    out = await web.handle_fetch_content(_ANY_CTX, _ANY_CFG, {"url": "https://example.com/", "max_chars": 50})
    assert out["truncated"] is True
    assert len(out["text"]) == 50


async def test_fetch_content_reports_http_error(monkeypatch) -> None:
    async def fake_get(url: str, *, params=None):
        return _resp(404, "nope")

    monkeypatch.setattr(web, "_get", fake_get)
    out = await web.handle_fetch_content(_ANY_CTX, _ANY_CFG, {"url": "https://example.com/"})
    assert out["status"] == "error"
    assert "404" in out["message"]


async def test_fetch_content_reports_timeout(monkeypatch) -> None:
    async def fake_get(url: str, *, params=None):
        raise httpx.TimeoutException("slow")

    monkeypatch.setattr(web, "_get", fake_get)
    out = await web.handle_fetch_content(_ANY_CTX, _ANY_CFG, {"url": "https://example.com/"})
    assert out["status"] == "error"
    assert "タイムアウト" in out["message"]


# ── web_search ──


async def test_web_search_rejects_empty_query() -> None:
    out = await web.handle_web_search(_ANY_CTX, _ANY_CFG, {"query": "   "})
    assert out["status"] == "error"


async def test_web_search_collects_both_languages(monkeypatch) -> None:
    calls: list[str] = []

    async def fake_get(url: str, *, params=None):
        calls.append(url)
        lang = "ja" if "ja.wikipedia" in url else "en"
        return _resp(
            200,
            {
                "query": {
                    "search": [
                        {"title": f"{lang} title", "snippet": "<span>抜粋</span>"},
                    ]
                }
            },
            url=url,
            ctype="application/json",
        )

    monkeypatch.setattr(web, "_get", fake_get)
    out = await web.handle_web_search(_ANY_CTX, _ANY_CFG, {"query": "herta"})
    assert out["status"] == "success"
    assert [r["lang"] for r in out["results"]] == ["ja", "en"]
    assert out["results"][0]["snippet"] == "抜粋"  # タグは落とす
    assert out["results"][0]["url"].startswith("https://ja.wikipedia.org/wiki/")
    assert len(calls) == 2


async def test_web_search_dedupes_titles(monkeypatch) -> None:
    async def fake_get(url: str, *, params=None):
        return _resp(200, {"query": {"search": [{"title": "same", "snippet": ""}]}}, url=url, ctype="application/json")

    monkeypatch.setattr(web, "_get", fake_get)
    out = await web.handle_web_search(_ANY_CTX, _ANY_CFG, {"query": "x"})
    assert len(out["results"]) == 1  # ja と en で同じタイトルは 1 件に畳む


async def test_web_search_reports_backend_failure(monkeypatch) -> None:
    async def fake_get(url: str, *, params=None):
        raise httpx.ConnectError("down")

    monkeypatch.setattr(web, "_get", fake_get)
    out = await web.handle_web_search(_ANY_CTX, _ANY_CFG, {"query": "x"})
    assert out["status"] == "error"
    assert "検索できなかった" in out["message"]


async def test_web_search_empty_result_is_success(monkeypatch) -> None:
    async def fake_get(url: str, *, params=None):
        return _resp(200, {"query": {"search": []}}, url=url, ctype="application/json")

    monkeypatch.setattr(web, "_get", fake_get)
    out = await web.handle_web_search(_ANY_CTX, _ANY_CFG, {"query": "x"})
    assert out["status"] == "success"
    assert out["results"] == []


@pytest.mark.parametrize("raw,expected", [("1", 1), (10, 10), (99, 10)])
async def test_web_search_limit_is_capped(monkeypatch, raw, expected) -> None:
    seen: list[int] = []

    async def fake_get(url: str, *, params=None):
        seen.append(params["srlimit"])
        return _resp(200, {"query": {"search": [{"title": "t", "snippet": ""}]}}, url=url, ctype="application/json")

    monkeypatch.setattr(web, "_get", fake_get)
    await web.handle_web_search(_ANY_CTX, _ANY_CFG, {"query": "x", "limit": raw})
    assert seen == [expected, expected]
