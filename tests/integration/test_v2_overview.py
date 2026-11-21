"""v2 分割 API（overview / recent / セクション）の統合テスト。

v1 /api/dashboard/{persona} の形を変えていないことの回帰もここで押さえる。
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
from datetime import timedelta
from unittest.mock import patch

import httpx
import pytest

from nous.application.use_cases import AppContextRegistry
from nous.config.runtime_config import RuntimeConfigManager
from nous.domain.shared.time_utils import format_iso, get_now
from nous.main import create_app

PERSONA = "v2persona"


@pytest.fixture()
def tmp_data_dir():
    d = tempfile.mkdtemp(prefix="memorymcp_v2_")
    yield d
    shutil.rmtree(d, ignore_errors=True)


@pytest.fixture()
def _reset_singletons():
    AppContextRegistry.close_all()
    AppContextRegistry._settings = None
    RuntimeConfigManager.reset()
    import nous.config.settings as _s

    _s.get_settings.cache_clear()
    yield
    AppContextRegistry.close_all()
    AppContextRegistry._settings = None
    RuntimeConfigManager.reset()
    _s.get_settings.cache_clear()


@pytest.fixture()
async def client(tmp_data_dir, _auto_persona_dirs):
    env_overrides = {
        "NOUS_DATA_ROOT": tmp_data_dir,
        "NOUS_SERVER__HOST": "127.0.0.1",
        "NOUS_SERVER__PORT": "19999",
        "NOUS_QDRANT__URL": "http://localhost:1",
        "NOUS_LOG_LEVEL": "WARNING",
        "NOUS_IMPORT_DIR": "",
    }
    with patch.dict(os.environ, env_overrides, clear=False):
        starlette_app = create_app().streamable_http_app()
        transport = httpx.ASGITransport(app=starlette_app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as ac:
            yield ac


def _db(persona: str = PERSONA):
    return AppContextRegistry.get(persona).connection.get_memory_db()


def _seed_memories(n: int, persona: str = PERSONA) -> list[str]:
    db = _db(persona)
    keys = []
    for i in range(n):
        now = format_iso(get_now() - timedelta(hours=n - i))
        key = "v2_mem_%03d" % i
        db.execute(
            """INSERT OR REPLACE INTO memories
               (key, content, created_at, updated_at, tags, importance,
                emotion, emotion_intensity, privacy_level)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (key, "v2 テスト記憶 %d" % i, now, now, json.dumps(["test"]), 0.5, "joy", 0.5, "internal"),
        )
        keys.append(key)
    db.commit()
    return keys


def _seed_wiki(pages: int = 3, project: str = "alpha", persona: str = PERSONA) -> None:
    from nous.config.settings import get_settings
    from nous.infrastructure.wiki.store import WikiStore

    store = WikiStore(get_settings().data_root, persona)
    for i in range(pages):
        store.write_page("v2-page-%d" % i, "V2 Page %d" % i, "本文", project=project if i % 2 == 0 else None)


# ---------------------------------------------------------------------------
# overview
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_overview_has_kpi_but_no_heavy_sections(client):
    _seed_memories(3)
    r = await client.get("/api/v2/overview/" + PERSONA)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["persona"] == PERSONA
    assert data["stats"]["total_count"] == 3
    assert "pages" in data["wiki"] and "projects" in data["wiki"]
    for heavy in ("recent", "blocks", "items", "equipment", "generated_images", "latest_self_portrait"):
        assert heavy not in data, heavy


@pytest.mark.asyncio
async def test_overview_is_under_2kb(client):
    _seed_memories(3)
    _seed_wiki(pages=5)
    r = await client.get("/api/v2/overview/" + PERSONA)
    assert r.status_code == 200
    assert len(r.content) < 2048, len(r.content)


@pytest.mark.asyncio
async def test_overview_wiki_counts_match_wiki_endpoint(client):
    _seed_wiki(pages=4, project="alpha")
    ov = (await client.get("/api/v2/overview/" + PERSONA)).json()
    pages = (await client.get("/api/wiki/" + PERSONA)).json()["pages"]
    assert ov["wiki"]["pages"] == len(pages)
    assert ov["wiki"]["projects"] == len({p["project"] for p in pages if (p["project"] or "").strip()})


@pytest.mark.asyncio
async def test_overview_status_matches_v1_for_unknown_persona(client):
    v2 = await client.get("/api/v2/overview/no_such_persona_xyz")
    v1 = await client.get("/api/dashboard/no_such_persona_xyz")
    assert v2.status_code == v1.status_code


# ---------------------------------------------------------------------------
# recent
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_recent_defaults_to_10(client):
    _seed_memories(15)
    data = (await client.get("/api/v2/recent/" + PERSONA)).json()
    assert len(data["recent"]) == 10


@pytest.mark.asyncio
async def test_recent_limit_is_capped_at_50(client):
    _seed_memories(60)
    data = (await client.get("/api/v2/recent/" + PERSONA, params={"limit": 200})).json()
    assert len(data["recent"]) == 50


@pytest.mark.asyncio
async def test_recent_full_matches_v1_shape(client):
    _seed_memories(2)
    slim = (await client.get("/api/v2/recent/" + PERSONA)).json()["recent"][0]
    full = (await client.get("/api/v2/recent/" + PERSONA, params={"full": 1})).json()["recent"][0]
    v1 = (await client.get("/api/dashboard/" + PERSONA)).json()["recent"][0]
    assert set(full) == set(v1)
    assert set(slim) < set(full)


@pytest.mark.asyncio
async def test_v1_dashboard_keeps_50_recent_and_all_sections(client):
    _seed_memories(60)
    data = (await client.get("/api/dashboard/" + PERSONA)).json()
    assert len(data["recent"]) == 50
    for key in (
        "stats",
        "context",
        "recent",
        "blocks",
        "equipment",
        "items",
        "goals",
        "relationship_highlights",
        "state_memories",
        "latest_self_portrait",
        "generated_images",
    ):
        assert key in data, key


# ---------------------------------------------------------------------------
# sections
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sections_carry_only_their_own_key(client):
    _seed_memories(1)
    blocks = (await client.get("/api/v2/blocks/" + PERSONA)).json()
    items = (await client.get("/api/v2/items/" + PERSONA)).json()
    equipment = (await client.get("/api/v2/equipment/" + PERSONA)).json()
    goals = (await client.get("/api/v2/goals/" + PERSONA)).json()
    assert set(blocks) == {"persona", "blocks"}
    assert set(items) == {"persona", "items"}
    assert set(equipment) == {"persona", "equipment"}
    assert set(goals) == {"persona", "goals"}


@pytest.mark.asyncio
async def test_sections_status_matches_v1_for_unknown_persona(client):
    v1 = (await client.get("/api/dashboard/no_such_persona_xyz")).status_code
    for name in ("blocks", "equipment", "items", "goals", "images"):
        r = await client.get("/api/v2/%s/no_such_persona_xyz" % name)
        assert r.status_code == v1, name
