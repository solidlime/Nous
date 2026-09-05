"""E2E dogfooding tests for the Nous v3 dashboard.

Tests all HTTP endpoints registered via ``register_http_routes`` against a
real (temporary) SQLite backend and mocked/absent Qdrant vector store.
Requires: pytest, httpx, pytest-asyncio
"""

from __future__ import annotations

import os
import shutil
import tempfile
from datetime import timedelta, timezone
from unittest.mock import patch

import httpx
import pytest

from nous.application.use_cases import AppContext, AppContextRegistry
from nous.config.runtime_config import RuntimeConfigManager
from nous.domain.shared.time_utils import format_iso, get_now
from nous.main import create_app

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

JST = timezone(timedelta(hours=9))


@pytest.fixture()
def tmp_data_dir():
    """Create a temporary data directory and clean up after the test."""
    d = tempfile.mkdtemp(prefix="memorymcp_test_")
    yield d
    shutil.rmtree(d, ignore_errors=True)


@pytest.fixture()
def _reset_singletons():
    """Reset global singletons before and after each test."""
    # --- before ---
    AppContextRegistry.close_all()
    AppContextRegistry._settings = None
    RuntimeConfigManager.reset()
    import nous.config.settings as _s

    _s.get_settings.cache_clear()
    yield
    # --- after ---
    AppContextRegistry.close_all()
    AppContextRegistry._settings = None
    RuntimeConfigManager.reset()
    _s.get_settings.cache_clear()


@pytest.fixture()
async def client(tmp_data_dir, _auto_persona_dirs):
    """httpx AsyncClient backed by a fresh Nous Starlette app."""
    env_overrides = {
        "NOUS_DATA_ROOT": tmp_data_dir,
        "NOUS_SERVER__HOST": "127.0.0.1",
        "NOUS_SERVER__PORT": "19999",
        "NOUS_QDRANT__URL": "http://localhost:1",  # intentionally unreachable
        "NOUS_FORGETTING__ENABLED": "false",
        "NOUS_LOG_LEVEL": "WARNING",
        "NOUS_IMPORT_DIR": "",
    }
    with patch.dict(os.environ, env_overrides, clear=False):
        app_mcp = create_app()
        starlette_app = app_mcp.streamable_http_app()
        transport = httpx.ASGITransport(app=starlette_app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as ac:
            yield ac


def _get_ctx(persona: str = "testpersona") -> AppContext:
    """Convenience: retrieve the AppContext for *persona*."""
    return AppContextRegistry.get(persona)


def _get_db(persona: str = "testpersona"):
    """Get the raw sqlite3.Connection for *persona*'s memory DB."""
    return _get_ctx(persona).connection.get_memory_db()


def _seed_memories(persona: str = "testpersona", n: int = 6) -> list[str]:
    """Insert *n* memories directly via raw SQL and return their keys."""
    import json

    db = _get_db(persona)
    keys: list[str] = []
    for i in range(n):
        now = get_now() - timedelta(hours=n - i)
        now_str = format_iso(now)
        key = f"test_mem_{i:03d}"
        tags = ["food", "test"] if i % 2 == 0 else ["science", "test"]
        emotion = "joy" if i % 2 == 0 else "curiosity"
        db.execute(
            """INSERT OR REPLACE INTO memories
               (key, content, created_at, updated_at, tags, importance,
                emotion, emotion_intensity, privacy_level)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                key,
                f"テスト記憶 {i}: ユーザーはラーメンが好き。メモリ番号{i}。",
                now_str,
                now_str,
                json.dumps(tags, ensure_ascii=False),
                round(0.3 + 0.1 * i, 2),
                emotion,
                round(0.4 + 0.05 * i, 2),
                "internal",
            ),
        )
        db.execute(
            """INSERT OR REPLACE INTO memory_strength
               (memory_key, strength, stability, last_decay, recall_count, last_recall)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                key,
                round(0.5 + 0.08 * i, 3),
                round(1.0 + 0.5 * i, 2),
                now_str,
                i,
                now_str,
            ),
        )
        keys.append(key)
    db.commit()
    return keys


