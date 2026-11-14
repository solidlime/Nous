"""公開運用セキュリティ診断（kanban #6）.

``diagnose_security`` は「公開 bind なのに鍵が無い」「CORS '*'」「plugin が
有効で鍵が弱い/空」を警告する。開発既定（0.0.0.0 + 鍵なし + plugin 無効）は
Docker/dev の素通しとして意図的に許容する — その線引きをテストで固定する。
"""

from __future__ import annotations

import pytest

from nous.config.security_diagnostics import diagnose_security, is_public_bind
from nous.config.settings import (
    CorsConfig,
    McpSecurityConfig,
    PluginConfig,
    ServerConfig,
    Settings,
)

pytestmark = pytest.mark.unit


def _settings(**kwargs) -> Settings:
    base = dict(
        server=ServerConfig(host="127.0.0.1"),
        cors=CorsConfig(allowed_origins=["http://localhost:3000"]),
        plugin=PluginConfig(enabled=False, api_key=""),
        mcp_security=McpSecurityConfig(
            allowed_hosts=["localhost", "127.0.0.1"],
            allowed_origins=["http://localhost:3000"],
        ),
        api_key="",
    )
    base.update(kwargs)
    return Settings(**base)


def test_loopback_without_key_is_clean() -> None:
    """localhost bind は認証なしでも公開されない（警告なし）。"""
    assert diagnose_security(_settings()) == []


def test_public_bind_without_key_warns() -> None:
    codes = [d.code for d in diagnose_security(_settings(server=ServerConfig(host="0.0.0.0")))]
    assert codes == ["public_bind_without_api_key"]


def test_public_bind_with_key_is_clean() -> None:
    assert diagnose_security(_settings(server=ServerConfig(host="0.0.0.0"), api_key="x" * 32)) == []


def test_cors_wildcard_warns() -> None:
    codes = [d.code for d in diagnose_security(_settings(cors=CorsConfig(allowed_origins=["*"])))]
    assert "cors_wildcard" in codes


def test_plugin_without_key_warns() -> None:
    codes = [d.code for d in diagnose_security(_settings(plugin=PluginConfig(enabled=True, api_key="")))]
    assert "plugin_enabled_without_api_key" in codes


def test_plugin_weak_key_warns() -> None:
    codes = [d.code for d in diagnose_security(_settings(plugin=PluginConfig(enabled=True, api_key="short")))]
    assert "plugin_weak_api_key" in codes


def test_plugin_strong_key_is_clean() -> None:
    assert diagnose_security(_settings(plugin=PluginConfig(enabled=True, api_key="k" * 32))) == []


def test_mcp_security_both_wildcard_warns() -> None:
    codes = [
        d.code
        for d in diagnose_security(
            _settings(mcp_security=McpSecurityConfig(allowed_hosts=["*"], allowed_origins=["*"]))
        )
    ]
    assert "mcp_security_opened" in codes


@pytest.mark.parametrize(
    ("host", "expected"),
    [("127.0.0.1", False), ("localhost", False), ("::1", False), ("0.0.0.0", True), ("", True), ("10.0.0.5", True)],
)
def test_is_public_bind(host: str, expected: bool) -> None:
    assert is_public_bind(host) is expected


def test_diagnostic_dict_has_no_values() -> None:
    """診断結果はメッセージとヒントだけで、設定値そのものを返さない。"""
    warnings = diagnose_security(_settings(plugin=PluginConfig(enabled=True, api_key="short")))
    payload = warnings[0].to_dict()
    assert set(payload) == {"code", "severity", "message", "hint"}
    assert "short" not in payload["message"].replace("短い", "")
