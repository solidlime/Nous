from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from starlette.responses import HTMLResponse, JSONResponse

from nous.api.http.deps import _memory_to_dict, _resolve_persona_from_request
from nous.api.http.routers.persona.persona_helpers import _resolve_request
from nous.config.settings import Settings, get_settings
from nous.infrastructure.logging.structured import get_logger

if TYPE_CHECKING:
    from starlette.requests import Request

logger = get_logger(__name__)


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


async def dashboard_page(request: Request) -> HTMLResponse:
    """GET / — root dashboard or setup page."""
    return HTMLResponse(await _do_dashboard_page())


async def dashboard_page_persona(request: Request) -> HTMLResponse:
    """GET /dashboard/{persona} — persona-specific dashboard."""
    persona = _resolve_persona_from_request(request)
    return HTMLResponse(await _do_dashboard_page(persona))


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

    recent_result = ctx.memory_service.get_recent(limit=50)
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
        # 非致命的、ダッシュボードはリンク比率なしで表示継続

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
        # 非致命的、ハイライトなしで表示継続

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
            # 非致命的、状態メモリなしで表示継続

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
        # 非致命的、ポートレートなしで表示継続

    # ── Generated images history (max 20, newest first) ──
    generated_images: list[dict] = []
    try:
        images_dir = Path(get_settings().data_root) / "persona" / persona / "images"
        if images_dir.is_dir():
            all_images = sorted(images_dir.glob("*.png"), key=lambda f: f.stat().st_mtime, reverse=True)
            for img_file in all_images[:20]:
                generated_images.append({
                    "url": f"/api/chat/{persona}/persona/images/{img_file.name}",
                    "filename": img_file.name,
                    "created_at": datetime.fromtimestamp(img_file.stat().st_mtime).isoformat(),
                    "is_self_portrait": img_file.name.startswith("self_"),
                })
    except Exception:
        logger.exception("dashboard_data: generated images lookup failed")
        # 非致命的、画像履歴なしで表示継続

    # ── Enrich generated_images with prompt data from message metadata ──
    if generated_images:
        try:
            db = ctx.connection.get_memory_db()
            rows = db.execute(
                "SELECT metadata FROM messages WHERE metadata LIKE '%image_generation%'"
            ).fetchall()
            prompt_lookup: dict[str, dict[str, str]] = {}
            for (meta_str,) in rows:
                try:
                    meta = json.loads(meta_str)
                    if meta.get("type") == "image_generation" and meta.get("filename"):
                        prompt_lookup[meta["filename"]] = {
                            "revised_prompt": meta.get("prompt", ""),
                            "negative_prompt": meta.get("negative_prompt", ""),
                        }
                except (json.JSONDecodeError, TypeError):
                    continue
            for img in generated_images:
                info = prompt_lookup.get(img.get("filename", ""), {})
                img["revised_prompt"] = info.get("revised_prompt", "")
                img["negative_prompt"] = info.get("negative_prompt", "")
        except Exception:
            logger.debug("dashboard_data: prompt enrichment skipped")

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
        "generated_images": generated_images,
    }


async def dashboard_data(request: Request) -> JSONResponse:
    """GET /api/dashboard/{persona} — dashboard data JSON."""
    persona, ctx = _resolve_request(request)
    if not ctx:
        return JSONResponse({"error": f"Persona '{persona}' not found"}, status_code=404)
    try:
        return JSONResponse(await _do_dashboard_data(persona, ctx))
    # 最終防衛線
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