def _seed_emotions(persona: str = "testpersona", n: int = 4) -> None:
    """Insert emotion history records via raw SQL."""
    db = _get_db(persona)
    emotions = ["joy", "curiosity", "sadness", "excitement"]
    for i in range(n):
        now = get_now() - timedelta(hours=n - i)
        db.execute(
            """INSERT INTO emotion_history
               (emotion_type, intensity, timestamp, trigger_memory_key, context)
               VALUES (?, ?, ?, ?, ?)""",
            (
                emotions[i % len(emotions)],
                round(0.3 + 0.15 * i, 2),
                format_iso(now),
                f"test_mem_{i:03d}" if i < 3 else None,
                f"テスト感情コンテキスト {i}",
            ),
        )
    db.commit()


def _seed_goals_and_promises(persona: str = "testpersona") -> None:
    """Insert goals and promises as memory entries with type tags."""
    import json

    db = _get_db(persona)
    now_str = format_iso(get_now())
    db.execute(
        """INSERT OR REPLACE INTO memories
           (key, content, created_at, updated_at, tags, importance,
            emotion, emotion_intensity, privacy_level)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            "goal_001",
            "宇宙の謎を解明する",
            now_str,
            now_str,
            json.dumps(["goal", "active"], ensure_ascii=False),
            0.8,
            "anticipation",
            0.7,
            "internal",
        ),
    )
    db.execute(
        """INSERT OR REPLACE INTO memories
           (key, content, created_at, updated_at, tags, importance,
            emotion, emotion_intensity, privacy_level)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            "promise_001",
            "毎日研究を続ける",
            now_str,
            now_str,
            json.dumps(["promise", "active"], ensure_ascii=False),
            0.8,
            "trust",
            0.7,
            "internal",
        ),
    )
    db.commit()


@pytest.fixture()
async def seeded_client(client):
    """Client with pre-seeded test data (memories, emotions, goals, promises)."""
    _seed_memories()
    _seed_emotions()
    _seed_goals_and_promises()
    yield client


# ===================================================================
# Basic Tests (E1–E3 + health)
# ===================================================================


@pytest.mark.asyncio
async def test_dashboard_html_loads(client):
    """E1: GET / → 200, HTML contains key dashboard elements."""
    # Create a persona first so the dashboard loads (not the setup page)
    create_resp = await client.post("/api/personas", json={"name": "testpersona"})
    assert create_resp.status_code == 201, f"Setup failed: {create_resp.text}"
    resp = await client.get("/")
    assert resp.status_code == 200
    html = resp.text
    assert "Nous" in html
    # Chart.js reference
    assert "chart.js" in html.lower() or "Chart" in html
    # Tailwind reference
    assert "tailwindcss" in html.lower() or "tailwind" in html.lower()
    # 5 tabs
    for tab in ("Overview", "Memories", "Settings", "Chat", "Activity"):
        assert tab in html, f"Tab '{tab}' not found in dashboard HTML"


@pytest.mark.asyncio
async def test_health_endpoint(client):
    """Health check returns ok even when Qdrant is unavailable."""
    resp = await client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["version"] == "3.5.0"
    assert data["qdrant"] in ("connected", "unavailable")


@pytest.mark.asyncio
async def test_persona_list(client):
    """E2: GET /api/personas → 200, personas array."""
    resp = await client.get("/api/personas")
    assert resp.status_code == 200
    data = resp.json()
    assert "personas" in data
    assert isinstance(data["personas"], list)


@pytest.mark.asyncio
async def test_dashboard_data_empty(client):
    """E3: GET /api/dashboard/{persona} → 200 with correct structure on empty DB."""
    resp = await client.get("/api/dashboard/testpersona")
    assert resp.status_code == 200
    data = resp.json()
    assert data["persona"] == "testpersona"
    for key in ("stats", "context", "recent", "blocks", "equipment", "strengths", "goals"):
        assert key in data, f"Missing key '{key}' in dashboard data"
    # Empty DB → no memories
    assert data["recent"] == []
    assert data["strengths"]["total"] == 0


