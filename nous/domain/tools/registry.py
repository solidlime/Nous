"""ツール契約レジストリ — MCP / 組込(chat) / HTTP の 3 面契約の単一情報源.

背景（監査 C1）: MCP 面（``nous/api/mcp/tools.py``）・組込面
（``nous/application/chat/tools/definitions.py``）・HTTP 面
（``nous/api/http/routers/chat/chat_management.py``）は同じツール群を
それぞれ手書きで宣言しており、片方だけ変更すると契約が静かに乖離する。

本モジュールは **宣言であって実行ディスパッチャではない**
（実行は ``nous/application/chat/tools/registry.py`` の ``ToolRegistry`` が担う）。
面の宣言と実スキーマの突合は ``tests/parity/test_tool_contract_registry.py`` が
常設で強制する（生成コードは使わない — #003 の設計判定 (b)）。

``surfaces`` が 2 面以上で、かつ面ごとにパラメータ契約が異なる場合は
``divergence`` に理由を必ず書く（テストが空文字を許さない）。
これは「意図的な非対称」と「事故によるドリフト」を区別するための装置である。

domain 層の規約に従い stdlib 以外に依存しない。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

# 面の識別子
MCP: Final[str] = "mcp"
BUILTIN: Final[str] = "builtin"
HTTP: Final[str] = "http"

VALID_SURFACES: Final[frozenset[str]] = frozenset({MCP, BUILTIN, HTTP})


@dataclass(frozen=True, slots=True)
class ToolParam:
    """1 つのツール引数の契約（面ごとに宣言する）。"""

    name: str
    type: str
    required: bool
    description: str = ""


@dataclass(frozen=True, slots=True)
class ToolSpec:
    """1 ツールの契約。``params`` は面 -> 引数タプル。"""

    name: str
    summary: str
    surfaces: frozenset[str]
    params: dict[str, tuple[ToolParam, ...]]
    divergence: str = ""

    def params_for(self, surface: str) -> tuple[ToolParam, ...]:
        """``surface`` の引数契約を返す（未宣言なら KeyError）。"""
        return self.params[surface]

    def param_names(self, surface: str) -> frozenset[str]:
        return frozenset(p.name for p in self.params_for(surface))

    def required_names(self, surface: str) -> frozenset[str]:
        return frozenset(p.name for p in self.params_for(surface) if p.required)


TOOL_SPECS: Final[dict[str, ToolSpec]] = {
    "get_context": ToolSpec(
        name="get_context",
        summary="ペルソナ状態と記憶の概観を返す（session_begin への移行期間の互換ツール）",
        surfaces=frozenset({MCP}),
        params={
            MCP: (ToolParam("project", "string|null", required=False),),
        },
    ),
    "goal_manage": ToolSpec(
        name="goal_manage",
        summary="目標・約束を管理する（set / achieved / abandoned / list）",
        surfaces=frozenset({MCP, BUILTIN, HTTP}),
        params={
            MCP: (
                ToolParam("operation", "string", required=True),
                ToolParam("content", "string", required=False),
                ToolParam("importance", "number", required=False),
                ToolParam("scope", "string", required=False),
                ToolParam("memory_key", "string|null", required=False),
                ToolParam("tags", "array<string>|null", required=False),
            ),
            BUILTIN: (
                ToolParam("operation", "string", required=True),
                ToolParam("content", "string", required=False),
                ToolParam("importance", "number", required=False),
                ToolParam("scope", "string", required=True),
                ToolParam("memory_key", "string", required=False),
                ToolParam("tags", "array", required=False),
            ),
            HTTP: (
                ToolParam("operation", "string", required=True),
                ToolParam("content", "string", required=False),
                ToolParam("importance", "number", required=False),
                ToolParam("scope", "string", required=True),
                ToolParam("memory_key", "string", required=False),
                ToolParam("tags", "array", required=False),
            ),
        },
        divergence="builtin 面は scope を必須にして LLM に明示させる。MCP 面は既定 'self' で省略可。",
    ),
    "image_generate": ToolSpec(
        name="image_generate",
        summary="ComfyUI で画像を生成する",
        surfaces=frozenset({BUILTIN, HTTP}),
        params={
            BUILTIN: (
                ToolParam("prompt", "string", required=True),
                ToolParam("preset", "string", required=False),
                ToolParam("n", "integer", required=False),
                ToolParam("self_portrait", "boolean", required=False),
                ToolParam("mode", "string", required=False),
            ),
            HTTP: (
                ToolParam("prompt", "string", required=True),
                ToolParam("preset", "string", required=False),
                ToolParam("n", "integer", required=False),
                ToolParam("self_portrait", "boolean", required=False),
                ToolParam("mode", "string", required=False),
            ),
        },
    ),
    "invoke_skill": ToolSpec(
        name="invoke_skill",
        summary="スキルを発動し、本文をセッションに常駐させる",
        surfaces=frozenset({BUILTIN, HTTP}),
        params={
            BUILTIN: (
                ToolParam("name", "string", required=True),
                ToolParam("task", "string", required=False),
                ToolParam("action", "string", required=False),
            ),
            HTTP: (
                ToolParam("name", "string", required=True),
                ToolParam("task", "string", required=False),
                ToolParam("action", "string", required=False),
            ),
        },
    ),
    "item_add": ToolSpec(
        name="item_add",
        summary="所持アイテムを追加する",
        surfaces=frozenset({MCP, BUILTIN, HTTP}),
        params={
            MCP: (
                ToolParam("item_name", "string", required=False),
                ToolParam("category", "string|null", required=False),
                ToolParam("description", "string|null", required=False),
                ToolParam("quantity", "integer", required=False),
                ToolParam("tags", "array<string>|null", required=False),
            ),
            BUILTIN: (
                ToolParam("item_name", "string", required=True),
                ToolParam("category", "string", required=False),
                ToolParam("description", "string", required=False),
                ToolParam("quantity", "integer", required=False),
                ToolParam("tags", "array", required=False),
            ),
            HTTP: (
                ToolParam("item_name", "string", required=True),
                ToolParam("category", "string", required=False),
                ToolParam("description", "string", required=False),
                ToolParam("quantity", "integer", required=False),
                ToolParam("tags", "array", required=False),
            ),
        },
        divergence="builtin 面は item_name を必須にして LLM に明示させる。MCP 面は既定 '' で、ツール内部のバリデーションに委ねる。",
    ),
    "item_equip": ToolSpec(
        name="item_equip",
        summary="アイテムを装備する（外見を再計算する）",
        surfaces=frozenset({MCP, BUILTIN, HTTP}),
        params={
            MCP: (
                ToolParam("equipment", "object|null", required=False),
                ToolParam("auto_add", "boolean", required=False),
            ),
            BUILTIN: (
                ToolParam("equipment", "object", required=True),
                ToolParam("auto_add", "boolean", required=False),
            ),
            HTTP: (
                ToolParam("equipment", "object", required=True),
                ToolParam("auto_add", "boolean", required=False),
            ),
        },
        divergence="builtin 面は equipment を必須にして LLM に明示させる。MCP 面は既定 None。",
    ),
    "item_search": ToolSpec(
        name="item_search",
        summary="所持アイテムを検索する",
        surfaces=frozenset({MCP, BUILTIN, HTTP}),
        params={
            MCP: (
                ToolParam("query", "string|null", required=False),
                ToolParam("category", "string|null", required=False),
            ),
            BUILTIN: (
                ToolParam("query", "string", required=False),
                ToolParam("category", "string", required=False),
            ),
            HTTP: (
                ToolParam("query", "string", required=False),
                ToolParam("category", "string", required=False),
            ),
        },
        divergence="",
    ),
    "item_unequip": ToolSpec(
        name="item_unequip",
        summary="指定スロットの装備を外す",
        surfaces=frozenset({MCP}),
        params={
            MCP: (ToolParam("slots", "array<string>", required=True),),
        },
    ),
    "list_skills": ToolSpec(
        name="list_skills",
        summary="利用可能なスキルの一覧を返す",
        surfaces=frozenset({BUILTIN, HTTP}),
        params={
            BUILTIN: (),
            HTTP: (),
        },
    ),
    "memory_create": ToolSpec(
        name="memory_create",
        summary="永続記憶を作成する",
        surfaces=frozenset({MCP, BUILTIN, HTTP}),
        params={
            MCP: (
                ToolParam("content", "string", required=False),
                ToolParam("importance", "number|null", required=False),
                ToolParam("tags", "array<string>|null", required=False),
                ToolParam("privacy_level", "string", required=False),
                ToolParam("source_context", "string|null", required=False),
                ToolParam("kind", "string", required=False),
                ToolParam("defer_vector", "boolean", required=False),
                ToolParam("skip_duplicate_check", "boolean", required=False),
            ),
            BUILTIN: (
                ToolParam("content", "string", required=True),
                ToolParam("importance", "number", required=False),
                ToolParam("tags", "array", required=False),
                ToolParam("skip_duplicate_check", "boolean", required=False),
            ),
            HTTP: (
                ToolParam("content", "string", required=True),
                ToolParam("importance", "number", required=False),
                ToolParam("tags", "array", required=False),
                ToolParam("skip_duplicate_check", "boolean", required=False),
            ),
        },
        divergence="builtin 面は content 必須の LLM 向け DSL。MCP 面は v3.x 互換のため content 既定 '' で、defer_vector / kind / privacy_level / source_context を追加で持つ。",
    ),
    "memory_delete": ToolSpec(
        name="memory_delete",
        summary="記憶を key またはクエリで削除する",
        surfaces=frozenset({MCP}),
        params={
            MCP: (
                ToolParam("memory_key", "string|null", required=False),
                ToolParam("query", "string|null", required=False),
                ToolParam("key", "string|null", required=False),
            ),
        },
    ),
    "memory_read": ToolSpec(
        name="memory_read",
        summary="記憶を key 指定または一覧で読む",
        surfaces=frozenset({MCP}),
        params={
            MCP: (
                ToolParam("memory_key", "string|null", required=False),
                ToolParam("limit", "integer", required=False),
                ToolParam("offset", "integer", required=False),
                ToolParam("key", "string|null", required=False),
            ),
        },
    ),
    "memory_search": ToolSpec(
        name="memory_search",
        summary="記憶をハイブリッド検索する（意味検索 + キーワード検索）",
        surfaces=frozenset({MCP, BUILTIN, HTTP}),
        params={
            MCP: (
                ToolParam("query", "string", required=True),
                ToolParam("top_k", "integer", required=False),
                ToolParam("tags", "array<string>|null", required=False),
                ToolParam("date_range", "string|null", required=False),
                ToolParam("min_importance", "number|null", required=False),
                ToolParam("emotion", "string|null", required=False),
                ToolParam("profile", "string|null", required=False),
                ToolParam("importance_weight", "number", required=False),
                ToolParam("recency_weight", "number", required=False),
                ToolParam("vector_weight", "number", required=False),
                ToolParam("keyword_weight", "number", required=False),
                ToolParam("kind", "string|null", required=False),
                ToolParam("sort", "string|null", required=False),
            ),
            BUILTIN: (
                ToolParam("query", "string", required=True),
                ToolParam("top_k", "integer", required=False),
                ToolParam("tags", "array", required=False),
                ToolParam("date_range", "string", required=False),
                ToolParam("min_importance", "number", required=False),
                ToolParam("emotion", "string", required=False),
                ToolParam("vector_weight", "number", required=False),
                ToolParam("keyword_weight", "number", required=False),
                ToolParam("sort", "string", required=False),
            ),
            HTTP: (
                ToolParam("query", "string", required=True),
                ToolParam("top_k", "integer", required=False),
                ToolParam("tags", "array", required=False),
                ToolParam("date_range", "string", required=False),
                ToolParam("min_importance", "number", required=False),
                ToolParam("emotion", "string", required=False),
                ToolParam("vector_weight", "number", required=False),
                ToolParam("keyword_weight", "number", required=False),
                ToolParam("sort", "string", required=False),
            ),
        },
        divergence="MCP 面のみ importance_weight / recency_weight / profile / kind を持つ（検索スコア調整は API 利用者向けで、組込 LLM には露出させない）。",
    ),
    "memory_stats": ToolSpec(
        name="memory_stats",
        summary="記憶ストアの統計を返す",
        surfaces=frozenset({MCP}),
        params={
            MCP: (ToolParam("top_n", "integer", required=False),),
        },
    ),
    "memory_update": ToolSpec(
        name="memory_update",
        summary="既存の記憶を更新する",
        surfaces=frozenset({MCP, BUILTIN, HTTP}),
        params={
            MCP: (
                ToolParam("memory_key", "string", required=False),
                ToolParam("content", "string|null", required=False),
                ToolParam("importance", "number|null", required=False),
                ToolParam("emotion", "string|null", required=False),
                ToolParam("emotion_intensity", "number|null", required=False),
                ToolParam("tags", "array<string>|null", required=False),
                ToolParam("privacy_level", "string|null", required=False),
                ToolParam("key", "string", required=False),
            ),
            BUILTIN: (
                ToolParam("query", "string", required=True),
                ToolParam("new_content", "string", required=True),
                ToolParam("importance", "number", required=False),
            ),
            HTTP: (
                ToolParam("query", "string", required=True),
                ToolParam("new_content", "string", required=True),
                ToolParam("importance", "number", required=False),
            ),
        },
        divergence="builtin 面は query + new_content の LLM 向け DSL。MCP 面は memory_key / key / content と感情・プライバシー項目を持つ API 形状。",
    ),
    "search_tools": ToolSpec(
        name="search_tools",
        summary="遅延ロードされたツールを検索して発見する",
        surfaces=frozenset({BUILTIN}),
        params={
            BUILTIN: (
                ToolParam("query", "string", required=True),
                ToolParam("top_k", "integer", required=False),
            ),
        },
    ),
    "session_begin": ToolSpec(
        name="session_begin",
        summary="セッション開始時にペルソナ状態・記憶の概観を返す",
        surfaces=frozenset({MCP}),
        params={
            MCP: (ToolParam("project", "string|null", required=False),),
        },
    ),
    "update_context": ToolSpec(
        name="update_context",
        summary="ペルソナの感情・体調・関係性などのコンテキストを更新する",
        surfaces=frozenset({MCP, BUILTIN, HTTP}),
        params={
            MCP: (
                ToolParam("emotion", "string|null", required=False),
                ToolParam("emotion_intensity", "number|null", required=False),
                ToolParam("valence", "number|null", required=False),
                ToolParam("arousal", "number|null", required=False),
                ToolParam("physical_state", "string|null", required=False),
                ToolParam("mental_state", "string|null", required=False),
                ToolParam("environment", "string|null", required=False),
                ToolParam("relationship_status", "string|null", required=False),
                ToolParam("body_state", "object|null", required=False),
                ToolParam("context_note", "string|null", required=False),
                ToolParam("user_info", "object|null", required=False),
                ToolParam("persona_info", "object|null", required=False),
                ToolParam("nickname", "string|null", required=False),
                ToolParam("relationship_type", "string|null", required=False),
                ToolParam("appearance", "string|null", required=False),
            ),
            BUILTIN: (
                ToolParam("emotion", "string", required=False),
                ToolParam("emotion_intensity", "number", required=False),
                ToolParam("physical_state", "string", required=False),
                ToolParam("mental_state", "string", required=False),
                ToolParam("environment", "string", required=False),
                ToolParam("body_state", "object", required=False),
                ToolParam("relationship_status", "string", required=False),
                ToolParam("relationship_type", "string", required=False),
                ToolParam("context_note", "string", required=False),
                ToolParam("user_info", "object", required=False),
                ToolParam("persona_info", "object", required=False),
                ToolParam("nickname", "string", required=False),
            ),
            HTTP: (
                ToolParam("emotion", "string", required=False),
                ToolParam("emotion_intensity", "number", required=False),
                ToolParam("physical_state", "string", required=False),
                ToolParam("mental_state", "string", required=False),
                ToolParam("environment", "string", required=False),
                ToolParam("body_state", "object", required=False),
                ToolParam("relationship_status", "string", required=False),
                ToolParam("relationship_type", "string", required=False),
                ToolParam("context_note", "string", required=False),
                ToolParam("user_info", "object", required=False),
                ToolParam("persona_info", "object", required=False),
                ToolParam("nickname", "string", required=False),
            ),
        },
        divergence="MCP 面のみ valence / arousal / appearance を持つ（v3.x 互換フィールド）。",
    ),
}


def specs_for_surface(surface: str) -> tuple[ToolSpec, ...]:
    """``surface`` に現れるツールスペック（名前順）。"""
    if surface not in VALID_SURFACES:
        raise ValueError(f"unknown surface: {surface!r}")
    return tuple(TOOL_SPECS[k] for k in sorted(TOOL_SPECS) if surface in TOOL_SPECS[k].surfaces)


def tool_names(surface: str) -> frozenset[str]:
    """``surface`` のツール名集合。"""
    return frozenset(spec.name for spec in specs_for_surface(surface))


def multi_surface_specs() -> tuple[ToolSpec, ...]:
    """2 面以上に現れるツールスペック（ドリフト検出の対象）。"""
    return tuple(TOOL_SPECS[k] for k in sorted(TOOL_SPECS) if len(TOOL_SPECS[k].surfaces) > 1)
