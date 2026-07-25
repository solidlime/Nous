from __future__ import annotations

import shutil
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from starlette.responses import HTMLResponse, JSONResponse, Response

from nous.api.http.deps import (
    _PERSONA_PATTERN,
    _memory_to_dict,
    _resolve_persona_from_request,
    _safe_get_context,
)
from nous.application.use_cases import AppContextRegistry
from nous.config.settings import Settings, get_settings
from nous.infrastructure.logging.structured import get_logger

if TYPE_CHECKING:
    from starlette.requests import Request

    from nous.domain.persona.entities import PersonaState

logger = get_logger(__name__)


# ── helpers ──────────────────────────────────────────────────────────────


def _resolve_request(request: Request):
    """Return (persona, ctx) or (persona, None)."""
    persona = _resolve_persona_from_request(request)
    ctx = _safe_get_context(persona)
    return persona, ctx


# ── pure logic layer (_do_*) — Request非依存、単体テスト可能 ───────────────


async def _do_health() -> dict:
    """Return health check dict."""
    from nous import __version__  # noqa: PLC0415  — avoids circular import

    try:
        from qdrant_client import QdrantClient

        settings = Settings()
        client = QdrantClient(url=settings.qdrant.url, api_key=settings.qdrant.api_key)
        client.get_collections()
        qdrant_ok = True
        client.close()
    except Exception:
        qdrant_ok = False

    return {
        "status": "ok",
        "version": __version__,
        "qdrant": "connected" if qdrant_ok else "unavailable",
    }


async def _do_list_personas() -> list:
    """Return sorted list of persona names (those with memory.sqlite)."""
    settings = Settings()
    data_path = Path(settings.persona_dir)
    if data_path.exists():
        return sorted([d.name for d in data_path.iterdir() if d.is_dir() and (d / "memory.sqlite").exists()])
    return []


async def _do_dashboard_page(persona: str | None = None) -> str:
    """Return rendered dashboard HTML for persona, or setup page if no personas exist."""
    if persona is None:
        settings = Settings()
        data_path = Path(settings.persona_dir)
        persona_count = 0
        if data_path.exists():
            persona_count = len([d for d in data_path.iterdir() if d.is_dir() and (d / "memory.sqlite").exists()])
        if persona_count == 0:
            return _render_setup_page()

    from nous.api.http.dashboard import render_dashboard

    return render_dashboard(persona)


