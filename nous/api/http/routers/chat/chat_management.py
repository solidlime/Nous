from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from starlette.responses import HTMLResponse, JSONResponse, Response

from nous.api.http.deps import _PERSONA_PATTERN
from nous.api.http.routers.chat.chat_stream import _resolve_request
from nous.config.settings import get_settings
from nous.domain.config.chat_config import ChatConfig, ChatConfigFileRepository
from nous.infrastructure.logging.structured import get_logger
from nous.infrastructure.persona_layout import persona_media_dir, persona_uploads_dir

if TYPE_CHECKING:
    from starlette.requests import Request

logger = get_logger(__name__)

# その場で描画してよい MIME（許可リスト）。SVG はスクリプトを運べるので含めない。
_INLINE_MIME = frozenset(
    {
        "image/jpeg",
        "image/png",
        "image/gif",
        "image/webp",
        "image/avif",
        "image/bmp",
        "audio/mpeg",
        "audio/wav",
        "video/mp4",
        "application/pdf",
    }
)


# ── pure logic layer (_do_*) ───────────────────────────────────────


async def _do_get_chat_config(persona: str, ctx) -> dict:
    """Return chat config safe dict for persona."""
    repo = ChatConfigFileRepository(get_settings().data_root)
    try:
        config = repo.get(persona)
    except Exception:  # 設定読み込み失敗時のフォールバック
        logger.warning("get_chat_config: repo.get(%r) failed, returning defaults", persona)
        config = ChatConfig(persona=persona)
    return config.to_safe_dict()


# ── config defaults (auto-derived from pydantic models) ───────────
# 「デフォルト値に戻す」ボタン向け。モデルの model_fields から自動取得するため、
# 設定フィールド追加時にバックエンド側の定数メンテは不要。


# 秘匿項目: 値を返さず常に空文字（単一定義は ChatConfig.is_secret_field）。
def _is_secret_field(name: str) -> bool:
    return ChatConfig.is_secret_field(name)


# v4.0 で削除された死にノブ。旧クライアント/旧 config.json が送ってきても
# 値は無視する（_all_flat_fields フィルタで既に落ちる）。保存時に 1 回だけ
# warning を出し、消えたキー名を可視化する。
_REMOVED_CONFIG_KEYS_V4: frozenset[str] = frozenset(
    {
        "forgetting_trigger_threshold",
        "forgetting_forget_ratio",
        "forgetting_forget_strength",
        # 時間減衰ワーカー廃止 (2026-11-08) で落ちたノブ
        "forgetting_enabled",
        "forgetting_decay_interval_seconds",
        "forgetting_min_strength",
        "h5_stability_clamp_enabled",
        # H4 (2026-11-17): 死にノブ（感情ゲイン係数）を削除
        "brain_emotion_gain_k",
        "brain_rif_suppression_rho",
        "reflection_threshold",
        "reflection_enabled",
        "reflection_min_interval_hours",
        "reflection_interval_cycles",
        "memory_enrichment_auto_run",
        "memory_enrichment_interval",
        "memory_enrichment_model",
        "memory_enrichment_prompt_template",
        # enrichment 廃止 (2026-11-08) で落ちたノブ
        "memory_enrichment_enabled",
        "brain_enrich_auto_run",
        "brain_enrich_interval_seconds",
        "brain_enrich_batch_limit",
        "brain_novelty_sim_threshold",
        "brain_novelty_importance_threshold",
        "brain_novelty_stability_multiplier",
        "brain_idle_after_seconds",
        "brain_min_batch_size",
        "brain_max_defer_seconds",
        "brain_spontaneous_enabled",
        "brain_spontaneous_interval_hours",
        "brain_spontaneous_prompt",
        # 自発的内省 / 独り言 (2026-11-09 kanban #35) で落ちたノブ
        "brain_monologue_enabled",
        "brain_introspection_enabled",
        "brain_introspection_prompt",
        # sampling 廃止 + Stage0 削除 (2026-11-22 kanban #144) で落ちたノブ
        "top_p",
        "dynamic_temperature",
        "emotion_temperature_scale",
        "context_keep_recent_turns",
    }
)


