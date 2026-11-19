"""ログ・イベントに残す前に秘密値を潰す（kanban #75）。

`tool.called` の `params_summary` は LLM 生成の任意 dict を文字列化したものなので、
URL に埋まったトークン・`export API_KEY=...`・MCP の認証ヘッダがそのまま
`session_events`（永続）と SSE に出てしまう。例外文字列も sqlite3 の
`IntegrityError` のように SQL 断片を運ぶ。

マスクの対象名は `ChatConfig.is_secret_field` / `is_secret_header_name` と揃えてある
（HTTP の GET 側が `***` にしているのにログだけ生値、という不揃いを作らないため）。
"""

from __future__ import annotations

import re
from typing import Any

from nous.domain.config.chat_config import ChatConfig

REDACTED = "***"

# `api_key=xxx` / `"token": "xxx"` / `Authorization: Bearer xxx` を拾う。
_TEXT_SECRET_RE = re.compile(
    r"""(?P<name>[A-Za-z0-9_.\-]*(?:api[_\-]?key|token|secret|password|passwd|credential|cookie)[A-Za-z0-9_.\-]*)"""
    r"""(?P<sep>\s*[:=]\s*)"""
    r"""(?P<quote>["']?)"""
    r"""(?P<value>[^\s"'&,;}\]]+)""",
    re.IGNORECASE,
)
_BEARER_RE = re.compile(r"(?i)\b(bearer|basic)\s+[A-Za-z0-9._~+/\-]+=*")
# `name=` を伴わずに貼られた鍵（ログ・例外文でよくある）。
_BARE_KEY_RE = re.compile(
    r"\b(?:sk-[A-Za-z0-9_\-]{8,}|ghp_[A-Za-z0-9]{16,}|github_pat_[A-Za-z0-9_]{20,}|xox[abprs]-[A-Za-z0-9\-]{10,}|AKIA[0-9A-Z]{16})"
)


def is_secret_name(name: str) -> bool:
    """dict のキー名が秘密値か（ChatConfig の判定に揃える）。"""
    return ChatConfig.is_secret_field(name) or ChatConfig.is_secret_header_name(name)


def redact_text(text: str, max_len: int | None = None) -> str:
    """自由文（例外メッセージ等）から秘密値を潰す。"""
    masked = _BEARER_RE.sub(lambda m: f"{m.group(1)} {REDACTED}", text)
    masked = _BARE_KEY_RE.sub(REDACTED, masked)
    masked = _TEXT_SECRET_RE.sub(lambda m: f"{m.group('name')}{m.group('sep')}{m.group('quote')}{REDACTED}", masked)
    if max_len is not None and len(masked) > max_len:
        return masked[: max(0, max_len - 1)] + "…"
    return masked


def redact_params(params: Any, max_len: int = 200) -> str:
    """ツール引数を 1 行サマリにする。秘密キーの値は ``***``。"""
    if isinstance(params, dict):
        safe = {k: REDACTED if isinstance(k, str) and is_secret_name(k) else v for k, v in params.items()}
        text = str(safe)
    else:
        text = str(params)
    return redact_text(text, max_len)


__all__ = ["REDACTED", "is_secret_name", "redact_params", "redact_text"]