async def _do_dashboard_data(persona: str, ctx) -> dict:
    """Return dashboard data dict for persona."""
    stats_result = ctx.memory_service.get_stats()
    stats = stats_result.value if stats_result.is_ok else {}

    context_result = ctx.persona_service.get_context(persona)
    context = asdict(context_result.value) if context_result.is_ok else {}
    for _dt_key in ("last_conversation_time", "last_state_update"):
        if _dt_key in context and context[_dt_key] is not None:
            context[_dt_key] = context[_dt_key].isoformat()

    for _f in (
        "environment",
        "fatigue",
        "warmth",
        "arousal",
        "heart_rate",
        "pain",
    ):
        stats[_f] = context.get(_f)

    recent_result = ctx.memory_service.get_recent(limit=5)
    recent = [_memory_to_dict(m) for m in recent_result.value] if recent_result.is_ok else []

    blocks_result = ctx.memory_service.list_blocks()
    blocks = blocks_result.value if blocks_result.is_ok else []

    equip_result = ctx.equipment_service.get_equipment()
    equipment = equip_result.value if equip_result.is_ok else {}

    items_result = ctx.equipment_service.search_items()
    items_raw = items_result.value if items_result.is_ok else []
    items = []
    for it in items_raw:
        d = asdict(it)
        for k in ("created_at", "updated_at"):
            if k in d and d[k] is not None:
                d[k] = d[k].isoformat()
        items.append(d)

    strength_result = ctx.memory_repo.get_all_strengths()
    strengths_raw = strength_result.value if strength_result.is_ok else []
    strength_values = [s.strength for s in strengths_raw]
    strengths_summary = {
        "total": len(strength_values),
        "avg": round(sum(strength_values) / len(strength_values), 3) if strength_values else None,
        "min": round(min(strength_values), 3) if strength_values else None,
        "max": round(max(strength_values), 3) if strength_values else None,
    }

    # Helper: sort goals by status priority (active first), then by recency
    _status_priority = {"active": 0, "fulfilled": 1, "achieved": 1, "cancelled": 2}
    _max_commitments = 30

    goals_result = ctx.memory_repo.get_by_tags(["goal"])
    _goals_raw = goals_result.value if goals_result.is_ok else []
    _goals_sorted = sorted(
        _goals_raw,
        key=lambda m: (
            _status_priority.get(
                next((t for t in (m.tags or []) if t in ("active", "achieved", "cancelled")), "active"),
                99,
            ),
            -(m.created_at.timestamp() if m.created_at else 0),
        ),
    )
    goals = [
        {
            "content": m.content,
            "status": next((t for t in (m.tags or []) if t in ("active", "achieved", "cancelled")), "active"),
            "created_at": m.created_at.isoformat() if m.created_at else None,
            "key": m.key,
        }
        for m in _goals_sorted[:_max_commitments]
    ]

    try:
        total_count = stats.get("total_count", 0)
        if total_count > 0:
            linked_row = ctx.entity_repo._db.execute(
                "SELECT COUNT(DISTINCT memory_key) AS cnt FROM memory_entities WHERE memory_key != ''"
            ).fetchone()
            linked_count = linked_row["cnt"] if linked_row else 0
            stats["linked_ratio"] = min(linked_count / total_count, 1.0)
    except Exception:
        logger.exception("dashboard_data: linked_ratio calculation failed")
        pass

    # Relationship highlights from memory tags
    rel_highlights: list[dict] = []
    try:
        rel_result = ctx.memory_repo.find_relationship_highlights(limit=10)
        if rel_result.is_ok and rel_result.value:
            rel_highlights = [
                {
                    "content": m.content,
                    "key": m.key,
                    "importance": m.importance,
                    "tags": m.tags or [],
                    "created_at": m.created_at.isoformat() if m.created_at else None,
                }
                for m in rel_result.value
            ]
    except Exception:
        logger.exception("dashboard_data: relationship highlights failed")
        pass

    # State memories (speech/physical/mental) -- newest per tag for WebUI
    state_memories: dict[str, dict] = {}
    for tag in ["physical_state", "mental_state"]:
        try:
            mems_result = ctx.memory_service.get_by_tags([tag], include_consumed=True)
            if mems_result.is_ok and mems_result.value:
                latest = max(mems_result.value, key=lambda m: m.created_at or datetime.min)
                prefix = f"{tag}: "
                content = latest.content
                if content.startswith(prefix):
                    content = content[len(prefix) :]
                state_memories[tag] = {
                    "content": content,
                    "created_at": latest.created_at.isoformat() if latest.created_at else None,
                }
        except Exception:
            logger.exception("dashboard_data: state memories failed")
            pass

    # ── Latest self-portrait image ──
    latest_self_portrait: str | None = None
    try:
        images_dir = Path(get_settings().data_root) / "persona" / persona / "images"
        if images_dir.is_dir():
            self_files = sorted(images_dir.glob("self_*.png"))
            if self_files:
                latest = self_files[-1]  # sorted alphabetically = chronological
                latest_self_portrait = f"/api/chat/{persona}/persona/images/{latest.name}"
    except Exception:
        logger.exception("dashboard_data: self portrait lookup failed")
        pass

    return {
        "persona": persona,
        "stats": stats,
        "context": context,
        "recent": recent,
        "blocks": blocks,
        "equipment": equipment,
        "items": items,
        "strengths": strengths_summary,
        "goals": goals,
        "relationship_highlights": rel_highlights,
        "state_memories": state_memories,
        "latest_self_portrait": latest_self_portrait,
    }