# 設定パネルのセクション（sections/chat/*.py の data-category）へ prefix で分類。
# 一致しないフィールドは "core"。追加フィールドも prefix 一致で自然に追従する。
_SECTION_PREFIXES: tuple[tuple[str, str], ...] = (
    ("brain_", "brain_simulation"),
    ("voice_", "voice"),
    ("irodori_", "voice"),
    ("image_", "image"),
    ("memory_", "memory"),
    ("reflection_", "reflection"),
    ("mental_", "mental"),
    ("context_", "context"),
    ("retrieval_", "weights"),
    ("emotion_", "weights"),
    ("proactive_", "proactive"),
)
_SECTION_EXACT: dict[str, str] = {
    "mcp_servers": "tools",
    "disabled_tools": "tools",
    "enabled_skills": "skills",
    "enable_parallel_tools": "tools",
    "dynamic_tool_selection": "tools",
    "enable_memory_tools": "tools",
    "schedule_fail_limit": "tools",
    "workspace_root": "tools",
    "shell_timeout_seconds": "tools",
    "shell_approval_mode": "tools",
    "shell_allowed_commands": "tools",
    "sandbox_enabled": "tools",
    "sandbox_manager_url": "tools",
    "sandbox_image": "tools",
    "sandbox_network": "tools",
    "sandbox_memory": "tools",
    "sandbox_idle_minutes": "tools",
}
# 設定ではないメタフィールドは除外。
_META_FIELD_NAMES = frozenset({"persona", "updated_at"})


def _field_section(name: str) -> str:
    if name in _SECTION_EXACT:
        return _SECTION_EXACT[name]
    for prefix, section in _SECTION_PREFIXES:
        if name.startswith(prefix):
            return section
    return "core"


# ── 3層化 (v4.0): basic / advanced / expert ────────────────────────
# 設定パネル表示階層。_field_section と同じく prefix ではなく明示マップ。
# 取りこぼし（明示マップに無いキー）は危険側 = 非表示側の "expert" に倒す。
_TIER_BASIC: frozenset[str] = frozenset(
    {
        # 音声 ON/OFF・音量・TTS モデル/URL
        "voice_enabled",
        "voice_auto_play",
        "voice_volume",
        "voice_speed",
        "voice_model",
        "voice_url",
        "voice_streaming",
        # 表示系・セッション要約・記憶検索
        "show_message_timestamps",
        "language",
        "session_summarize",
        "episode_search_enabled",
        # メモリ検索重み
        "retrieval_recency_weight",
        "retrieval_importance_weight",
        "retrieval_relevance_weight",
        # 自立活動 ON/OFF（自発発言 #44 + 自発活動 #47 を統合、kanban #152）
        "autonomy_enabled",
    }
)
_TIER_ADVANCED: frozenset[str] = frozenset(
    {
        # LLM プロバイダ/モデル/サンプリング
        "provider",
        "model",
        "reasoning_enabled",
        "reasoning_effort",
        # ペルソナ/表示
        "system_prompt",
        "debug_mode",
        # ツール / スキル / MCP
        "mcp_servers",
        "disabled_tools",
        "enabled_skills",
        "enable_parallel_tools",
        "dynamic_tool_selection",
        "enable_memory_tools",
        # ワークスペース（シェル・ファイル操作）
        "workspace_root",
        "shell_timeout_seconds",
        "shell_approval_mode",
        "shell_allowed_commands",
        # サンドボックス（manager 経由の隔離コンテナ）
        "sandbox_enabled",
        "sandbox_manager_url",
        "sandbox_image",
        "sandbox_network",
        "sandbox_memory",
        "sandbox_idle_minutes",
        # 抽出
        "auto_extract",
        "extract_model",
        "max_tool_calls",
        # 画像生成
        "image_gen_enabled",
        "image_gen_provider",
        "image_gen_presets",
        "image_gen_default_preset",
        "image_gen_negative_prompt",
        "image_gen_self_portrait_prompt",
        "image_gen_full_body_prefix",
        "image_gen_portrait_prefix",
        "image_gen_selfie_prefix",
        "image_gen_scene_prefix",
        # メンタルモデル
        "mental_model_enabled",
        # brain 系主要 ON/OFF
        "brain_graph_flash_enabled",
        "brain_reasoning_enabled",
        "brain_llm_dedicated",
        # Jev 型判定ゲート / multi-hop 検索 (#011)
        "brain_decision_enabled",
        "brain_decision_model",
        "brain_decision_threshold",
        "brain_decision_max_hops",
        "brain_decision_time_weight",
        # 音声感情モード / アイテム抽出専用 LLM / 圧縮モード
        "voice_emotion_mode",
        "item_llm_dedicated",
        "item_llm_provider",
        "item_llm_model",
        "context_compression_mode",
        "context_use_llm_summary",
        # 想起スコア閾値（誤爆した低スコア記憶を注入しない）
        "memory_min_score",
        # 自発発言の間隔・クールダウン・追加指示
        "proactive_idle_minutes",
        "proactive_interval_minutes",
        "proactive_cooldown_minutes",
        "proactive_prompt",
    }
)


