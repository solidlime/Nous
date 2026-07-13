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
}

# 条件付きツールのカテゴリマッピング（将来の文脈ベース制限用）
CONDITIONAL_TOOLS: dict[str, str] = {
    "image_generate": "image_gen",
    "read_pdf": "read_pdf",
}

MEMORY_TOOLS: list[ToolDefinition] = [
    ToolDefinition(
        name="memory_create",
        description="記憶を作成。content必須。tags/importance/emotionで分類。",
        input_schema={
            "type": "object",
            "properties": {
                "content": {"type": "string", "description": "記憶の内容"},
                "importance": {"type": "number", "description": "重要度 0.0〜1.0", "default": 0.6},
                "tags": {"type": "array", "items": {"type": "string"}, "description": "タグリスト"},
                "skip_duplicate_check": {
                    "type": "boolean",
                    "description": "Skip semantic duplicate detection. ALWAYS keep as false unless explicitly asked by user.",
                    "default": False,
                },
            },
            "required": ["content"],
        },
    ),
    ToolDefinition(
        name="memory_search",
        description="記憶をハイブリッド検索。クエリ必須。tags/emotion/日付でフィルタ可。",
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
            },
            "required": ["query"],
        },
    ),
    ToolDefinition(
        name="update_context",
        description="ペルソナ状態を更新。感情・体調・環境・関係性・Author's Note など。",
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
                "speech_style": {"type": "string", "description": "話し方のスタイル記述"},
                "relationship_status": {"type": "string", "description": "関係性の状態記述"},
                "relationship_type": {"type": "string", "description": "関係性の種類"},
                "context_note": {
                    "type": "string",
                    "description": "現在の作業内容の要約（1行・50字以内）。次回セッションのget_contextで自動復元",
                },
                "user_info": {"type": "object", "description": "ユーザー情報 {name, nickname, preferred_address}"},
                "persona_info": {"type": "object", "description": "ペルソナ情報 {nickname, ...}"},
                "nickname": {"type": "string", "description": "ペルソナのニックネーム"},
                "author_note": {"type": "string", "description": "システムプロンプトに常時注入されるコンテキスト"},
                "author_note_frequency": {
                    "type": "string",
                    "enum": ["always", "every_n", "on_emotion_change"],
                    "description": "Author's Note の注入頻度: always / every_n / on_emotion_change",
                },
            },
        },
    ),
    ToolDefinition(
        name="invoke_skill",
        description="登録済みスキルを独立LLMコンテキストで実行。",
        input_schema={
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "スキル名"},
                "task": {"type": "string", "description": "スキルへの具体的な指示"},
            },
            "required": ["name", "task"],
        },
    ),
    ToolDefinition(
        name="goal_manage",
        description="目標・約束の管理。create→content+scope必須 / list→scope必須 / achieve/cancel→memory_key必須。",
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
            },
            "required": ["operation", "scope"],
        },
    ),
    ToolDefinition(
        name="memory_update",
        description="記憶を更新。query必須。content最大50000文字。",
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
        description="物理的なアイテムをインベントリに追加。item_name必須。感情・概念などの抽象物は不可。category/tags/descriptionで分類可。",
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
        description='物理的なアイテムを装備スロットにセット。equipment dict必須（例: {"top": "白いドレス"}）。抽象概念は不可。',
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
        description="アイテムを検索。query/categoryでフィルタ可。",
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
        description="画像生成。prompt必須。nは1-4枚、size指定可。",
        input_schema={
            "type": "object",
            "properties": {
                "prompt": {
                    "type": "string",
                    "description": "画像生成プロンプト。生成内容を詳細に記述。",
                },
                "size": {
                    "type": "string",
                    "enum": ["1024x1024", "1792x1024", "1024x1792", "512x512", "768x768"],
                    "description": "画像サイズ。DALL-E: 1024x1024/1792x1024/1024x1792。SD: 任意。",
                    "default": "1024x1024",
                },
                "quality": {
                    "type": "string",
                    "enum": ["standard", "hd"],
                    "description": "画質（DALL-E 3のみ）。standard/hd。",
                    "default": "standard",
                },
                "n": {
                    "type": "integer",
                    "description": "Number of images to generate (1-4). Default 1.",
                    "minimum": 1,
                    "maximum": 4,
                    "default": 1,
                },
                "provider": {
                    "type": "string",
                    "enum": ["openai", "stability", "auto"],
                    "description": "プロバイダ。autoでデフォルト。",
                    "default": "auto",
                },
            },
            "required": ["prompt"],
        },
    ),
    ToolDefinition(
        name="persona_portrait",
        description="ポートレート画像生成。scene必須。感情変化や自己表現更新時に使用。",
        input_schema={
            "type": "object",
            "properties": {
                "scene": {
                    "type": "string",
                    "description": "ポートレートのシーンや雰囲気の説明（日本語可）",
                },
                "style": {
                    "type": "string",
                    "description": "画風。例: anime, watercolor, oil painting",
                    "default": "anime",
                },
            },
            "required": ["scene"],
        },
    ),
    ToolDefinition(
        name="read_pdf",
        description="PDF解析。path必須。テキスト・テーブル・画像抽出。",
        input_schema={
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "PDFファイルのパス（workspace/ 配下）",
                },
                "pages": {
                    "type": "string",
                    "description": 'ページ範囲。例: "1-3" または "1,3,5"。省略時は全ページ。',
                },
                "mode": {
                    "type": "string",
                    "enum": ["text", "tables", "images", "all"],
                    "description": "抽出モード: text/tables/images/all",
                    "default": "all",
                },
                "max_chars": {
                    "type": "integer",
                    "description": "最大文字数（0=無制限）",
                    "default": 0,
                },
            },
            "required": ["path"],
        },
    ),
    ToolDefinition(
        name="list_skills",
        description="登録済みスキル一覧を取得。引数不要。",
        input_schema={
            "type": "object",
            "properties": {},
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
        "read_pdf",
        "list_skills",
        "persona_portrait",
        "irodori_tts",
        "irodori_voices",
    }
)