async def _do_import_conversation(persona: str, ctx, file_path: str) -> dict:
    """Import conversation file into persona memory. Returns count dict."""
    from nous.migration.importers.convo_importer import parse_conversation_file

    messages = parse_conversation_file(file_path)
    if not messages:
        return {"imported": 0, "skipped": 0, "message": "No importable messages found"}
    imported = 0
    skipped = 0
    for msg in messages:
        res = await ctx.memory_service.create_memory(
            content=msg.content,
            importance=0.4,
            emotion="neutral",
            emotion_intensity=0.0,
            tags=[],
            privacy_level="internal",
            source_context="convo_import",
        )
        if res.is_ok:
            if ctx.vector_store:
                await ctx.vector_store.upsert(persona, res.value.key, msg.content)
            imported += 1
        else:
            skipped += 1
    return {"imported": imported, "skipped": skipped, "message": f"Imported {imported} messages"}


async def _do_create_persona(persona_name: str) -> dict:
    """Create a new persona. Returns status dict or error dict."""
    settings = Settings()
    persona_dir = Path(settings.persona_dir) / persona_name
    if persona_dir.exists():
        return {"error": f"Persona '{persona_name}' already exists"}
    ctx = AppContextRegistry.get(persona_name)
    if ctx is None:
        return {"error": "Failed to initialize persona"}
    return {
        "status": "ok",
        "persona": persona_name,
        "message": f"Persona '{persona_name}' created",
    }


async def _do_delete_persona(persona: str) -> dict:
    """Delete a persona by name. Returns status dict or error dict."""
    settings = Settings()
    persona_dir = (Path(settings.persona_dir) / persona).resolve()
    root = Path(settings.persona_dir).resolve()
    if not str(persona_dir).startswith(str(root) + "/"):
        return {"error": "Invalid persona name"}
    if not persona_dir.exists():
        return {"error": f"Persona '{persona}' not found"}
    try:
        if persona in AppContextRegistry._contexts:
            AppContextRegistry._contexts[persona].close()
            del AppContextRegistry._contexts[persona]
        shutil.rmtree(persona_dir)
        return {"status": "ok", "deleted": persona}
    except Exception:
        logger.exception("delete_persona failure")
        return {"error": "Internal server error"}


async def _do_sillytavern_card(persona: str, ctx) -> bytes:
    """Build SillyTavern card PNG bytes from persona state."""
    state_result = ctx.persona_service.get_context(persona)
    if not state_result.is_ok:
        raise ValueError("Failed to get persona context")
    return _build_sillytavern_card(state_result.value)


# ── HTTP adapter layer — 元の関数名を維持 ───────────────────────────────


async def health(request: Request) -> JSONResponse:  # noqa: ARG001
    """GET /health — health check."""
    return JSONResponse(await _do_health())


async def list_personas(request: Request) -> JSONResponse:
    """GET /api/personas — list personas."""
    return JSONResponse({"personas": await _do_list_personas()})


async def dashboard_page(request: Request) -> HTMLResponse:
    """GET / — root dashboard or setup page."""
    return HTMLResponse(await _do_dashboard_page())


async def dashboard_page_persona(request: Request) -> HTMLResponse:
    """GET /dashboard/{persona} — persona-specific dashboard."""
    persona = _resolve_persona_from_request(request)
    return HTMLResponse(await _do_dashboard_page(persona))


async def dashboard_data(request: Request) -> JSONResponse:
    """GET /api/dashboard/{persona} — dashboard data JSON."""
    persona, ctx = _resolve_request(request)
    if not ctx:
        return JSONResponse({"error": f"Persona '{persona}' not found"}, status_code=404)
    try:
        return JSONResponse(await _do_dashboard_data(persona, ctx))
    except Exception as exc:
        logger.exception("Unexpected error: %s", exc)
        return JSONResponse({"error": "Internal server error"}, status_code=500)