def _field_tier(name: str) -> str:
    """basic / advanced / expert の表示階層を返す（fallback は expert）。"""
    if name in _TIER_BASIC:
        return "basic"
    if name in _TIER_ADVANCED:
        return "advanced"
    return "expert"


def _type_label(annotation: object) -> str:
    """Optional/Union/generics を JS 側で扱いやすい素の型名にする。"""
    import types as _types
    import typing as _typing

    origin = _typing.get_origin(annotation)
    if origin is _types.UnionType or origin is _typing.Union:
        for arg in _typing.get_args(annotation):
            if arg is not type(None):
                return _type_label(arg)
        return "none"
    if origin is list:
        return "list"
    if origin is dict:
        return "dict"
    return getattr(annotation, "__name__", "str")


def _do_get_config_defaults() -> dict:
    """ChatConfig（サブ設定含む）のフラット全フィールドのデフォルトを返す。"""
    fields: dict[str, dict] = {}
    for name, info in ChatConfig._all_flat_fields().items():
        if name in _META_FIELD_NAMES:
            continue
        # default_factory のフィールドは default が PydanticUndefined で JSON 化できない
        default = "" if _is_secret_field(name) else info.get_default(call_default_factory=True)
        fields[name] = {
            "default": default,
            "help": info.description or "",
            "type": _type_label(info.annotation),
            "section": _field_section(name),
            "tier": _field_tier(name),
        }
    return {"fields": fields}


def _preserve_masked_mcp_headers(incoming_servers: Any, existing_servers: list[dict]) -> Any:
    """Restore masked ``****`` header values in ``mcp_servers`` from *existing_servers* by name or url."""
    if not isinstance(incoming_servers, list):
        return incoming_servers
    by_name: dict[str, dict[str, Any]] = {}
    by_url: dict[str, dict[str, Any]] = {}
    for s in existing_servers:
        if not isinstance(s, dict) or not isinstance(s.get("headers"), dict):
            continue
        low = {str(k).lower(): v for k, v in s["headers"].items()}
        if s.get("name"):
            by_name[str(s["name"])] = low
        if s.get("url"):
            by_url[str(s["url"])] = low
    out: list[Any] = []
    for srv in incoming_servers:
        if not isinstance(srv, dict) or not isinstance(srv.get("headers"), dict):
            out.append(srv)
            continue
        sname = str(srv.get("name"))
        prev_headers = by_name[sname] if sname in by_name else by_url.get(str(srv.get("url") or ""))
        if not prev_headers:
            if any(isinstance(v, str) and v.endswith("****") for v in srv["headers"].values()):
                logger.warning(
                    "mcp_servers: masked header for %r cannot be restored; token would be lost", srv.get("name")
                )
            out.append(srv)
            continue
        merged_headers = dict(srv["headers"])
        for hk, hv in list(merged_headers.items()):
            if isinstance(hv, str) and hv.endswith("****") and str(hk).lower() in prev_headers:
                merged_headers[hk] = prev_headers[str(hk).lower()]
        srv_copy = dict(srv)
        srv_copy["headers"] = merged_headers
        out.append(srv_copy)
    return out


