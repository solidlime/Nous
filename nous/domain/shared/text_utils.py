"""LLM 出力テキストの共通ユーティリティ（純粋関数のみ・依存ゼロ）。"""

from __future__ import annotations


def strip_code_fence(text: str) -> str:
    """LLM 出力からコードフェンスを剥がす。

    - 先頭が ``` / ```json（"``` json" の空白入り含む）なら全体のフェンスを剥がす。
    - 地の文に埋もれた ```json ... ``` ブロックは中身のみ抽出する（旧 Variant C 互換）。
    """
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned[3:].lstrip()
        if cleaned[:4].lower() == "json":
            cleaned = cleaned[4:]
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3]
        return cleaned.strip()
    if "```" in cleaned:
        body = cleaned.split("```", 1)[1].lstrip()
        if body[:4].lower() == "json":
            body = body[4:]
        if "```" in body:
            body = body.split("```", 1)[0]
        return body.strip()
    return cleaned