async def import_conversation(request: Request) -> JSONResponse:
    """POST /api/import-conversation/{persona} — upload conversation file."""
    persona, ctx = _resolve_request(request)
    if not ctx:
        return JSONResponse({"error": f"Persona '{persona}' not found"}, status_code=404)
    try:
        body = await request.json()
    except Exception:
        logger.exception("import_conversation: invalid JSON body")
        return JSONResponse({"error": "Invalid JSON body"}, status_code=400)
    file_path = (body.get("file_path") or "").strip()
    if not file_path:
        return JSONResponse({"error": "Field 'file_path' is required"}, status_code=400)
    try:
        result = await _do_import_conversation(persona, ctx, file_path)
    except FileNotFoundError:
        return JSONResponse({"error": f"File not found: {file_path}"}, status_code=404)
    except ValueError:
        return JSONResponse({"error": "Unsupported or invalid conversation file format"}, status_code=422)
    except Exception as exc:
        logger.exception("Conversation parse error: %s", exc)
        return JSONResponse({"error": "Failed to parse conversation file"}, status_code=500)
    return JSONResponse(result)


async def create_persona(request: Request) -> JSONResponse:
    """POST /api/personas — create a new persona."""
    try:
        body = await request.json()
    except Exception:
        logger.exception("create_persona: invalid JSON body")
        return JSONResponse({"error": "Invalid JSON body"}, status_code=400)
    persona_name = (body.get("name") or "").strip()
    if not persona_name:
        return JSONResponse({"error": "Field 'name' is required"}, status_code=400)
    if not _PERSONA_PATTERN.match(persona_name):
        return JSONResponse(
            {"error": "ペルソナ名には英数字・ハイフン・アンダースコアのみ使用できます"},
            status_code=400,
        )
    result = await _do_create_persona(persona_name)
    if "error" in result:
        status = 409 if "already exists" in result["error"] else 500
        return JSONResponse(result, status_code=status)
    return JSONResponse(result, status_code=201)


async def delete_persona(request: Request) -> JSONResponse:
    """DELETE /api/personas/{persona} — delete a persona."""
    persona = _resolve_persona_from_request(request)
    result = await _do_delete_persona(persona)
    if "error" in result:
        status_code = 400 if "Invalid" in result["error"] else 404 if "not found" in result["error"] else 500
        return JSONResponse(result, status_code=status_code)
    return JSONResponse(result)


async def sillytavern_card(request: Request) -> Response:
    """GET /api/personas/{persona}/card.png — export SillyTavern character card."""
    persona, ctx = _resolve_request(request)
    if not ctx:
        return JSONResponse({"error": f"Persona '{persona}' not found"}, status_code=404)
    try:
        png_bytes = await _do_sillytavern_card(persona, ctx)
        return Response(content=png_bytes, media_type="image/png")
    except ValueError:
        return JSONResponse({"error": "Internal server error"}, status_code=500)


def register_persona_routes(mcp) -> None:
    mcp.custom_route("/health", methods=["GET"])(health)
    mcp.custom_route("/api/personas", methods=["GET"])(list_personas)
    mcp.custom_route("/", methods=["GET"])(dashboard_page)
    mcp.custom_route("/dashboard/{persona}", methods=["GET"])(dashboard_page_persona)
    mcp.custom_route("/api/dashboard/{persona}", methods=["GET"])(dashboard_data)
    mcp.custom_route("/api/import-conversation/{persona}", methods=["POST"])(import_conversation)
    mcp.custom_route("/api/personas", methods=["POST"])(create_persona)
    mcp.custom_route("/api/personas/{persona}", methods=["DELETE"])(delete_persona)
    mcp.custom_route("/api/personas/{persona}/card.png", methods=["GET"])(sillytavern_card)

    @mcp.custom_route("/api/personas/{persona}/profile", methods=["PUT"])
    async def update_persona_profile(request: Request) -> JSONResponse:
        persona = _resolve_persona_from_request(request)
        ctx = _safe_get_context(persona)
        if ctx is None:
            return JSONResponse({"error": f"Persona '{persona}' not found"}, status_code=404)
        try:
            body = await request.json()
        except Exception:
            logger.exception("update_persona_profile: invalid JSON body")
            return JSONResponse({"error": "Invalid JSON body"}, status_code=400)
        try:
            updated = []
            if "user_info" in body and isinstance(body["user_info"], dict):
                result = ctx.persona_service.update_user_info(persona, body["user_info"])
                if result.is_ok:
                    updated.append("user_info")
            if "persona_info" in body and isinstance(body["persona_info"], dict):
                result = ctx.persona_service.update_persona_info(persona, body["persona_info"])
                if result.is_ok:
                    updated.append("persona_info")
            if "relationship_status" in body:
                result = ctx.persona_service.update_relationship(persona, body["relationship_status"])
                if result.is_ok:
                    updated.append("relationship_status")
            if not updated:
                return JSONResponse({"error": "No valid fields to update"}, status_code=400)
            return JSONResponse({"status": "ok", "updated": updated})
        except Exception as exc:
            logger.exception("Unexpected error: %s", exc)
            return JSONResponse({"error": "Internal server error"}, status_code=500)


