"""Tool contract registry vs live surfaces (audit C1 / v4.0).

The MCP face (``nous/api/mcp/tools.py``), the builtin/chat face
(``nous/application/chat/tools/definitions.py``) and the HTTP face
(``nous/api/http/routers/chat/chat_management.py``) each declare the same
tools by hand. ``nous/domain/tools/registry.py`` is the single source of
truth for those declarations; this module fails the build whenever a live
face drifts away from it.

Design decision (#003): the registry is *not* used to generate the faces.
Generation would have to encode per-face logic (envelope wrapping, alias
handling, builtin DSL mapping) and would silently "fix" intentional
asymmetry. Instead every intentional asymmetry must carry a ``divergence``
reason in the registry, and ``test_divergence_documents_exactly_the_real_differences``
proves that the reason is present iff the contracts actually differ.
"""

from __future__ import annotations

import inspect
from unittest.mock import MagicMock, patch

import pytest

from nous.application.chat.tools.builtin import _BUILTIN_DISPATCH, _MCP_SHARED_TOOLS
from nous.application.chat.tools.definitions import MEMORY_TOOLS
from nous.domain.tools.registry import (
    BUILTIN,
    HTTP,
    MCP,
    TOOL_SPECS,
    VALID_SURFACES,
    specs_for_surface,
    tool_names,
)

# HTTP の /tool エンドポイント（execute_tool）が実行を解決できるツール。
# search_tools は ToolRegistry（チャット経路）専用で HTTP からは解決しない。
_HTTP_EXECUTABLE = frozenset(_BUILTIN_DISPATCH) | frozenset(_MCP_SHARED_TOOLS)


@pytest.fixture(scope="module")
def live_mcp_tools() -> dict[str, object]:
    """register_tools をモック FastMCP に通して、登録された関数を名前で捕まえる。"""
    tools: dict[str, object] = {}

    def mock_tool_decorator(*args, **kwargs):
        def decorator(func):
            tools[func.__name__] = func
            return func

        return decorator

    mock_mcp = MagicMock()
    mock_mcp.tool = mock_tool_decorator
    with patch("nous.api.mcp.tools.get_current_persona", return_value="test_persona"):
        from nous.api.mcp.tools import register_tools

        register_tools(mock_mcp)
    return tools


def _mcp_contract(func: object) -> tuple[frozenset[str], frozenset[str]]:
    names: set[str] = set()
    required: set[str] = set()
    for param in inspect.signature(func).parameters.values():  # type: ignore[arg-type]
        if param.kind in (param.VAR_KEYWORD, param.VAR_POSITIONAL):
            continue
        names.add(param.name)
        if param.default is param.empty:
            required.add(param.name)
    return frozenset(names), frozenset(required)


def _builtin_contract(definition: object) -> tuple[frozenset[str], frozenset[str]]:
    schema = definition.input_schema  # type: ignore[attr-defined]
    return frozenset(schema.get("properties", {})), frozenset(schema.get("required", []))


# ---------------------------------------------------------------------------
# 1. 宣言そのものの健全性
# ---------------------------------------------------------------------------


def test_registry_declaration_is_well_formed() -> None:
    assert TOOL_SPECS, "registry must not be empty"
    for name, spec in TOOL_SPECS.items():
        assert spec.name == name, f"{name}: spec.name mismatch"
        assert spec.summary, f"{name}: summary must not be empty"
        assert spec.surfaces, f"{name}: surfaces must not be empty"
        unknown = spec.surfaces - VALID_SURFACES
        assert not unknown, f"{name}: unknown surface(s) {sorted(unknown)}"
        declared = set(spec.params)
        assert declared == set(spec.surfaces), (
            f"{name}: params must be declared for exactly the declared surfaces "
            f"(surfaces={sorted(spec.surfaces)}, params={sorted(declared)})"
        )
        for surface, params in spec.params.items():
            names = [p.name for p in params]
            assert len(names) == len(set(names)), f"{name}/{surface}: duplicate param name"
            assert all(p.type for p in params), f"{name}/{surface}: param type must not be empty"


# ---------------------------------------------------------------------------
# 2. MCP 面
# ---------------------------------------------------------------------------


def test_mcp_surface_matches_dispatch_table() -> None:
    from nous.api.mcp.tools import TOOL_DISPATCH

    assert tool_names(MCP) == frozenset(TOOL_DISPATCH), (
        f"MCP registry/dispatch drift: "
        f"registry-only={sorted(tool_names(MCP) - set(TOOL_DISPATCH))}, "
        f"dispatch-only={sorted(set(TOOL_DISPATCH) - tool_names(MCP))}"
    )