async def _do_save_chat_config(persona: str, ctx, body: dict) -> dict:
    """Save and return updated chat config safe dict."""
    # v4.0: 削除済みキーは無視する。送られてきた場合のみ 1 リクエスト 1 回 warning。
    removed_present = sorted(k for k in body if k in _REMOVED_CONFIG_KEYS_V4)
    if removed_present:
        logger.warning(
            "save_chat_config: ignoring removed v4 config keys: %s",
            ", ".join(removed_present),
        )

    repo = ChatConfigFileRepository(get_settings().data_root)
    current = repo.get(persona)

    update_data = current.model_dump()
    for field_name in ChatConfig._all_flat_fields():
        if field_name in ("persona", "updated_at") or field_name not in body:
            continue
        raw_val = body[field_name]
        if _is_secret_field(field_name):
            # マスク済み値 ("sk-x****") は既存キーの据え置きを意味するためスキップ。
            # 空文字 "" や None はユーザーの「クリア（環境変数フォールバックへ戻す）」意図を反映する:
            # ProviderConfig.api_key は None で env へフォールバックし、他の *_api_key (str) は "" でフォールバックする。
            if raw_val is not None and str(raw_val).endswith("****"):
                continue
            if not raw_val:
                update_data[field_name] = None if field_name == "api_key" else ""
            else:
                update_data[field_name] = raw_val
            continue
        if field_name == "mcp_servers":
            raw_val = _preserve_masked_mcp_headers(raw_val, current.mcp_servers)
        update_data[field_name] = raw_val

    new_config = ChatConfig(**update_data)
    repo.save(new_config)
    return new_config.to_safe_dict()


async def _do_list_mcp_tools(persona: str, ctx) -> dict:
    """Return MCP tools and errors."""
    repo = ChatConfigFileRepository(get_settings().data_root)
    config = repo.get(persona)

    if not config.mcp_servers:
        return {"tools": [], "errors": []}

    from nous.infrastructure.mcp_client.pool import MCPClientPool

    tools_out: list[dict] = []
    errors_out: list[str] = []
    try:
        async with MCPClientPool(config.mcp_servers) as pool:
            for tool in pool.list_all_tools():
                desc = tool.description or ""
                server_name = ""
                if desc.startswith("[") and "]" in desc:
                    server_name = desc[1 : desc.index("]")]
                    desc = desc[desc.index("]") + 1 :].strip()
                tools_out.append(
                    {
                        "name": tool.name,
                        "description": desc,
                        "server": server_name,
                    }
                )
    except Exception as e:  # MCPプール接続失敗は非致命的
        logger.warning("get_chat_tools: tool retrieval failed: %s", e)
        errors_out.append(str(e))

    return {"tools": tools_out, "errors": errors_out}


def _iso_or_raw(value):
    """datetime を ISO 文字列化する（JSON シリアライズ対策）。他型はそのまま。"""
    return value.isoformat() if hasattr(value, "isoformat") else value


async def _do_get_commitments(persona: str, ctx) -> dict:
    """Return latest reflection insights."""
    insights: list[dict] = []

    try:
        reflection_result = ctx.memory_service.get_by_tags(["reflection"])
        if reflection_result.is_ok and reflection_result.value:
            sorted_refs = sorted(
                reflection_result.value,
                key=lambda m: getattr(m, "created_at", None) or "",
                reverse=True,
            )
            # メタ付きオブジェクト: パネルの詳細モーダルが本文＋メタを
            # 表示できるよう key / created_at を同梱（旧文字列形式の
            # 消費者には content プロパティで後方互換なし — 呼び出し元は
            # chat-core.js のみで、フロント側は両形式に対応済み）。
            insights = [
                {
                    "content": m.content,
                    "key": m.key,
                    # datetime は JSON シリアライズ不可のため ISO 文字列化
                    "created_at": _iso_or_raw(getattr(m, "created_at", None)),
                }
                for m in sorted_refs[:5]
            ]
    except Exception as e:  # insights の取得失敗は非致命的
        logger.warning("get_chat_commitments: insights failed: %s", e)

    return {"insights": insights}