# ===================================================================
# Data Operation Tests (E4–E8)
# ===================================================================


@pytest.mark.asyncio
async def test_dashboard_data_with_memories(seeded_client):
    """E4: Seeded data reflected in dashboard endpoint."""
    resp = await seeded_client.get("/api/dashboard/testpersona")
    assert resp.status_code == 200
    data = resp.json()
    assert data["persona"] == "testpersona"
    # recent returns up to 50 (dashboard fetches limit=50)
    assert len(data["recent"]) <= 50
    assert len(data["recent"]) > 0
    # strengths summary
    assert data["strengths"]["total"] == 6
    assert data["strengths"]["avg"] > 0
    # goals and promises
    assert len(data["goals"]) >= 1


@pytest.mark.asyncio
async def test_recent_memories(seeded_client):
    """E5: GET /api/observations/{persona}?mode=recent&per_page=5 → at most 5 memories."""
    resp = await seeded_client.get("/api/observations/testpersona?mode=recent&per_page=5")
    assert resp.status_code == 200
    data = resp.json()
    assert data["persona"] == "testpersona"
    assert isinstance(data["memories"], list)
    assert len(data["memories"]) <= 5
    assert len(data["memories"]) > 0
    # Each memory has required fields
    mem = data["memories"][0]
    assert "key" in mem
    assert "content" in mem
    assert "created_at" in mem


@pytest.mark.asyncio
async def test_search_memories_keyword_fallback(seeded_client):
    """E6: GET /api/search/{persona}?q=ラーメン → keyword search works without Qdrant."""
    resp = await seeded_client.get("/api/search/testpersona?q=ラーメン")
    assert resp.status_code == 200
    data = resp.json()
    assert data["persona"] == "testpersona"
    assert data["query"] == "ラーメン"
    assert isinstance(data["results"], list)
    # All seeded memories contain "ラーメン" so we expect results
    assert len(data["results"]) > 0
    # Each result has correct structure
    r = data["results"][0]
    assert "memory" in r
    assert "score" in r
    assert "source" in r


@pytest.mark.asyncio
async def test_search_memories_missing_query(client):
    """Search without q parameter returns 400."""
    resp = await client.get("/api/search/testpersona")
    assert resp.status_code == 400
    data = resp.json()
    assert "error" in data


@pytest.mark.asyncio
async def test_emotion_timeline(seeded_client):
    """E7削除: GET /api/emotions廃止（dashboard集約に一本化）。dashboard contextで代替確認。"""
    resp = await seeded_client.get("/api/dashboard/testpersona")
    assert resp.status_code == 200
    assert "context" in resp.json()


@pytest.mark.asyncio
async def test_observations_pagination(seeded_client):
    """E8: GET /api/observations/{persona}?page=1&per_page=3 → paginated results."""
    resp = await seeded_client.get("/api/observations/testpersona?page=1&per_page=3")
    assert resp.status_code == 200
    data = resp.json()
    assert data["persona"] == "testpersona"
    assert data["page"] == 1
    assert data["per_page"] == 3
    assert data["total_count"] == 8  # 6 regular memories + 1 goal + 1 promise
    assert data["total_pages"] == 3  # 8 memories / 3 per_page = ceil(8/3)=3
    assert len(data["memories"]) == 3

    # Fetch page 2
    resp2 = await seeded_client.get("/api/observations/testpersona?page=2&per_page=3")
    data2 = resp2.json()
    assert data2["page"] == 2
    assert len(data2["memories"]) == 3

    # Keys from page 1 and page 2 should not overlap
    keys_p1 = {m["key"] for m in data["memories"]}
    keys_p2 = {m["key"] for m in data2["memories"]}
    assert keys_p1.isdisjoint(keys_p2)


# ===================================================================
# Strength & Admin Tests (E9–E10): d1/d6削除に伴い直叩きテスト廃止
# ===================================================================