def test_mcp_surface_params_match_live_signatures(live_mcp_tools) -> None:
    assert frozenset(live_mcp_tools) == tool_names(MCP)
    for spec in specs_for_surface(MCP):
        live_names, live_required = _mcp_contract(live_mcp_tools[spec.name])
        assert spec.param_names(MCP) == live_names, (
            f"{spec.name} (mcp): param drift registry={sorted(spec.param_names(MCP))} live={sorted(live_names)}"
        )
        assert spec.required_names(MCP) == live_required, (
            f"{spec.name} (mcp): required drift registry={sorted(spec.required_names(MCP))} "
            f"live={sorted(live_required)}"
        )


# ---------------------------------------------------------------------------
# 3. 組込(chat) 面
# ---------------------------------------------------------------------------


def test_builtin_surface_matches_live_definitions() -> None:
    live = {d.name: d for d in MEMORY_TOOLS}
    assert tool_names(BUILTIN) == frozenset(live)
    for spec in specs_for_surface(BUILTIN):
        live_names, live_required = _builtin_contract(live[spec.name])
        assert spec.param_names(BUILTIN) == live_names, (
            f"{spec.name} (builtin): param drift registry={sorted(spec.param_names(BUILTIN))} live={sorted(live_names)}"
        )
        assert spec.required_names(BUILTIN) == live_required, (
            f"{spec.name} (builtin): required drift registry={sorted(spec.required_names(BUILTIN))} "
            f"live={sorted(live_required)}"
        )


# ---------------------------------------------------------------------------
# 4. HTTP 面
# ---------------------------------------------------------------------------


def test_http_surface_matches_executable_tool_names() -> None:
    assert tool_names(HTTP) == _HTTP_EXECUTABLE, (
        f"HTTP registry/dispatch drift: "
        f"registry-only={sorted(tool_names(HTTP) - _HTTP_EXECUTABLE)}, "
        f"executable-only={sorted(_HTTP_EXECUTABLE - tool_names(HTTP))}"
    )
    # search_tools はチャット経路の ToolRegistry 専用（HTTP /tool は解決しない）
    assert "search_tools" not in tool_names(HTTP)


def test_http_surface_contract_equals_builtin_contract() -> None:
    """HTTP は builtin の input_schema をそのまま実行するので契約は一致必須。"""
    for spec in specs_for_surface(HTTP):
        assert HTTP in spec.surfaces and BUILTIN in spec.surfaces, spec.name
        assert spec.params_for(HTTP) == spec.params_for(BUILTIN), (
            f"{spec.name}: HTTP と builtin の契約が異なる（同一の input_schema を使うはず）"
        )


# ---------------------------------------------------------------------------
# 5. 面間ドリフトの差別化（本命）
# ---------------------------------------------------------------------------


def test_divergence_documents_exactly_the_real_differences() -> None:
    """面間で契約が違うなら理由が書かれていること。同じなら理由は空であること。"""
    for spec in TOOL_SPECS.values():
        api_surfaces = sorted(s for s in spec.surfaces if s != HTTP)
        if len(api_surfaces) < 2:
            assert not spec.divergence, f"{spec.name}: 単一面なのに divergence が書かれている: {spec.divergence!r}"
            continue

        contracts = {(spec.param_names(s), spec.required_names(s)) for s in api_surfaces}
        differs = len(contracts) > 1
        if differs:
            assert spec.divergence, (
                f"{spec.name}: {api_surfaces} の契約が異なるのに divergence が空。"
                f"面ごとの契約: "
                + ", ".join(
                    f"{s}=({sorted(spec.param_names(s))}, req={sorted(spec.required_names(s))})" for s in api_surfaces
                )
            )
        else:
            assert not spec.divergence, (
                f"{spec.name}: 契約は全面同一なのに divergence が書かれている: {spec.divergence!r}"
            )


def test_every_live_tool_is_declared() -> None:
    """どちらの面のツールも registry から漏れていないこと（双方向）。"""
    live_mcp = tool_names(MCP)
    live_builtin = frozenset(d.name for d in MEMORY_TOOLS)
    assert live_mcp == {s.name for s in TOOL_SPECS.values() if MCP in s.surfaces}
    assert live_builtin == {s.name for s in TOOL_SPECS.values() if BUILTIN in s.surfaces}