async def _do_execute_chat_tool(persona: str, ctx, body: dict) -> dict:
    """Execute a builtin memory tool and return result dict."""
    from nous.application.chat.tools.builtin import execute_tool

    repo = ChatConfigFileRepository(get_settings().data_root)
    config = repo.get(persona)
    ctx.search_engine.set_persona(persona)

    tool_name = body.get("tool", "")
    tool_input = body.get("input", {})

    result = await execute_tool(ctx, config, tool_name, tool_input)
    if isinstance(result, dict) and "status" in result:
        return result
    return {
        "status": "ok" if result else "error",
        "key": result.get("memory_key", "") if isinstance(result, dict) else "",
        "message": str(result) if not isinstance(result, dict) else result.get("response", ""),
    }


async def _do_attachment_upload(persona: str, ctx, filename: str, file_bytes: bytes) -> dict:
    """Save uploaded file to host FS and return metadata dict."""
    import mimetypes
    import os
    from pathlib import Path

    settings = get_settings()
    uploads_dir = Path(persona_uploads_dir(settings.data_root, persona))
    uploads_dir.mkdir(parents=True, exist_ok=True)

    safe_name = os.path.basename(filename).replace("..", "").strip()
    if not safe_name:
        safe_name = "upload"

    dest = uploads_dir / safe_name
    counter = 0
    stem = dest.stem
    suffix = dest.suffix
    while dest.exists() or dest.is_symlink():
        counter += 1
        dest = uploads_dir / f"{stem}_{counter}{suffix}"
    safe_name = dest.name

    dest.write_bytes(file_bytes)

    mime_type, _ = mimetypes.guess_type(safe_name)
    mime_type = mime_type or "application/octet-stream"
    size = dest.stat().st_size

    return {
        "filename": safe_name,
        "url": f"/api/chat/{persona}/attachment/{safe_name}",
        # sandbox からは /root/uploads に見える（/mnt/nous/uploads への symlink）。
        "workspace_path": f"/root/uploads/{safe_name}",
        "mime_type": mime_type,
        "size": size,
    }


async def _do_attachment_serve(persona: str, ctx, filename: str) -> dict | None:
    """Resolve file path and mime type for an uploaded attachment. Returns None if not found."""
    import mimetypes
    from pathlib import Path

    settings = get_settings()
    file_path = Path(persona_uploads_dir(settings.data_root, persona)) / filename
    if not file_path.exists():
        return None

    mime_type, _ = mimetypes.guess_type(filename)
    mime_type = mime_type or "application/octet-stream"
    return {"file_path": str(file_path), "mime_type": mime_type}


async def _do_memory_image_serve(persona: str, ctx, filename: str) -> dict | None:
    """Resolve file path and mime type for a memory image. Returns None if not found."""
    import mimetypes
    from pathlib import Path

    settings = get_settings()
    file_path = Path(persona_media_dir(settings.data_root, persona)) / "images" / filename
    if not file_path.exists():
        return None

    mime_type, _ = mimetypes.guess_type(filename)
    mime_type = mime_type or "image/png"
    return {"file_path": str(file_path), "mime_type": mime_type}


# ── HTTP adapter layer ─────────────────────────────────────────────


async def get_chat_config(request: Request) -> JSONResponse:
    """GET /api/chat/{persona}/config — return chat configuration."""
    persona, ctx = _resolve_request(request)
    if not ctx:
        return JSONResponse({"error": "Persona not found"}, status_code=404)
    return JSONResponse(await _do_get_chat_config(persona, ctx))


