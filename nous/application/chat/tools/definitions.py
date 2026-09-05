"""MEMORY_TOOLS: チャット組み込みツール定義 + 選択的ツール登録。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from nous.infrastructure.llm.base import ToolDefinition
from nous.infrastructure.logging.structured import get_logger

if TYPE_CHECKING:
    from nous.domain.chat_config import ChatConfig

logger = get_logger(__name__)

# 絶対にフィルタリングされないコアツール（Nous のアイデンティティ）
CORE_ALWAYS_TOOLS: set[str] = {
    "memory_search",
    "memory_create",
    "memory_update",
    "update_context",
    "invoke_skill",
    "goal_manage",
    # item_* 系 — ペルソナ表現に必須
    "item_add",
    "item_equip",
    "item_search",
    # ツール発見 — LLM が deferred ツールを検索するために常時必要
    "search_tools",
}

MEMORY_TOOLS: list[ToolDefinition] = [
    ToolDefinition(
        name="memory_create",
        description="永続的な記憶を作成する。ユーザーが重要な個人情報・好み・決定・約束を共有したら使え。同じ内容の記憶が既にあれば使うな。既存の記憶の修正には memory_update を使え。content（記憶本文）は必須。tags/importance/emotion で分類を補強できる。",
        input_schema={
            "type": "object",
            "properties": {
                "content": {"type": "string", "description": "記憶の内容"},
                "importance": {"type": "number", "description": "重要度 0.0〜1.0", "default": 0.6},
                "tags": {"type": "array", "items": {"type": "string"}, "description": "タグリスト"},
                "skip_duplicate_check": {
                    "type": "boolean",
                    "description": "重複チェックをスキップする（デフォルト: True。応答を速くするため）。重複防止が必要な場合は false を明示的に指定。",
                    "default": True,
                },
            },
            "required": ["content"],
        },
    ),
    ToolDefinition(
        name="memory_search",
        description="永続記憶ストアをハイブリッド検索（意味検索+キーワード検索）する。過去の会話やユーザー設定を思い出す必要がある時に使え。現在の会話で既出の情報を検索するな。query は必須。tags/emotion/date_range で結果を絞り込める。",
        input_schema={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "検索クエリ"},
                "top_k": {"type": "integer", "description": "取得件数（1〜200）", "default": 5},
                "tags": {"type": "array", "items": {"type": "string"}, "description": "タグでフィルタ"},
                "date_range": {"type": "string", "description": "日付範囲: 7d, 30d, 昨日, 今日"},
                "min_importance": {"type": "number", "description": "最小重要度 0.0-1.0"},
                "emotion": {"type": "string", "description": "感情でフィルタ（happy/sad/angry 等）"},
                "vector_weight": {
                    "type": "number",
                    "description": "RRFベクトル検索の重み（0.0-1.0）",
                    "default": 1.0,
                    "minimum": 0,
                    "maximum": 1.0,
                },
                "keyword_weight": {
                    "type": "number",
                    "description": "RRFキーワード検索の重み（0.0-1.0）",
                    "default": 0.5,
                    "minimum": 0,
                    "maximum": 1.0,
                },
                "sort": {"type": "string", "description": "並び順: updated_at で更新日時降順（最新優先）"},
            },
            "required": ["query"],
        },
    ),
    ToolDefinition(
        name="update_context",
        description="ペルソナの状態（感情・体調・環境・関係性・コンテキストノート）を更新する。会話中にペルソナの内外状態が意味のある変化をした時に使え。変化がないのに更新するな。自明な微細変動は無視せよ。emotion, physical_state, environment, relationship_status, context_note など任意のフィールドを指定可能。",
        input_schema={
            "type": "object",
            "properties": {
                "emotion": {"type": "string", "description": "感情タイプ (joy/curiosity/sadness/anger/trust 等)"},
                "emotion_intensity": {"type": "number", "description": "感情強度 0.0〜1.0"},
                "physical_state": {"type": "string", "description": "身体状態の自由記述"},
                "mental_state": {"type": "string", "description": "精神状態の自由記述"},
                "environment": {"type": "string", "description": "現在の環境・場所"},
                "body_state": {
                    "type": "object",
                    "description": "身体数値 {fatigue, warmth, arousal, heart_rate, pain} — 各0.0-1.0",
                    "properties": {
                        "fatigue": {"type": "number"},
                        "warmth": {"type": "number"},
                        "arousal": {"type": "number"},
                        "heart_rate": {"type": "number"},
                        "pain": {"type": "number"},
                    },
                },
                "relationship_status": {"type": "string", "description": "関係性の状態記述"},
                "relationship_type": {"type": "string", "description": "関係性の種類"},
                "context_note": {
                    "type": "string",
                    "description": "現在の作業内容の要約（1行・50字以内）。次回セッションのget_contextで自動復元",
                },
                "user_info": {"type": "object", "description": "ユーザー情報 {name, nickname, preferred_address}"},
                "persona_info": {"type": "object", "description": "ペルソナ情報 {nickname, ...}"},
                "nickname": {"type": "string", "description": "ペルソナのニックネーム"},
            },
        },
    ),
    ToolDefinition(
        name="invoke_skill",
        description="有効なスキルの完全な指示を取得する。会話の状況がスキルの発動条件に合致したと判断したら、ユーザーの指示を待たず自律的に呼び出せ。発動条件に合致しないスキルを推測で呼ぶな。同じスキルを同一ターンで重複呼び出しするな。name（スキル名）が必須。task パラメータに呼び出し理由を簡潔に記述できる。",
        input_schema={
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "スキル名"},
                "task": {
                    "type": "string",
                    "description": "スキルを呼び出す理由（任意。スキル内容を読み返す目的を簡潔に）",
                },
            },
            "required": ["name"],
        },
    ),
    ToolDefinition(
        name="goal_manage",
        description="目標・約束を管理する（作成・一覧・達成・取消）。ユーザーが目標を設定・確認・完了・破棄する時に使え。一時的な雑談や軽い意向には使うな。operation（create/list/achieve/cancel）と scope（self/interpersonal）が必須。create 時は content 必須、achieve/cancel 時は memory_key で対象を指定できる。tags は create 時は goal/active に加えて付与、list/achieve/cancel 時は絞り込みに使用する。",
        input_schema={
            "type": "object",
            "properties": {
                "operation": {
                    "type": "string",
                    "enum": ["create", "list", "achieve", "cancel"],
                    "description": "操作種別",
                },
                "content": {"type": "string", "description": "内容（create時に必須）"},
                "importance": {"type": "number", "description": "重要度 0.0〜1.0", "default": 0.75},
                "scope": {
                    "type": "string",
                    "enum": ["self", "interpersonal"],
                    "description": "目標種別",
                    "default": "self",
                },
                "memory_key": {
                    "type": "string",
                    "description": "memory_key（achieve/cancel時に直接指定可能）",
                },
                "tags": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "追加タグ（例: project:nous）。create 時は goal/active に加えて付与、list/achieve/cancel 時は絞り込みに使用",
                },
            },
            "required": ["operation", "scope"],
        },
    ),
    ToolDefinition(
        name="memory_update",
        description="既存の記憶を新しい内容で上書き更新する。ユーザーが以前の情報を訂正・更新した時に使え。新規の記憶作成には memory_create を使え。memory_update を不必要に呼ぶな。query（検索用）と new_content（新しい内容）が必須。",
        input_schema={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "更新したい記憶を検索するクエリ"},
                "new_content": {"type": "string", "description": "新しい内容"},
                "importance": {"type": "number", "description": "新しい重要度（省略可）"},
            },
            "required": ["query", "new_content"],
        },
    ),
    ToolDefinition(
        name="item_add",
        defer_loading=False,
        description="物理的なアイテムをペルソナのインベントリに追加する。ペルソナが有形の物体を取得・受領した時に使え。感情・概念・情報などの抽象物を追加するな。item_name が必須。category/tags/description/quantity で分類・補足できる。",
        input_schema={
            "type": "object",
            "properties": {
                "item_name": {"type": "string", "description": "アイテム名"},
                "category": {"type": "string", "description": "カテゴリ（top/outer/bottom/accessory/etc）"},
                "description": {"type": "string", "description": "アイテムの説明"},
                "quantity": {"type": "integer", "description": "数量", "default": 1},
                "tags": {"type": "array", "items": {"type": "string"}, "description": "タグ"},
            },
            "required": ["item_name"],
        },
    ),
    ToolDefinition(
        name="item_equip",
        defer_loading=False,
        description="インベントリ内のアイテムを装備スロットにセットする。ペルソナが服を着る・アクセサリを付ける・武器を持つ時に使え。抽象的な概念や非物理的な状態を装備するな。equipment が必須（{slot: item_name} 形式）。auto_add=true で未登録アイテムの自動追加が可能。",
        input_schema={
            "type": "object",
            "properties": {
                "equipment": {"type": "object", "description": "装備するアイテム {slot: item_name}"},
                "auto_add": {"type": "boolean", "description": "未登録アイテムを自動追加", "default": True},
            },
            "required": ["equipment"],
        },
    ),
    ToolDefinition(
        name="item_search",
        defer_loading=False,
        description="ペルソナのインベントリを検索する。所持品の確認や装備可能なアイテムを探す時に使え。外部の物や他者の所持品は検索できない。query（部分一致）や category で結果を絞り込める。",
        input_schema={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "検索クエリ（部分一致）"},
                "category": {"type": "string", "description": "カテゴリでフィルタ"},
            },
        },
    ),
    ToolDefinition(
        name="image_generate",
        defer_loading=False,
        description="AI画像を生成する。ユーザーが画像を要求した時は必ず使い、視覚表現が会話を強化する場面では許可なしに自律的に使ってよい（image-gen スキルの発動条件に従う）。会話の文脈に沿う画像なら積極的に生成せよ。prompt は必須（英語の自然言語で状況・感情・シーンを記述。Danbooru タグとの併用も可）。n で枚数（1-4）、preset で解像度プリセット、mode で構図を指定できる。",
        input_schema={
            "type": "object",
            "properties": {
                "prompt": {
                    "type": "string",
                    "description": "画像生成プロンプト。英語の自然言語で記述（例: 'a girl standing under a blue sky, smiling softly'）。キャラ外見タグ（例: '1girl, purple eyes, white hair'）を先頭に併記してもよい",
                },
                "preset": {
                    "type": "string",
                    "enum": [
                        "portrait_large",
                        "portrait_medium",
                        "portrait_small",
                        "landscape_large",
                        "landscape_medium",
                        "landscape_small",
                        "square_large",
                        "square_medium",
                        "square_small",
                    ],
                    "description": "解像度プリセット。portrait=縦長, landscape=横長, square=正方形。large/medium/small でサイズ選択。省略時は設定のデフォルトプリセットを使用。",
                },
                "n": {
                    "type": "integer",
                    "description": "Number of images to generate (1-4). Default 1.",
                    "minimum": 1,
                    "maximum": 4,
                    "default": 1,
                },
                "self_portrait": {
                    "type": "boolean",
                    "description": "自分自身の画像を生成する場合はtrue。外部の画像や風景など、自分自身でない画像はfalse。",
                },
                "mode": {
                    "type": "string",
                    "enum": ["full_body", "portrait", "selfie", "scene"],
                    "description": "構図モード。full_body=全身, portrait=胸から上, selfie=自撮り風, scene=環境込み。self_portrait=trueのときのみ有効。",
                },
            },
            "required": ["prompt"],
        },
    ),
    ToolDefinition(
        name="list_skills",
        defer_loading=False,
        description="登録済みスキルの一覧を取得する。利用可能なスキルを把握したい時に使え。スキルの発動自体には invoke_skill を使うこと。引数不要。",
        input_schema={
            "type": "object",
            "properties": {},
        },
    ),
    ToolDefinition(
        name="search_tools",
        defer_loading=False,
        description=(
            "必要な機能のツール名がわからない時、または一覧にない機能が必要な時に使え。"
            "明らかに存在しない機能を推測で検索するな。クエリに関連するツールがなければ「見つからない」と報告せよ。"
            "query（検索したい機能の説明）が必須。top_k で取得件数を指定できる。"
        ),
        input_schema={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "検索したい機能の説明（例: アイテム管理、画像生成、記憶の検索）",
                },
                "top_k": {"type": "integer", "description": "取得件数", "default": 5},
            },
            "required": ["query"],
        },
    ),
]


def get_filtered_tools(config: ChatConfig) -> list[ToolDefinition]:
    """コアツール + 条件次第で条件付きツールを返す。

    この関数が CORE_ALWAYS_TOOLS を絶対に除外しないことを保証する。
    dynamic_tool_selection=False の場合は従来通り全ツールを返す。
    disabled_tools に指定されたツールは除外する（コアツールも対象）。
    """
    disabled = set(config.disabled_tools or [])

    if not config.dynamic_tool_selection:
        return [t for t in MEMORY_TOOLS if t.name not in disabled]

    # 常時ツールを収集
    always_tools = [t for t in MEMORY_TOOLS if t.name in CORE_ALWAYS_TOOLS]

    # 条件付きツール（dynamic_tool_selection=True なら全追加 = 現状同じ）
    conditional_tools = [t for t in MEMORY_TOOLS if t.name not in CORE_ALWAYS_TOOLS]

    result = always_tools + conditional_tools
    # disabled_tools でフィルタリング
    if disabled:
        result = [t for t in result if t.name not in disabled]
    # image_gen_enabled に基づいて image_generate をフィルタリング
    if not getattr(config, "image_gen_enabled", False):
        result = [t for t in result if t.name != "image_generate"]
    logger.debug(
        "Tools: %d always + %d conditional = %d total (disabled: %d)",
        len(always_tools),
        len(conditional_tools),
        len(result),
        len(disabled),
    )
    return result


# MCPサーバー由来のツール名（MEMORY_TOOLS と重複するため除外対象）
_NOUS_TOOL_NAMES: frozenset[str] = frozenset(
    {
        # MCP flat tools that overlap with builtin
        "memory_create",
        "memory_read",
        "memory_update",
        "memory_delete",
        "memory_search",
        "memory_stats",
        "get_context",
        "update_context",
        "item_add",
        "item_equip",
        "item_search",
        "goal_manage",
        "invoke_skill",
        "image_generate",
        "list_skills",
        "search_tools",
    }
)