def _build_sillytavern_card(state: PersonaState) -> bytes:
    """Build a SillyTavern v3 character card PNG from a PersonaState.

    Creates a 400×600 PNG with a solid background colored by the current
    emotion and embeds the ``chara`` JSON in a ``tEXt`` chunk per the
    SillyTavern v3 spec.
    """
    import io
    import json as _json

    from PIL import Image, PngImagePlugin

    emotion_colors: dict[str, str] = {
        "joy": "#FFD700",
        "sadness": "#6495ED",
        "anger": "#FF4500",
        "fear": "#9370DB",
        "surprise": "#FF69B4",
        "disgust": "#228B22",
        "trust": "#20B2AA",
        "anticipation": "#FF8C00",
        "love": "#FF1493",
        "neutral": "#A9A9A9",
    }

    pi = state.persona_info or {}
    display_name = pi.get("nickname") or state.persona

    color_hex = emotion_colors.get(state.emotion, "#A9A9A9")
    # Convert hex to RGBA tuple
    color_rgba = tuple(int(color_hex.lstrip("#")[i : i + 2], 16) for i in (0, 2, 4)) + (255,)

    img = Image.new("RGBA", (400, 600), color_rgba)

    card_data: dict = {
        "spec": "chara_card_v3",
        "spec_version": "3.0",
        "data": {
            "name": display_name,
            "description": pi.get("description") or pi.get("personality", ""),
            "personality": pi.get("personality_summary", ""),
            "scenario": pi.get("scenario", ""),
            "first_mes": pi.get("greeting") or pi.get("first_message", f"こんにちは、{display_name}です。"),
            "mes_example": pi.get("example_dialogue", ""),
            "creator_notes": "",
            "system_prompt": pi.get("system_prompt", ""),
            "post_history_instructions": "",
            "tags": [],
            "creator": "Nous",
            "character_version": "1.0",
            "extensions": {},
        },
    }

    png_info = PngImagePlugin.PngInfo()
    png_info.add_text("chara", _json.dumps(card_data, ensure_ascii=False))

    buf = io.BytesIO()
    img.save(buf, format="PNG", pnginfo=png_info)
    return buf.getvalue()


def _render_setup_page() -> str:
    """Return minimal setup HTML when no persona exists."""
    return r"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Nous — Setup</title>
