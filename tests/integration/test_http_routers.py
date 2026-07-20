"""Integration tests for HTTP routers — covers routes not in test_http_api.py.

Routes exercised here:
  memory.py  : blocks (GET/POST/DELETE), recent (GET), strengths (GET)
  persona.py : dashboard (/  /dashboard/{p}  /api/dashboard/{p}),
               create/delete persona, profile update
  search.py  : emotions (GET), graph (GET)
  admin.py   : settings (GET/PUT/status), rebuild (503 path), export (GET)
  item.py    : add/equip/unequip/update/delete items
  deps.py    : persona resolution via Bearer token and X-Persona header
"""

from __future__ import annotations

import os
import shutil
import tempfile
from unittest.mock import patch

import httpx
import pytest

from nous.application.use_cases import AppContextRegistry
from nous.config.runtime_config import RuntimeConfigManager
from nous.main import create_app

# ---------------------------------------------------------------------------
# Fixtures — identical pattern to test_http_api.py
# ---------------------------------------------------------------------------


@pytest.fixture()
def tmp_data_dir():
    d = tempfile.mkdtemp(prefix="memorymcp_routers_")
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
async def client(tmp_data_dir, _reset_singletons):
    """AsyncClient backed by a fresh Nous app (Qdrant intentionally offline)."""
    env_overrides = {
        "NOUS_DATA_ROOT": tmp_data_dir,
        "NOUS_SERVER__HOST": "127.0.0.1",
        "NOUS_SERVER__PORT": "19997",
        "NOUS_QDRANT__URL": "http://localhost:1",  # unreachable
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


PERSONA = "router_test"


# ---------------------------------------------------------------------------
# deps.py — persona resolution via HTTP headers
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestPersonaResolution:
    """_resolve_persona_from_request: Bearer token / X-Persona header / path param."""

    async def test_path_param_resolves_persona(self, client):
        resp = await client.get(f"/api/dashboard/{PERSONA}")
        assert resp.status_code == 200

    async def test_bearer_token_accepted(self, client):
        """Bearer token persona is accepted; /health has no path persona param."""
        resp = await client.get("/health", headers={"Authorization": "Bearer bearer_persona"})
        assert resp.status_code == 200

    async def test_x_persona_header_accepted(self, client):
        resp = await client.get("/health", headers={"X-Persona": "xpersona_test"})
        assert resp.status_code == 200

    async def test_path_param_overrides_header(self, client):
        """Path parameter takes priority over X-Persona header."""
        resp = await client.get(
            f"/api/dashboard/{PERSONA}",
            headers={"X-Persona": "other_persona"},
        )
        assert resp.status_code == 200
        # The returned stats belong to PERSONA, not "other_persona"


# ---------------------------------------------------------------------------
# memory.py — blocks endpoints
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestBlocksEndpoints:
    """GET / POST / DELETE /api/blocks/{persona}."""

    async def test_list_blocks_empty(self, client):
        resp = await client.get(f"/api/blocks/{PERSONA}")
        assert resp.status_code == 200
        data = resp.json()
        assert "blocks" in data
        assert isinstance(data["blocks"], list)

    async def test_create_block_ok(self, client):
        resp = await client.post(
            f"/api/blocks/{PERSONA}",
            json={"block_name": "test_block", "content": "block content"},
        )
        assert resp.status_code == 200
        assert resp.json().get("ok") is True
        assert resp.json().get("block_name") == "test_block"

    async def test_create_block_missing_block_name(self, client):
        resp = await client.post(f"/api/blocks/{PERSONA}", json={"content": "no name"})
        assert resp.status_code == 400

    async def test_create_block_missing_content(self, client):
        resp = await client.post(f"/api/blocks/{PERSONA}", json={"block_name": "noname"})
        assert resp.status_code == 400

    async def test_delete_block_ok(self, client):
        await client.post(
            f"/api/blocks/{PERSONA}",
            json={"block_name": "del_block", "content": "to delete"},
        )
        resp = await client.delete(f"/api/blocks/{PERSONA}/del_block")
        assert resp.status_code == 200
        assert resp.json().get("ok") is True

    async def test_list_blocks_after_create(self, client):
        await client.post(
            f"/api/blocks/{PERSONA}",
            json={"block_name": "visible_block", "content": "listed"},
        )
        resp = await client.get(f"/api/blocks/{PERSONA}")
        assert resp.status_code == 200
        blocks = resp.json()["blocks"]
        # block names may be returned as strings or dicts
        names = [b if isinstance(b, str) else b.get("block_name", "") for b in blocks]
        assert "visible_block" in names


# ---------------------------------------------------------------------------
# memory.py — recent endpoint (replaced by /api/observations with mode=recent)
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestObservationsRecentEndpoint:
    """GET /api/observations/{persona}?mode=recent replaces /api/recent/{persona}."""

    async def test_recent_empty(self, client):
        resp = await client.get(f"/api/observations/{PERSONA}?mode=recent")
        assert resp.status_code == 200
        data = resp.json()
        assert "memories" in data
        assert isinstance(data["memories"], list)

    async def test_recent_includes_created_memory(self, client):
        await client.post(f"/api/memories/{PERSONA}", json={"content": "recent test"})
        resp = await client.get(f"/api/observations/{PERSONA}?mode=recent")
        assert resp.status_code == 200
        assert len(resp.json()["memories"]) >= 1

    async def test_recent_per_page_param(self, client):
        for i in range(5):
            await client.post(f"/api/memories/{PERSONA}", json={"content": f"mem {i}"})
        resp = await client.get(f"/api/observations/{PERSONA}?mode=recent&per_page=2")
        assert resp.status_code == 200
        assert len(resp.json()["memories"]) <= 2

    async def test_recent_invalid_per_page_type(self, client):
        resp = await client.get(f"/api/observations/{PERSONA}?mode=recent&per_page=abc")
        assert resp.status_code == 400

    async def test_recent_per_page_too_large(self, client):
        resp = await client.get(f"/api/observations/{PERSONA}?mode=recent&per_page=9999")
        assert resp.status_code == 400

    async def test_recent_per_page_zero(self, client):
        resp = await client.get(f"/api/observations/{PERSONA}?mode=recent&per_page=0")
        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# memory.py — strengths endpoint
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestStrengthsEndpoint:
    """GET /api/strengths/{persona}."""

    async def test_strengths_empty_persona(self, client):
        resp = await client.get(f"/api/strengths/{PERSONA}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["persona"] == PERSONA
        assert "total" in data
        assert "histogram" in data
        assert isinstance(data["histogram"], list)
        assert len(data["histogram"]) == 10

    async def test_strengths_after_create(self, client):
        await client.post(f"/api/memories/{PERSONA}", json={"content": "strength test"})
        resp = await client.get(f"/api/strengths/{PERSONA}")
        assert resp.status_code == 200
        assert resp.json()["total"] >= 1

    async def test_strengths_histogram_ranges(self, client):
        resp = await client.get(f"/api/strengths/{PERSONA}")
        histogram = resp.json()["histogram"]
        assert histogram[0]["range"] == "0.0-0.1"
        assert histogram[9]["range"] == "0.9-1.0"
        for bucket in histogram:
            assert "range" in bucket
            assert "count" in bucket


# ---------------------------------------------------------------------------
# persona.py — dashboard endpoints
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestDashboardEndpoints:
    """GET /  GET /dashboard/{persona}  GET /api/dashboard/{persona}."""

    async def test_root_returns_html(self, client):
        resp = await client.get("/")
        assert resp.status_code == 200
        ct = resp.headers.get("content-type", "")
        assert "html" in ct.lower()

    async def test_dashboard_persona_returns_html(self, client):
        resp = await client.get(f"/dashboard/{PERSONA}")
        assert resp.status_code == 200
        ct = resp.headers.get("content-type", "")
        assert "html" in ct.lower()

    async def test_api_dashboard_returns_json(self, client):
        resp = await client.get(f"/api/dashboard/{PERSONA}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["persona"] == PERSONA

    async def test_api_dashboard_contains_required_keys(self, client):
        resp = await client.get(f"/api/dashboard/{PERSONA}")
        data = resp.json()
        for key in ("stats", "context", "recent", "blocks", "equipment", "items", "goals"):
            assert key in data, f"Missing key: {key}"

    async def test_api_dashboard_recent_populated_after_create(self, client):
        await client.post(f"/api/memories/{PERSONA}", json={"content": "dashboard mem"})
        resp = await client.get(f"/api/dashboard/{PERSONA}")
        assert resp.json()["stats"]["total_count"] >= 1
        assert len(resp.json()["recent"]) >= 1


# ---------------------------------------------------------------------------
# persona.py — persona CRUD
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestPersonaCRUD:
    """POST /api/personas  and  DELETE /api/personas/{persona}."""

    async def test_create_persona_ok(self, client):
        resp = await client.post("/api/personas", json={"name": "brand_new_persona"})
        assert resp.status_code == 201
        data = resp.json()
        assert data["status"] == "ok"
        assert data["persona"] == "brand_new_persona"

    async def test_create_persona_missing_name(self, client):
        resp = await client.post("/api/personas", json={})
        assert resp.status_code == 400

    async def test_create_persona_invalid_chars(self, client):
        resp = await client.post("/api/personas", json={"name": "invalid name!"})
        assert resp.status_code == 400

    async def test_create_persona_duplicate_returns_409(self, client):
        await client.post("/api/personas", json={"name": "dup_persona"})
        resp = await client.post("/api/personas", json={"name": "dup_persona"})
        assert resp.status_code == 409

    async def test_create_persona_invalid_json(self, client):
        resp = await client.post(
            "/api/personas",
            content=b"not json",
            headers={"content-type": "application/json"},
        )
        assert resp.status_code == 400

    async def test_delete_nonexistent_persona_returns_404(self, client):
        resp = await client.delete("/api/personas/does_not_exist_xyz")
        assert resp.status_code == 404

    async def test_create_then_delete_persona(self, client):
        await client.post("/api/personas", json={"name": "to_delete"})
        resp = await client.delete("/api/personas/to_delete")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"
        assert resp.json()["deleted"] == "to_delete"


# ---------------------------------------------------------------------------
# persona.py — profile update
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestPersonaProfileUpdate:
    """PUT /api/personas/{persona}/profile."""

    async def test_update_user_info(self, client):
        resp = await client.put(
            f"/api/personas/{PERSONA}/profile",
            json={"user_info": {"name": "テストユーザー"}},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert "user_info" in data["updated"]

    async def test_update_relationship_status(self, client):
        resp = await client.put(
            f"/api/personas/{PERSONA}/profile",
            json={"relationship_status": "friend"},
        )
        assert resp.status_code == 200
        assert "relationship_status" in resp.json()["updated"]

    async def test_update_persona_info(self, client):
        resp = await client.put(
            f"/api/personas/{PERSONA}/profile",
            json={"persona_info": {"nickname": "ヘルタ"}},
        )
        assert resp.status_code == 200
        assert "persona_info" in resp.json()["updated"]

    async def test_update_profile_no_valid_fields(self, client):
        resp = await client.put(
            f"/api/personas/{PERSONA}/profile",
            json={"unknown_field": "value"},
        )
        assert resp.status_code == 400

    async def test_update_profile_invalid_json(self, client):
        resp = await client.put(
            f"/api/personas/{PERSONA}/profile",
            content=b"not json",
            headers={"content-type": "application/json"},
        )
        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# search.py — emotion history
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestEmotionHistoryEndpoint:
    """GET /api/emotions/{persona}."""

    async def test_emotion_history_empty(self, client):
        resp = await client.get(f"/api/emotions/{PERSONA}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["persona"] == PERSONA
        assert "history" in data
        assert isinstance(data["history"], dict)

    async def test_emotion_history_default_days(self, client):
        resp = await client.get(f"/api/emotions/{PERSONA}")
        assert resp.json()["days"] == 7

    async def test_emotion_history_custom_days(self, client):
        resp = await client.get(f"/api/emotions/{PERSONA}?days=30")
        assert resp.status_code == 200
        assert resp.json()["days"] == 30

    async def test_emotion_history_invalid_days(self, client):
        resp = await client.get(f"/api/emotions/{PERSONA}?days=xyz")
        assert resp.status_code == 400

    async def test_emotion_history_days_too_large(self, client):
        resp = await client.get(f"/api/emotions/{PERSONA}?days=999")
        assert resp.status_code == 400

    async def test_emotion_history_days_zero(self, client):
        resp = await client.get(f"/api/emotions/{PERSONA}?days=0")
        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# search.py — graph
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestGraphEndpoint:
    """GET /api/graph/{persona}."""

    async def test_graph_empty_persona(self, client):
        resp = await client.get(f"/api/graph/{PERSONA}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["persona"] == PERSONA
        assert "nodes" in data
        assert "edges" in data
        assert isinstance(data["nodes"], list)
        assert isinstance(data["edges"], list)
        assert data["node_count"] == len(data["nodes"])
        assert data["edge_count"] == len(data["edges"])

    async def test_graph_nodes_populated_after_memories(self, client):
        for i in range(3):
            await client.post(
                f"/api/memories/{PERSONA}",
                json={"content": f"graph node {i}", "tags": ["gtag"]},
            )
        resp = await client.get(f"/api/graph/{PERSONA}")
        data = resp.json()
        assert data["node_count"] >= 3

    async def test_graph_shared_tag_creates_edges(self, client):
        for i in range(2):
            await client.post(
                f"/api/memories/{PERSONA}",
                json={"content": f"shared tag mem {i}", "tags": ["shared_tag"]},
            )
        resp = await client.get(f"/api/graph/{PERSONA}")
        data = resp.json()
        assert data["edge_count"] >= 1

    async def test_graph_limit_param(self, client):
        resp = await client.get(f"/api/graph/{PERSONA}?limit=5")
        assert resp.status_code == 200
        assert resp.json()["node_count"] <= 5

    async def test_graph_node_structure(self, client):
        await client.post(f"/api/memories/{PERSONA}", json={"content": "node struct test", "importance": 0.6})
        resp = await client.get(f"/api/graph/{PERSONA}")
        nodes = resp.json()["nodes"]
        if nodes:
            n = nodes[0]
            assert "key" in n
            assert "content" in n
            assert "tags" in n
            assert "importance" in n


# ---------------------------------------------------------------------------
# admin.py — settings
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestSettingsEndpoints:
    """GET /api/settings  PUT /api/settings  GET /api/settings/status."""

    async def test_get_settings_returns_dict(self, client):
        resp = await client.get("/api/settings")
        assert resp.status_code == 200
        assert isinstance(resp.json(), dict)

    async def test_settings_status_has_reload_status(self, client):
        resp = await client.get("/api/settings/status")
        assert resp.status_code == 200
        assert "reload_status" in resp.json()

    async def test_update_settings_missing_category(self, client):
        resp = await client.put("/api/settings", json={"key": "k", "value": "v"})
        assert resp.status_code == 400

    async def test_update_settings_missing_key(self, client):
        resp = await client.put("/api/settings", json={"category": "c", "value": "v"})
        assert resp.status_code == 400

    async def test_update_settings_invalid_json(self, client):
        resp = await client.put(
            "/api/settings",
            content=b"not json",
            headers={"content-type": "application/json"},
        )
        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# admin.py — rebuild (vector store offline → 503)
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestAdminRebuildEndpoint:
    """POST /api/admin/rebuild/{persona} — Qdrant offline returns 503."""

    async def test_rebuild_without_vector_store_returns_503(self, client):
        resp = await client.post(f"/api/admin/rebuild/{PERSONA}")
        assert resp.status_code == 503
        assert "unavailable" in resp.json()["error"].lower()


# ---------------------------------------------------------------------------
# admin.py — export
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestExportEndpoint:
    """GET /api/export/{persona}."""

    async def test_export_nonexistent_persona_returns_404(self, client):
        resp = await client.get("/api/export/totally_nonexistent_persona_xyz")
        assert resp.status_code == 404

    async def test_export_existing_persona_returns_zip(self, client):
        await client.post(f"/api/memories/{PERSONA}", json={"content": "export seed"})
        resp = await client.get(f"/api/export/{PERSONA}")
        assert resp.status_code == 200
        assert resp.headers.get("content-type") == "application/zip"
        content_disp = resp.headers.get("content-disposition", "")
        assert PERSONA in content_disp
        assert ".zip" in content_disp


# ---------------------------------------------------------------------------
# item.py — full CRUD + equip/unequip
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestItemEndpoints:
    """POST / PUT / DELETE /api/items/{persona}  and  equip/unequip."""

    async def test_add_item_ok(self, client):
        resp = await client.post(
            f"/api/items/{PERSONA}",
            json={"item_name": "白いドレス", "category": "clothing"},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["status"] == "ok"
        assert data["item_name"] == "白いドレス"

    async def test_add_item_missing_name(self, client):
        resp = await client.post(f"/api/items/{PERSONA}", json={"category": "clothing"})
        assert resp.status_code == 400

    async def test_add_item_invalid_json(self, client):
        resp = await client.post(
            f"/api/items/{PERSONA}",
            content=b"not json",
            headers={"content-type": "application/json"},
        )
        assert resp.status_code == 400

    async def test_added_item_appears_in_list(self, client):
        await client.post(f"/api/items/{PERSONA}", json={"item_name": "listed_item"})
        resp = await client.get(f"/api/items/{PERSONA}")
        names = [it.get("name") or it.get("item_name") for it in resp.json()["items"]]
        assert "listed_item" in names

    async def test_update_item_ok(self, client):
        await client.post(f"/api/items/{PERSONA}", json={"item_name": "update_me"})
        resp = await client.put(
            f"/api/items/{PERSONA}/update_me",
            json={"description": "updated description", "quantity": 2},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    async def test_update_item_no_valid_fields(self, client):
        await client.post(f"/api/items/{PERSONA}", json={"item_name": "nf_item"})
        resp = await client.put(
            f"/api/items/{PERSONA}/nf_item",
            json={"unknown_field": "value"},
        )
        assert resp.status_code == 400

    async def test_update_item_invalid_json(self, client):
        await client.post(f"/api/items/{PERSONA}", json={"item_name": "ij_item"})
        resp = await client.put(
            f"/api/items/{PERSONA}/ij_item",
            content=b"not json",
            headers={"content-type": "application/json"},
        )
        assert resp.status_code == 400

    async def test_delete_item_ok(self, client):
        await client.post(f"/api/items/{PERSONA}", json={"item_name": "to_delete_item"})
        resp = await client.delete(f"/api/items/{PERSONA}/to_delete_item")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"
        assert resp.json()["deleted"] == "to_delete_item"

    async def test_equip_items_ok(self, client):
        await client.post(f"/api/items/{PERSONA}", json={"item_name": "帽子", "category": "head"})
        resp = await client.post(
            f"/api/items/{PERSONA}/equip",
            json={"head": "帽子"},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"
        assert "head" in resp.json()["equipped"]

    async def test_equip_auto_add(self, client):
        """auto_add=True should create the item automatically if not in inventory."""
        resp = await client.post(
            f"/api/items/{PERSONA}/equip",
            json={"top": "新しいシャツ", "auto_add": True},
        )
        assert resp.status_code == 200

    async def test_equip_empty_body_returns_400(self, client):
        resp = await client.post(f"/api/items/{PERSONA}/equip", json={})
        assert resp.status_code == 400

    async def test_equip_invalid_json(self, client):
        resp = await client.post(
            f"/api/items/{PERSONA}/equip",
            content=b"not json",
            headers={"content-type": "application/json"},
        )
        assert resp.status_code == 400

    async def test_unequip_ok(self, client):
        await client.post(
            f"/api/items/{PERSONA}/equip",
            json={"head": "帽子", "auto_add": True},
        )
        resp = await client.post(
            f"/api/items/{PERSONA}/unequip",
            json={"slots": ["head"]},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"
        assert "head" in resp.json()["unequipped"]

    async def test_unequip_string_slot(self, client):
        """slots can be passed as a single string (coerced to list in router)."""
        resp = await client.post(
            f"/api/items/{PERSONA}/unequip",
            json={"slots": "head"},
        )
        assert resp.status_code == 200

    async def test_unequip_no_slots_returns_400(self, client):
        resp = await client.post(f"/api/items/{PERSONA}/unequip", json={})
        assert resp.status_code == 400

    async def test_unequip_invalid_json(self, client):
        resp = await client.post(
            f"/api/items/{PERSONA}/unequip",
            content=b"not json",
            headers={"content-type": "application/json"},
        )
        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# Dashboard state restoration helpers (moved from test_dashboard_state_restore)
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestDashboardStateRestoration:
    """Regression tests for dashboard state restoration helpers."""

    def test_dashboard_uses_consistent_persona_storage_helpers(self):
        """Persona persistence should use shared helpers instead of split localStorage keys."""
        base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        base_js_path = os.path.join(base_dir, "nous", "api", "http", "static", "base.js")
        with open(base_js_path) as f:
            js = f.read()

        assert "function getStoredPersona()" in js
        assert "function setStoredPersona(persona)" in js
        assert 'localStorage.setItem("selected_persona"' in js
        assert 'localStorage.setItem("mmcp-persona"' in js


@pytest.mark.integration
class TestEditMessageEndpoint:
    """PUT /api/chat/{persona}/sessions/{session_id}/messages/{msg_id}."""

    async def _create_persona_with_session(self, client, persona: str) -> tuple[str, str]:
        """Helper: create persona and insert a test message directly into session store.

        Returns (session_id, msg_id) tuple.
        """
        # Create persona via POST /api/personas
        resp = await client.post("/api/personas", json={"name": persona})
        assert resp.status_code in (200, 201), f"Expected 200/201, got {resp.status_code}: {resp.text[:200]}"

        # Insert a test message directly via the session store
        from nous.application.chat.service import _session_manager
        from nous.application.use_cases import AppContextRegistry

        ctx = AppContextRegistry.get(persona)
        assert ctx is not None, f"Context for '{persona}' not found"
        db = ctx.connection.get_memory_db()

        window = _session_manager.get_or_create(persona, "main", db=db)
        msg_id = window.add("user", "test message")
        window.flush()
        return "main", msg_id

    async def test_edit_message_ok(self, client):
        persona = "edit_test_ok"
        session_id, msg_id = await self._create_persona_with_session(client, persona)

        # Edit by msg_id
        resp = await client.put(
            f"/api/chat/{persona}/sessions/{session_id}/messages/{msg_id}",
            json={"content": "edited content"},
        )
        assert resp.status_code == 200
        result = resp.json()
        assert result["status"] == "ok"
        assert result["updated_message"]["content"] == "edited content"
        assert result["updated_message"]["role"] == "user"
        assert "id" in result["updated_message"]

        # Verify persistence
        resp = await client.get(f"/api/chat/{persona}/sessions/{session_id}")
        data = resp.json()
        assert data["messages"][0]["content"] == "edited content"
        assert data["messages"][0]["id"] == msg_id

    async def test_edit_message_not_found(self, client):
        persona = "edit_test_nf"
        await self._create_persona_with_session(client, persona)

        # Non-existent UUID
        fake_id = "00000000-0000-0000-0000-000000000000"
        resp = await client.put(
            f"/api/chat/{persona}/sessions/main/messages/{fake_id}",
            json={"content": "nope"},
        )
        assert resp.status_code == 404

    async def test_edit_message_empty_content(self, client):
        persona = "edit_test_empty"
        _, msg_id = await self._create_persona_with_session(client, persona)

        resp = await client.put(
            f"/api/chat/{persona}/sessions/main/messages/{msg_id}",
            json={"content": ""},
        )
        assert resp.status_code == 400

    async def test_edit_message_nonexistent_persona(self, client):
        resp = await client.put(
            "/api/chat/nonexistent/sessions/main/messages/00000000-0000-0000-0000-000000000000",
            json={"content": "test"},
        )
        assert resp.status_code == 404


@pytest.mark.integration
class TestRollbackEndpoint:
    """POST /api/chat/{persona}/sessions/{session_id}/rollback."""

    async def _create_session_with_messages(self, client, persona: str, count: int = 3) -> tuple[str, str]:
        """Helper: create persona and insert messages. Returns (session_id, last_msg_id)."""
        resp = await client.post("/api/personas", json={"name": persona})
        assert resp.status_code in (200, 201), f"Expected 200/201, got {resp.status_code}: {resp.text[:200]}"

        from nous.application.chat.service import _session_manager
        from nous.application.use_cases import AppContextRegistry

        ctx = AppContextRegistry.get(persona)
        assert ctx is not None, f"Context for '{persona}' not found"
        db = ctx.connection.get_memory_db()

        window = _session_manager.get_or_create(persona, "main", db=db)
        assert count > 0, "count must be positive"
        last_id = None
        for i in range(count):
            last_id = window.add("user" if i % 2 == 0 else "assistant", f"message {i}")
        assert last_id is not None
        window.flush()
        return "main", last_id

    async def test_rollback_ok(self, client):
        persona = "rollback_ok"
        session_id, last_id = await self._create_session_with_messages(client, persona, count=3)

        # Read session to get first message id
        resp = await client.get(f"/api/chat/{persona}/sessions/{session_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["messages"]) == 3
        first_msg_id = data["messages"][0]["id"]

        # Rollback to first message (keep only first, remove rest)
        resp = await client.post(
            f"/api/chat/{persona}/sessions/{session_id}/rollback",
            json={"from_id": first_msg_id},
        )
        assert resp.status_code == 200
        result = resp.json()
        assert "active_leaf_id" in result
        assert result["active_leaf_id"] == first_msg_id
        assert len(result["remaining_messages"]) == 1

    async def test_rollback_invalid_id(self, client):
        persona = "rollback_inv"
        session_id, _ = await self._create_session_with_messages(client, persona, count=2)

        fake_id = "99999999-9999-9999-9999-999999999999"
        resp = await client.post(
            f"/api/chat/{persona}/sessions/{session_id}/rollback",
            json={"from_id": fake_id},
        )
        # Non-existent ID should return 404
        assert resp.status_code == 404

    async def test_rollback_missing_persona(self, client):
        resp = await client.post(
            "/api/chat/nonexistent/sessions/main/rollback",
            json={"from_id": "00000000-0000-0000-0000-000000000000"},
        )
        assert resp.status_code == 404

    async def test_rollback_empty_from_id(self, client):
        """Empty from_id should be rejected."""
        resp = await client.post(
            "/api/chat/nonexistent/sessions/main/rollback",
            json={"from_id": ""},
        )
        assert resp.status_code == 400
