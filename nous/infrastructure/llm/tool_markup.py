"""content に漏れたツール呼び出し記法（DeepSeek の DSML 等）の除去と復旧。

ゲートウェイがツール呼び出しのパースに失敗すると、モデルは呼び出しを独自記法の
まま本文へ書く。そのまま流すとユーザーに生の記法が出るうえ、呼び出しも実行されない。
ここで記法ブロックを本文から取り除き、可能なら本物の tool call に戻す。
"""

from __future__ import annotations

import json
import re

# 記法名。DeepSeek 系は <｜｜DSML｜｜ invoke name="bash"> ... の形で吐く（｜ は全角）。
_MARKUP_KEYWORD = "DSML"

# ブロックの終端になるタグ（invoke 単位で畳む。calls の閉じが無くても切り分けられる）
_END_RE = re.compile(r"</[^>]{0,60}?(?:calls|invoke)\s*>")
_INVOKE_RE = re.compile(r'invoke\s+name="([^"]+)"[^>]*>(.*?)</[^>]{0,60}?invoke\s*>', re.S)
_PARAM_RE = re.compile(r'parameter\s+name="([^"]+)"([^>]*)>(.*?)</[^>]{0,60}?parameter\s*>', re.S)

# 閉じタグが来ないまま伸び続けたら諦める（本文を飲み込まないための上限）
_MAX_MARKUP_CHARS = 20000
# タグの途中かもしれない末尾を保留する長さ（開きタグのうち閉じていない部分）
_MAX_TAG_WAIT = 60


def _coerce(raw: str, attrs: str) -> object:
    """パラメータ値を型に戻す。string="true" は文字列のまま。"""
    if 'string="true"' in attrs:
        return raw
    text = raw.strip()
    if text in ("true", "false"):
        return text == "true"
    try:
        if re.fullmatch(r"-?\d+", text):
            return int(text)
        if re.fullmatch(r"-?\d+\.\d+", text):
            return float(text)
    except ValueError:  # pragma: no cover - 上で形を縛っているので実質起きない
        return raw
    if text[:1] in "[{":
        try:
            return json.loads(text)
        except ValueError:
            return raw
    return raw


def parse_tool_calls(markup: str) -> list[tuple[str, dict[str, object]]]:
    """記法ブロックから (ツール名, 引数) を取り出す。取れなければ空リスト。"""
    calls: list[tuple[str, dict[str, object]]] = []
    for name, body in _INVOKE_RE.findall(markup):
        args = {pname: _coerce(value, attrs) for pname, attrs, value in _PARAM_RE.findall(body)}
        calls.append((name, args))
    return calls


class ToolMarkupStream:
    """ストリーム中のツール記法ブロックを捨て、見えている本文だけを返す。

    strip() の戻り値をユーザー向けに流し、捨てた記法は ``markup`` に溜めて
    最後に ``parse_tool_calls`` へ渡す。
    """

    def __init__(self) -> None:
        self.markup = ""
        self._pending = ""
        self._block = ""
        self._in_markup = False
        self._after_block = False

    def strip(self, text: str) -> str:
        buf = self._pending + text
        self._pending = ""
        return self._strip(buf)

    def _strip(self, buf: str) -> str:
        if self._in_markup:
            return self._consume(buf)
        if self._after_block:
            return self._after(buf)
        idx = buf.find(_MARKUP_KEYWORD)
        if idx == -1:
            # 末尾がタグの途中かもしれない分だけ保留する（閉じていない <... が残っている）
            cut = buf.rfind("<")
            if cut != -1 and len(buf) - cut <= _MAX_TAG_WAIT and ">" not in buf[cut:]:
                self._pending = buf[cut:]
                return buf[:cut]
            return buf
        start = buf.rfind("<", 0, idx)
        self._in_markup = True
        head = buf[:start] if start != -1 else buf[:idx]
        return head + self._consume(buf[start:] if start != -1 else buf[idx:])

    def _after(self, buf: str) -> str:
        """ブロック終端の直後。連続する閉じタグ（calls の閉じ等）を同じブロックとして飲む。"""
        if not buf:
            return ""
        match = re.match(r"(\s*)(</[^>]*>)", buf)
        if match:
            if _MARKUP_KEYWORD in match.group(2):
                self.markup += match.group(0)
                return self._after(buf[match.end() :])
            # 記法の閉じではないタグ → ブロック終了、このタグからは本文
            self._after_block = False
            return self._strip(buf)
        # 閉じタグがまだ途中（"</" だけ届いた等）なら保留して待つ
        stripped = buf.lstrip()
        if stripped.startswith("<") and ">" not in stripped:
            self._pending = buf[len(buf) - len(stripped) :]
            return buf[: len(buf) - len(stripped)]
        # 次の記法ブロックが続いていることがある → 本文に戻さず再走査する
        self._after_block = False
        return self._strip(buf)

    def _consume(self, buf: str) -> str:
        self._block += buf
        match = _END_RE.search(self._block)
        if not match:
            if len(self._block) > _MAX_MARKUP_CHARS:
                # 閉じが来ないまま暴走: 諦めて捨てる（本文を飲み込まない）
                self._block = ""
                self._in_markup = False
            return ""
        self.markup += self._block[: match.end()]
        rest = self._block[match.end() :]
        self._block = ""
        self._in_markup = False
        self._after_block = True
        return self._after(rest)

    def flush(self) -> str:
        """ストリーム終端で保留分（タグの途中で切れた本文）を返す。"""
        pending, self._pending = self._pending, ""
        if self._in_markup and self._block:
            # 閉じタグが来ないまま終わった: 部分復旧を試せるよう markup に残す
            self.markup += self._block
        self._block = ""
        return pending