<script src="https://cdn.tailwindcss.com"></script>
<script src="https://unpkg.com/lucide@latest"></script>
<style>
  body {
    background: linear-gradient(135deg, #0f0a1a 0%, #1a1035 50%, #0f0a1a 100%);
    min-height: 100vh; display: flex; align-items: center; justify-content: center;
    font-family: system-ui, -apple-system, sans-serif;
    margin: 0; padding: 20px;
  }
  .glass {
    background: rgba(255,255,255,0.04);
    backdrop-filter: blur(16px);
    border: 1px solid rgba(255,255,255,0.08);
    border-radius: 20px;
    padding: 40px;
    max-width: 440px;
    width: 100%;
    box-shadow: 0 8px 40px rgba(0,0,0,0.4);
  }
  .glass-input {
    background: rgba(255,255,255,0.06);
    border: 1px solid rgba(255,255,255,0.12);
    border-radius: 12px;
    color: rgba(255,255,255,0.9);
    padding: 12px 16px;
    width: 100%;
    box-sizing: border-box;
    outline: none;
    transition: border-color 0.2s;
  }
  .glass-input:focus { border-color: #a855f7; }
  .glass-btn {
    background: rgba(255,255,255,0.08);
    border: 1px solid rgba(255,255,255,0.12);
    border-radius: 12px;
    color: rgba(255,255,255,0.9);
    padding: 10px 24px;
    cursor: pointer;
    transition: background 0.2s;
    font-size: 0.95rem;
  }
  .glass-btn:hover { background: rgba(255,255,255,0.14); }
  .btn-primary {
    background: #a855f7;
    border: none;
    color: white;
  }
  .btn-primary:hover { background: #9333ea; }
  .text-muted { color: rgba(255,255,255,0.5); font-size: 0.85rem; }
</style>
</head>
<body>
<div class="glass">
  <div style="display:flex;align-items:center;gap:12px;margin-bottom:24px">
    <i data-lucide="brain" style="width:2rem;height:2rem;color:#a855f7"></i>
    <div>
      <h1 style="font-size:1.5rem;font-weight:700;color:white;margin:0">Nous</h1>
      <p style="margin:2px 0 0 0" class="text-muted">Welcome! Let's set up your first persona.</p>
    </div>
  </div>

  <p style="color:rgba(255,255,255,0.7);margin-bottom:20px;line-height:1.5">
    A <strong>persona</strong> is your AI companion's identity — memories, emotions,
    and state are scoped per persona. Create one to get started.
  </p>

  <form id="setup-form" onsubmit="return createPersona(event)">
    <label style="display:block;font-size:0.9rem;color:rgba(255,255,255,0.8);margin-bottom:6px">
      Persona name
    </label>
    <input type="text" id="persona-name" class="glass-input"
      placeholder="e.g. assistant, friend, scholar"
      maxlength="50" pattern="[a-zA-Z0-9_\-]{1,50}"
      title="Letters, numbers, hyphens, underscores (1-50 chars)"
      autofocus required>
    <p class="text-muted" style="margin:6px 0 0 0">
      Allowed: letters, numbers, underscores, hyphens (1-50 chars)
    </p>

    <div id="error-msg" style="color:#ef4444;font-size:0.85rem;margin-top:10px;display:none"></div>

    <button type="submit" id="create-btn" class="glass-btn btn-primary"
      style="width:100%;margin-top:20px;padding:12px;font-size:1rem;font-weight:600">
      <i data-lucide="sparkles" style="width:1.1rem;height:1.1rem;vertical-align:middle"></i>
      Create Persona
    </button>
  </form>
</div>

<script>
  if (typeof lucide !== "undefined") lucide.createIcons();
  async function createPersona(e) {
    e.preventDefault();
    var name = document.getElementById('persona-name').value.trim();
    var errEl = document.getElementById('error-msg');
    var btn = document.getElementById('create-btn');
    if (!name) return false;
    btn.disabled = true;
    btn.textContent = 'Creating...';
    var ctrl = new AbortController();
    var timer = setTimeout(function(){ ctrl.abort(); }, 60000);
    try {
      var res = await fetch('/api/personas', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({name: name}),
        signal: ctrl.signal
      });
      clearTimeout(timer);
      var data = await res.json();
      if (!res.ok) {
        errEl.textContent = data.error || 'Failed to create persona';
        errEl.style.display = 'block';
        btn.disabled = false;
        btn.textContent = 'Create Persona';
        return false;
      }
      window.location.href = '/dashboard/' + encodeURIComponent(name);
    } catch (e) {
      clearTimeout(timer);
      errEl.textContent = e.name === 'AbortError'
        ? 'Request timed out (60s). Is Qdrant running?'
        : 'Network error: ' + e.message;
      errEl.style.display = 'block';
      btn.disabled = false;
      btn.textContent = 'Create Persona';
    }
    return false;
  }
</script>
</body>
</html>"""