async def get_config_defaults(request: Request) -> JSONResponse:
    """GET /api/chat/{persona}/config/defaults — auto-derived field defaults."""
    persona, ctx = _resolve_request(request)
    if not ctx:
        return JSONResponse({"error": "Persona not found"}, status_code=404)
    return JSONResponse(_do_get_config_defaults())


async def save_chat_config(request: Request) -> JSONResponse:
    """POST /api/chat/{persona}/config — update chat configuration."""
    persona, ctx = _resolve_request(request)
    if not ctx:
        return JSONResponse({"error": "Persona not found"}, status_code=404)
    try:
        body = await request.json()
    except (json.JSONDecodeError, TypeError):
        return JSONResponse({"error": "Invalid JSON body"}, status_code=400)
    if not isinstance(body, dict):
        return JSONResponse({"error": "Body must be a JSON object"}, status_code=400)
    try:
        result = await _do_save_chat_config(persona, ctx, body)
    except Exception:  # 最終防衛線: Pydantic/domain validation
        logger.exception("save_chat_config: config validation failed")
        return JSONResponse({"error": "Invalid config"}, status_code=400)
    # Re-resolve the brain LLM so brain_llm_* toggles apply immediately (B1).
    try:
        ctx.reload_brain_llm()
    except Exception:
        logger.debug("save_chat_config: reload_brain_llm failed", exc_info=True)
    # 複数 WebUI クライアントの設定同期（E3）。publish 失敗は保存に影響させない。
    try:
        await ctx.event_bus.publish("config.updated", {"persona": persona})
    except Exception:
        logger.debug("save_chat_config: config.updated publish failed", exc_info=True)
    return JSONResponse(result)


async def list_mcp_tools(request: Request) -> JSONResponse:
    """GET /api/chat/{persona}/mcp-tools — return MCP tools list."""
    persona, ctx = _resolve_request(request)
    if not ctx:
        return JSONResponse({"error": "Persona not found"}, status_code=404)
    return JSONResponse(await _do_list_mcp_tools(persona, ctx))


async def get_chat_layout(request: Request) -> HTMLResponse:
    """GET /api/chat/{persona}/layout — chat tab inner markup for lazy first visit.

    Returns the inner only (memory panel + main + sidebar, no wrapper, no
    asset tags): chat.chunk.js injects it into the SSR'd empty #chat-layout
    BEFORE loading any chat script, so script-time bindings find their DOM
    (innerHTML would neither execute <script> nor apply <link>). The shell
    (wrapper + tab-head) is server-rendered by dashboard.py.
    """
    from nous.api.http.sections.chat import render_chat_inner

    persona, ctx = _resolve_request(request)
    if not ctx:
        return HTMLResponse("<div>Persona not found</div>", status_code=404)
    return HTMLResponse(render_chat_inner(persona))


async def get_chat_commitments(request: Request) -> JSONResponse:
    """GET /api/chat/{persona}/commitments — return latest reflection insights."""
    persona, ctx = _resolve_request(request)
    if not ctx:
        return JSONResponse({"error": "Persona not found"}, status_code=404)
    return JSONResponse(
        await _do_get_commitments(persona, ctx), headers={"Content-Type": "application/json; charset=utf-8"}
    )


async def attachment_upload(request: Request) -> JSONResponse:
    """POST /api/chat/{persona}/attachment/upload — upload file attachment."""
    from starlette.datastructures import UploadFile  # noqa: TC002

    persona, ctx = _resolve_request(request)
    if not ctx:
        return JSONResponse({"error": "Persona not found"}, status_code=404)

    form = await request.form()
    upload = form.get("file")
    if not isinstance(upload, UploadFile) or not upload:
        return JSONResponse({"error": "file field required"}, status_code=400)

    repo = ChatConfigFileRepository(get_settings().data_root)
    try:
        config = repo.get(persona)
    except Exception:
        config = ChatConfig(persona=persona)
    limit = config.max_attachment_bytes

    filename = upload.filename or "upload"
    file_bytes = await _read_limited(upload, limit)
    if file_bytes is None:
        return JSONResponse({"error": f"file too large (max {limit // (1024 * 1024)} MB)"}, status_code=413)
    return JSONResponse(await _do_attachment_upload(persona, ctx, filename, file_bytes))