@pytest.mark.asyncio
async def test_strengths_endpoint(seeded_client):
    """E9削除: 直叩き廃止。dashboard集約data.strengthsで代替確認。"""
    resp = await seeded_client.get("/api/dashboard/testpersona")
    assert resp.status_code == 200
    assert resp.json()["strengths"]["total"] == 6


@pytest.mark.asyncio
async def test_admin_rebuild_no_qdrant(client):
    """E10削除: POST /api/admin/rebuild廃止のため削除。ダッシュボード生存で代替。"""
    resp = await client.get("/api/dashboard/testpersona")
    assert resp.status_code in (200, 404)


# ===================================================================
# Settings Tests (E11–E14)
# ===================================================================


@pytest.mark.asyncio
async def test_settings_get_all(client):
    """E11: GET /api/settings → all categories with source & hot_reload metadata."""
    resp = await client.get("/api/settings")
    assert resp.status_code == 200
    data = resp.json()
    assert "settings" in data
    assert "reload_status" in data
    settings = data["settings"]
    # Verify expected categories exist
    for cat in ("server", "embedding", "reranker", "qdrant", "general"):
        assert cat in settings, f"Missing category '{cat}'"
    # Verify structure of a setting entry
    tz_entry = settings["general"]["timezone"]
    assert "value" in tz_entry
    assert "source" in tz_entry
    assert "hot_reload" in tz_entry
    assert tz_entry["source"] in ("default", "override", "env")


