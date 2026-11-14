"""公開運用のセキュリティ診断（kanban #6）.

「公開してよい設定か」だけを見る読み取り専用の診断。値そのもの（API キー等）は
返さない — 起動ログ・``/health``・``/api/settings/diagnostics``・設定タブの
バナーに同じ結果を出せるように、判定はここ 1 箇所に閉じる。

開発既定（``0.0.0.0`` + ``api_key`` 空 + plugin 無効 + localhost CORS）は
Docker/dev の素通しとして **意図的に許容** する。診断は警告までで、起動は止めない。
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from nous.config.settings import Settings

#: loopback として扱う bind 先。これ以外（0.0.0.0 / :: / 実 IP）は公開 bind。
_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1", "[::1]"})
#: 全インターフェース bind。
_WILDCARD_HOSTS = frozenset({"", "0.0.0.0", "::", "[::]"})  # nosec B104 - 文字列比較であり bind ではない

#: plugin API キーの最低長（admin の ``general.api_key`` と同じ基準）。
PLUGIN_KEY_MIN_LENGTH = 16


@dataclass(frozen=True)
class Diagnostic:
    """1 件の診断結果（値は含めない）。"""

    code: str
    severity: str  # "warning"
    message: str
    hint: str

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


def is_public_bind(host: str) -> bool:
    """``host`` が loopback 以外（= LAN/公開から届く）かを返す。"""
    normalized = (host or "").strip().lower()
    if normalized in _LOOPBACK_HOSTS:
        return False
    if normalized in _WILDCARD_HOSTS:
        return True
    return True


def diagnose_security(settings: Settings) -> list[Diagnostic]:
    """公開運用上の危険な組み合わせを列挙する（無ければ空リスト）。"""
    found: list[Diagnostic] = []
    host = settings.server.host
    api_key = (settings.api_key or "").strip()

    if is_public_bind(host) and not api_key:
        found.append(
            Diagnostic(
                code="public_bind_without_api_key",
                severity="warning",
                message=f"HTTP を {host or '全インターフェース'} で公開 bind しているのに NOUS_API_KEY が未設定。",
                hint="Bearer 無しで誰でも API を叩ける。NOUS_API_KEY を設定するか NOUS_SERVER__HOST=127.0.0.1 にする。",
            )
        )

    origins = [str(o).strip() for o in settings.cors.allowed_origins]
    if "*" in origins:
        found.append(
            Diagnostic(
                code="cors_wildcard",
                severity="warning",
                message="CORS allowed_origins に '*' が入っている（全オリジン許可）。",
                hint="allow_credentials は自動で無効化される。公開運用では明示オリジンに絞る。",
            )
        )

    plugin = settings.plugin
    plugin_key = (plugin.api_key or "").strip()
    if plugin.enabled and not plugin_key:
        found.append(
            Diagnostic(
                code="plugin_enabled_without_api_key",
                severity="warning",
                message="Plugin API が有効なのに NOUS_PLUGIN__API_KEY が空。",
                hint="plugin 系エンドポイントは 500 を返し続ける。キーを設定するか NOUS_PLUGIN__ENABLED=false にする。",
            )
        )
    elif plugin.enabled and len(plugin_key) < PLUGIN_KEY_MIN_LENGTH:
        found.append(
            Diagnostic(
                code="plugin_weak_api_key",
                severity="warning",
                message=f"Plugin API キーが短い（{len(plugin_key)} 文字 < {PLUGIN_KEY_MIN_LENGTH}）。",
                hint="推測されにくい長いキーに差し替える。",
            )
        )

    mcp_security = settings.mcp_security
    if "*" in mcp_security.allowed_hosts and "*" in mcp_security.allowed_origins:
        found.append(
            Diagnostic(
                code="mcp_security_opened",
                severity="warning",
                message="MCP の Host/Origin 検証 allowlist が両方 '*'（DNS-rebinding 対策が無効）。",
                hint="公開運用では NOUS_MCP_SECURITY__ALLOWED_HOSTS / ALLOWED_ORIGINS を明示する。",
            )
        )

    return found


def security_summary(settings: Settings) -> dict:
    """``/health`` 用の要約（詳細は返さない）。"""
    warnings = diagnose_security(settings)
    return {
        "status": "warn" if warnings else "ok",
        "warnings": [d.code for d in warnings],
    }