async def _read_limited(upload, limit: int) -> bytes | None:
    """上限を超えたら None を返す。

    ``await upload.read()`` は全量を一度にヒープへ載せるので、数十 GB の
    1 リクエストでプロセスが落ちる（kanban #76）。インライン上限を先に見て、
    無い場合は 1MB ずつ読んで超過した時点で捨てる。
    """
    size = getattr(upload, "size", None)
    if size is not None and size > limit:
        return None
    buf = bytearray()
    while chunk := await upload.read(1024 * 1024):
        buf.extend(chunk)
        if len(buf) > limit:
            return None
    return bytes(buf)


async def attachment_serve(request: Request) -> Response:
    """GET /api/chat/{persona}/attachment/{filename} — serve uploaded file.

    エージェントも uploads に書ける（attach_file）ため、HTML 等を**そのまま描画させない**。
    表示するのは画像・音声・動画・PDF だけで、それ以外は attachment にする。
    """
    import os
    from urllib.parse import quote

    from starlette.responses import FileResponse

    persona, ctx = _resolve_request(request)
    if not ctx or not _PERSONA_PATTERN.match(persona):
        return JSONResponse({"error": "Persona not found"}, status_code=404)

    filename = request.path_params.get("filename", "")
    safe_name = os.path.basename(filename).replace("..", "").strip()
    if not safe_name:
        return JSONResponse({"error": "Invalid filename"}, status_code=400)

    result = await _do_attachment_serve(persona, ctx, safe_name)
    if result is None:
        return JSONResponse({"error": "File not found"}, status_code=404)

    # nosniff は middleware（nous/api/http/middleware.py）が全レスポンスに付ける
    headers: dict[str, str] = {}
    if result["mime_type"] not in _INLINE_MIME:
        headers["Content-Disposition"] = f"attachment; filename*=UTF-8''{quote(safe_name)}"
    return FileResponse(result["file_path"], media_type=result["mime_type"], headers=headers)


async def memory_image_serve(request: Request) -> Response:
    """GET /api/chat/{persona}/persona/images/{filename} — serve generated image."""
    import os

    from starlette.responses import FileResponse

    persona, ctx = _resolve_request(request)
    if not ctx or not _PERSONA_PATTERN.match(persona):
        return JSONResponse({"error": "Persona not found"}, status_code=404)

    filename = request.path_params.get("filename", "")
    safe_name = os.path.basename(filename).replace("..", "").strip()
    if not safe_name or not safe_name.lower().endswith(".png"):
        return JSONResponse({"error": "Invalid filename"}, status_code=400)

    result = await _do_memory_image_serve(persona, ctx, safe_name)
    if result is None:
        return JSONResponse({"error": "File not found"}, status_code=404)

    return FileResponse(result["file_path"], media_type=result["mime_type"])


async def execute_chat_tool(request: Request) -> JSONResponse:
    """POST /api/chat/{persona}/tool — execute a builtin memory tool."""
    persona, ctx = _resolve_request(request)
    if not ctx:
        return JSONResponse({"error": "Persona not found"}, status_code=404)

    try:
        body = await request.json()
    except (ValueError, TypeError):  # 不正 JSON・不正 UTF-8 も 400 で返す（#89）
        return JSONResponse({"error": "Invalid JSON body"}, status_code=400)
    if not isinstance(body, dict):
        # JSON として妥当でも object でなければ body.get が落ちる（#89 review）
        return JSONResponse({"error": "Invalid JSON body"}, status_code=400)
    tool_name = body.get("tool", "")
    if not tool_name:
        return JSONResponse({"status": "error", "message": "tool name required"}, status_code=400)

    try:
        result = await _do_execute_chat_tool(persona, ctx, body)
        return JSONResponse(result)
    except Exception:  # 最終防衛線
        logger.exception("execute_chat_tool: tool execution failed")
        return JSONResponse({"status": "error", "message": "Tool execution failed"}, status_code=500)
