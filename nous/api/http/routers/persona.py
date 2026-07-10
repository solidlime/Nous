from __future__ import annotations

import shutil
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from starlette.responses import HTMLResponse, JSONResponse

from nous.api.http.deps import (
    _PERSONA_PATTERN,
    _memory_to_dict,
    _resolve_persona_from_request,
    _safe_get_context,
)
from nous.application.use_cases import AppContextRegistry
from nous.config.settings import Settings
from nous.infrastructure.logging.structured import get_logger

if TYPE_CHECKING:
    from starlette.requests import Request

logger = get_logger(__name__)


def register_persona_routes(mcp) -> None:
    @mcp.custom_route("/health", methods=["GET"])
    async def health(request: Request) -> JSONResponse:  # noqa: ARG001
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

        return JSONResponse(
            {
                "status": "ok",
                "version": __version__,
                "qdrant": "connected" if qdrant_ok else "unavailable",
            }
        )

    @mcp.custom_route("/api/personas", methods=["GET"])
    async def list_personas(request: Request) -> JSONResponse:
        settings = Settings()
        data_dir = settings.data_dir
        data_path = Path(data_dir)
        if data_path.exists():
            personas = sorted([d.name for d in data_path.iterdir() if d.is_dir() and (d / "memory.sqlite").exists()])
        else:
            personas = []
        return JSONResponse({"personas": personas})

    @mcp.custom_route("/", methods=["GET"])
    async def dashboard_page(request: Request) -> HTMLResponse:
        from nous.api.http.dashboard import render_dashboard

        # Check if any personas exist; show setup screen if none.
        settings = Settings()
        data_path = Path(settings.data_dir)
        persona_count = 0
        if data_path.exists():
            persona_count = len([d for d in data_path.iterdir() if d.is_dir() and (d / "memory.sqlite").exists()])

        if persona_count == 0:
            return HTMLResponse(_render_setup_page())

        return HTMLResponse(render_dashboard())

    @mcp.custom_route("/dashboard/{persona}", methods=["GET"])
    async def dashboard_page_persona(request: Request) -> HTMLResponse:
        from nous.api.http.dashboard import render_dashboard

        persona = _resolve_persona_from_request(request)
        return HTMLResponse(render_dashboard(persona))

    @mcp.custom_route("/api/dashboard/{persona}", methods=["GET"])
    async def dashboard_data(request: Request) -> JSONResponse:
        persona = _resolve_persona_from_request(request)
        ctx = _safe_get_context(persona)
        if ctx is None:
            return JSONResponse({"error": f"Persona '{persona}' not found"}, status_code=404)
        try:
            stats_result = ctx.memory_service.get_stats()
            stats = stats_result.value if stats_result.is_ok else {}

            context_result = ctx.persona_service.get_context(persona)
            context = asdict(context_result.value) if context_result.is_ok else {}
            for _dt_key in ("last_conversation_time", "last_state_update"):
                if _dt_key in context and context[_dt_key] is not None:
                    context[_dt_key] = context[_dt_key].isoformat()

            for _f in (
                "environment",
                "speech_style",
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
                pass

            # State memories (speech/physical/mental) -- newest per tag for WebUI
            state_memories: dict[str, dict] = {}
            for tag in ["speech_style", "physical_state", "mental_state"]:
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
                    pass

            return JSONResponse(
                {
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
                }
            )
        except Exception as exc:
            logger.exception("Unexpected error: %s", exc)
            return JSONResponse({"error": "Internal server error"}, status_code=500)

    @mcp.custom_route("/api/import-conversation/{persona}", methods=["POST"])
    async def import_conversation(request: Request) -> JSONResponse:
        persona = _resolve_persona_from_request(request)
        ctx = _safe_get_context(persona)
        if ctx is None:
            return JSONResponse({"error": f"Persona '{persona}' not found"}, status_code=404)
        try:
            body = await request.json()
        except Exception:
            return JSONResponse({"error": "Invalid JSON body"}, status_code=400)
        file_path = body.get("file_path", "").strip()
        if not file_path:
            return JSONResponse({"error": "Field 'file_path' is required"}, status_code=400)
        try:
            from nous.migration.importers.convo_importer import parse_conversation_file

            messages = parse_conversation_file(file_path)
        except FileNotFoundError:
            return JSONResponse({"error": f"File not found: {file_path}"}, status_code=404)
        except ValueError:
            return JSONResponse({"error": "Unsupported or invalid conversation file format"}, status_code=422)
        except Exception as exc:
            logger.exception("Conversation parse error: %s", exc)
            return JSONResponse({"error": "Failed to parse conversation file"}, status_code=500)
        if not messages:
            return JSONResponse({"imported": 0, "skipped": 0, "message": "No importable messages found"})
        imported = 0
        skipped = 0
        for msg in messages:
            res = ctx.memory_service.create_memory(
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
        return JSONResponse({"imported": imported, "skipped": skipped, "message": f"Imported {imported} messages"})

    @mcp.custom_route("/api/personas", methods=["POST"])
    async def create_persona(request: Request) -> JSONResponse:
        try:
            body = await request.json()
        except Exception:
            return JSONResponse({"error": "Invalid JSON body"}, status_code=400)
        persona_name = body.get("name")
        if not persona_name:
            return JSONResponse({"error": "Field 'name' is required"}, status_code=400)
        if not _PERSONA_PATTERN.match(persona_name):
            return JSONResponse(
                {"error": "Persona name must contain only alphanumeric characters, hyphens, and underscores"},
                status_code=400,
            )
        settings = Settings()
        persona_dir = Path(settings.data_dir) / persona_name
        if persona_dir.exists():
            return JSONResponse({"error": f"Persona '{persona_name}' already exists"}, status_code=409)
        try:
            ctx = AppContextRegistry.get(persona_name)
            if ctx is None:
                return JSONResponse({"error": "Failed to initialize persona"}, status_code=500)
            return JSONResponse(
                {"status": "ok", "persona": persona_name, "message": f"Persona '{persona_name}' created"},
                status_code=201,
            )
        except Exception as exc:
            logger.exception("Unexpected error: %s", exc)
            return JSONResponse({"error": "Internal server error"}, status_code=500)

    @mcp.custom_route("/api/personas/{persona}", methods=["DELETE"])
    async def delete_persona(request: Request) -> JSONResponse:
        persona = _resolve_persona_from_request(request)
        settings = Settings()
        persona_dir = (Path(settings.data_dir) / persona).resolve()
        if not str(persona_dir).startswith(str(Path(settings.data_dir).resolve()) + "/"):
            return JSONResponse({"error": "Invalid persona name"}, status_code=400)
        if not persona_dir.exists():
            return JSONResponse({"error": f"Persona '{persona}' not found"}, status_code=404)
        try:
            if persona in AppContextRegistry._contexts:
                AppContextRegistry._contexts[persona].close()
                del AppContextRegistry._contexts[persona]
            shutil.rmtree(persona_dir)
            return JSONResponse({"status": "ok", "deleted": persona})
        except Exception as exc:
            logger.exception("Unexpected error: %s", exc)
            return JSONResponse({"error": "Internal server error"}, status_code=500)

    @mcp.custom_route("/api/personas/{persona}/profile", methods=["PUT"])
    async def update_persona_profile(request: Request) -> JSONResponse:
        persona = _resolve_persona_from_request(request)
        ctx = _safe_get_context(persona)
        if ctx is None:
            return JSONResponse({"error": f"Persona '{persona}' not found"}, status_code=404)
        try:
            body = await request.json()
        except Exception:
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
      maxlength="50" pattern="[a-zA-Z0-9_-]{1,50}"
      title="Alphanumeric, hyphens, underscores (1-50 chars)"
      autofocus required>
    <p class="text-muted" style="margin:6px 0 0 0">
      Allowed: letters, numbers, underscores, hyphens (1-50 chars)
    </p>

    <div id="error-msg" style="color:#ef4444;font-size:0.85rem;margin-top:10px;display:none"></div>

    <button type="submit" id="create-btn" class="glass-btn btn-primary"
      style="width:100%;margin-top:20px;padding:12px;font-size:1rem;font-weight:600"
      onclick="this.disabled=true;this.textContent='Creating...'">
      <i data-lucide="sparkles" style="width:1.1rem;height:1.1rem;vertical-align:middle"></i>
      Create Persona
    </button>
  </form>
</div>

<script>
  lucide.createIcons();
  async function createPersona(e) {
    e.preventDefault();
    var name = document.getElementById('persona-name').value.trim();
    var errEl = document.getElementById('error-msg');
    var btn = document.getElementById('create-btn');
    if (!name) return false;
    try {
      var res = await fetch('/api/personas', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({name: name})
      });
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
      errEl.textContent = 'Network error: ' + e.message;
      errEl.style.display = 'block';
      btn.disabled = false;
      btn.textContent = 'Create Persona';
    }
    return false;
  }
</script>
</body>
</html>"""