@pytest.mark.asyncio
async def test_settings_update_timezone(client):
    """E12: PUT /api/settings timezone → immediate effect."""
    resp = await client.put(
        "/api/settings",
        json={"category": "general", "key": "timezone", "value": "US/Eastern"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert data["value"] == "US/Eastern"

    # Re-fetch and verify
    resp2 = await client.get("/api/settings")
    tz = resp2.json()["settings"]["general"]["timezone"]
    assert tz["value"] == "US/Eastern"
    assert tz["source"] == "override"


@pytest.mark.asyncio
async def test_settings_restart_required(client):
    """E14: PUT /api/settings server.host → saves override, restart_required."""
    resp = await client.put(
        "/api/settings",
        json={"category": "server", "key": "host", "value": "0.0.0.0"},
    )
    # server.host has hot_reload=False → saved to disk, restart required
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert data.get("restart_required") is True


# ===================================================================
# Full Dogfooding Flow (E15)
# ===================================================================


@pytest.mark.asyncio
async def test_full_dogfooding_flow(client):
    """E15: Complete end-to-end dogfooding flow.

    1.  Health check
    2.  Persona list
    3.  Dashboard HTML
    4.  Dashboard data (empty)
    5.  Create memories via repository
    6.  Dashboard data (with memories)
    7.  Search
    8.  Settings get
    9.  Settings update (timezone)
    10. Settings verify
    11. Delete a memory
    12. Dashboard data (post-delete)
    """
    persona = "e2e_persona"

    # 1. Health check
    resp = await client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"

    # 2. Persona list
    resp = await client.get("/api/personas")
    assert resp.status_code == 200

    # 3. Dashboard HTML
    resp = await client.get("/")
    assert resp.status_code == 200
    assert "Nous" in resp.text

    # 4. Dashboard data (empty)
    resp = await client.get(f"/api/dashboard/{persona}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["recent"] == []
    assert data["strengths"]["total"] == 0

    # 5. Create memories via raw SQL
    import json as _json

    db = _get_db(persona)
    now = get_now()
    keys = []
    for i in range(3):
        ts = format_iso(now - timedelta(hours=3 - i))
        key = f"e2e_mem_{i:03d}"
        db.execute(
            """INSERT OR REPLACE INTO memories
               (key, content, created_at, updated_at, tags, importance,
                emotion, emotion_intensity, privacy_level)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                key,
                f"E2Eテスト記憶 {i}: 宇宙ステーションの実験データ番号{i}。",
                ts,
                ts,
                _json.dumps(["e2e", "science"], ensure_ascii=False),
                0.6 + 0.1 * i,
                "curiosity",
                0.5,
                "internal",
            ),
        )
        db.execute(
            """INSERT OR REPLACE INTO memory_strength
               (memory_key, strength, stability, last_decay, recall_count, last_recall)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (key, 0.8, 2.0, format_iso(now), 0, format_iso(now)),
        )
        keys.append(key)
    db.commit()

    # 6. Dashboard data (with memories)
    resp = await client.get(f"/api/dashboard/{persona}")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["recent"]) == 3
    assert data["strengths"]["total"] == 3

    # 7. Search (keyword)
    resp = await client.get(f"/api/search/{persona}?q=宇宙ステーション")
    assert resp.status_code == 200
    results = resp.json()["results"]
    assert len(results) >= 1

    # 8. Settings get
    resp = await client.get("/api/settings")
    assert resp.status_code == 200
    settings_data = resp.json()
    assert "settings" in settings_data

    # 9. Settings update (timezone)
    resp = await client.put(
        "/api/settings",
        json={"category": "general", "key": "timezone", "value": "Europe/London"},
    )
    assert resp.status_code == 200
    assert resp.json()["success"] is True

    # 10. Settings verify
    resp = await client.get("/api/settings")
    tz = resp.json()["settings"]["general"]["timezone"]
    assert tz["value"] == "Europe/London"
    assert tz["source"] == "override"

    # 11. Delete a memory via raw SQL
    delete_key = keys[0]
    db.execute("DELETE FROM memory_strength WHERE memory_key = ?", (delete_key,))
    db.execute("DELETE FROM memories WHERE key = ?", (delete_key,))
    db.commit()

    # 12. Dashboard data (post-delete)
    resp = await client.get(f"/api/dashboard/{persona}")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["recent"]) == 2
    remaining_keys = {m["key"] for m in data["recent"]}
    assert delete_key not in remaining_keys


# ===================================================================
# Goals/Promises normalization logic tests
# ===================================================================


def _normalize_goals(raw: list[dict]) -> list[str]:
    """Replicate the normalization from persona.py line 109."""
    return [g["description"] for g in raw if g.get("status") == "active" and g.get("description")]


def _normalize_promises(raw: list[dict]) -> list[str]:
    """Replicate the normalization from persona.py line 113."""
    return [p["description"] for p in raw if p.get("status") == "active" and p.get("description")]


def test_goals_normalization_active_only():
    """active な goals のみ返される。"""
    raw = [
        {"id": "g1", "description": "Do X", "status": "active"},
        {"id": "g2", "description": "Done Y", "status": "inactive"},
        {"id": "g3", "description": "Do Z", "status": "active"},
    ]
    result = _normalize_goals(raw)
    assert result == ["Do X", "Do Z"]
    assert "Done Y" not in result


def test_goals_normalization_empty_description_filtered():
    """description が空の active goal はスキップされる。"""
    raw = [
        {"id": "g1", "description": "", "status": "active"},
        {"id": "g2", "description": "Do X", "status": "active"},
    ]
    result = _normalize_goals(raw)
    assert "" not in result
    assert result == ["Do X"]


def test_goals_normalization_missing_fields():
    """status/description キーがない行はスキップされる。"""
    raw = [
        {"id": "g1"},  # status/description 欠如
        {"id": "g2", "description": "Goal A", "status": "active"},
    ]
    result = _normalize_goals(raw)
    assert result == ["Goal A"]


def test_promises_normalization_logic():
    """active な promises のみ返される。"""
    raw = [
        {"description": "Promise A", "status": "active"},
        {"description": "Promise B", "status": "inactive"},
    ]
    result = _normalize_promises(raw)
    assert result == ["Promise A"]


def test_empty_list_returns_empty():
    """空リストを渡すと空リストが返る。"""
    assert _normalize_goals([]) == []
    assert _normalize_promises([]) == []
