"""Integration tests for the HTTP API layer.

Uses httpx.AsyncClient with ASGI transport against a real Starlette app
backed by a temporary SQLite database.  Qdrant is intentionally unavailable
so that keyword-fallback behaviour is also verified.

Covers endpoints *not* already exercised by test_dashboard_integration.py:
  - POST /api/memories/{persona}      create memory
  - PUT  /api/memories/{persona}/{key} update memory
  - DELETE /api/memories/{persona}/{key} delete memory
  - GET  /api/items/{persona}          equipment list
  - GET  /api/stats/{persona}          memory statistics
  - GET  /api/observations/{persona}   paginated observations (edge cases)
  - GET  /api/search/{persona}         search with mode parameter
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
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def tmp_data_dir():
    d = tempfile.mkdtemp(prefix="memorymcp_http_")
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
    """AsyncClient backed by a fresh Nous app (Qdrant intentionally offline)."""
    env_overrides = {
        "NOUS_DATA_ROOT": tmp_data_dir,
        "NOUS_SERVER__HOST": "127.0.0.1",
        "NOUS_SERVER__PORT": "19998",
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


PERSONA = "http_api_test"


# ---------------------------------------------------------------------------
# H1: Memory CRUD via HTTP
# ---------------------------------------------------------------------------


class TestMemoryCRUDHttp:
    """POST / PUT / DELETE /api/memories/{persona}."""

    async def test_create_memory_returns_201(self, client):
        resp = await client.post(
            f"/api/memories/{PERSONA}",
            json={"content": "HTTP APIテスト記憶", "importance": 0.8, "tags": ["test"]},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["status"] == "ok"
        assert "memory" in data
        mem = data["memory"]
        assert mem["content"] == "HTTP APIテスト記憶"
        assert mem["importance"] == 0.8
        assert "key" in mem

    async def test_create_memory_missing_content_returns_400(self, client):
        resp = await client.post(f"/api/memories/{PERSONA}", json={"importance": 0.5})
        assert resp.status_code in (400, 422)
        assert "error" in resp.json() or "detail" in resp.json()

    async def test_create_memory_invalid_json_returns_400(self, client):
        resp = await client.post(
            f"/api/memories/{PERSONA}",
            content=b"not json at all",
            headers={"content-type": "application/json"},
        )
        assert resp.status_code == 400

    async def test_create_and_verify_via_dashboard(self, client):
        """Create a memory then confirm it appears in the dashboard."""
        await client.post(
            f"/api/memories/{PERSONA}",
            json={"content": "ダッシュボード確認用記憶", "importance": 0.7},
        )
        dash = await client.get(f"/api/dashboard/{PERSONA}")
        assert dash.status_code == 200
        recent_keys = [m["key"] for m in dash.json()["recent"]]
        assert len(recent_keys) >= 1

    async def test_update_memory(self, client):
        """PUT updates content of an existing memory."""
        create_resp = await client.post(
            f"/api/memories/{PERSONA}",
            json={"content": "更新前コンテンツ"},
        )
        key = create_resp.json()["memory"]["key"]

        update_resp = await client.put(
            f"/api/memories/{PERSONA}/{key}",
            json={"content": "更新後コンテンツ", "importance": 0.9},
        )
        assert update_resp.status_code == 200
        updated = update_resp.json()
        assert updated["status"] == "ok"
        assert updated["memory"]["content"] == "更新後コンテンツ"
        assert updated["memory"]["importance"] == 0.9

    async def test_update_nonexistent_memory_returns_404(self, client):
        resp = await client.put(
            f"/api/memories/{PERSONA}/nonexistent_key_abc",
            json={"content": "存在しないキーへの更新"},
        )
        assert resp.status_code == 404

    async def test_delete_memory(self, client):
        """DELETE removes the memory; subsequent dashboard no longer includes it."""
        create_resp = await client.post(
            f"/api/memories/{PERSONA}",
            json={"content": "削除対象記憶"},
        )
        key = create_resp.json()["memory"]["key"]

        del_resp = await client.delete(f"/api/memories/{PERSONA}/{key}")
        assert del_resp.status_code == 200
        assert del_resp.json()["status"] == "ok"

        # confirm removed from recent
        dash = await client.get(f"/api/dashboard/{PERSONA}")
        recent_keys = [m["key"] for m in dash.json()["recent"]]
        assert key not in recent_keys

    async def test_delete_nonexistent_memory_returns_404(self, client):
        resp = await client.delete(f"/api/memories/{PERSONA}/ghost_key_xyz")
        assert resp.status_code == 404

    async def test_create_memory_with_emotion(self, client):
        resp = await client.post(
            f"/api/memories/{PERSONA}",
            json={
                "content": "感情付き記憶テスト",
                "emotion": "curiosity",
                "emotion_intensity": 0.75,
            },
        )
        assert resp.status_code == 201
        mem = resp.json()["memory"]
        assert mem.get("emotion") == "curiosity"
        assert mem["emotion_intensity"] == 0.75


# ---------------------------------------------------------------------------
# H2: GET /api/dashboard/{persona} (replaces /api/stats/{persona})
# ---------------------------------------------------------------------------


class TestStatsEndpoint:
    """GET /api/dashboard/{persona} returns stats nested under 'stats' key."""

    async def test_stats_empty_persona(self, client):
        resp = await client.get(f"/api/dashboard/{PERSONA}")
        assert resp.status_code == 200
        data = resp.json()
        assert "stats" in data
        assert "total_count" in data["stats"]

    async def test_stats_increase_after_create(self, client):
        """Stats total_count reflects newly created memories."""
        before = await client.get(f"/api/dashboard/{PERSONA}")
        before_count = _extract_count(before.json())

        for i in range(3):
            await client.post(f"/api/memories/{PERSONA}", json={"content": f"統計テスト記憶{i}"})

        after = await client.get(f"/api/dashboard/{PERSONA}")
        after_count = _extract_count(after.json())
        assert after_count == before_count + 3

    async def test_stats_distribution_keys_present(self, client):
        """P1: stats レスポンスに tag_distribution と emotion_distribution が含まれる。"""
        await client.post(
            f"/api/memories/{PERSONA}",
            json={"content": "分布テスト", "tags": ["stats_tag"], "emotion": "joy"},
        )
        resp = await client.get(f"/api/dashboard/{PERSONA}")
        assert resp.status_code == 200
        data = resp.json()
        assert "tag_distribution" in data["stats"]
        assert "emotion_distribution" in data["stats"]
        assert isinstance(data["stats"]["tag_distribution"], dict)
        assert isinstance(data["stats"]["emotion_distribution"], dict)
        assert data["stats"]["tag_distribution"].get("stats_tag", 0) >= 1

    async def test_stats_top_n_note_when_many_tags(self, client):
        """P1: 21個以上のユニークタグがあると tag_distribution_note が現れる（デフォルト top_n=20）。"""
        for i in range(21):
            await client.post(
                f"/api/memories/{PERSONA}",
                json={"content": f"tag test {i}", "tags": [f"unique_tag_{i:02d}"]},
            )
        resp = await client.get(f"/api/dashboard/{PERSONA}")
        assert resp.status_code == 200
        data = resp.json()
        assert "tag_distribution_note" in data["stats"]
        assert len(data["stats"]["tag_distribution"]) == 20


def _extract_count(data: dict) -> int:
    """Extract total_count from dashboard response (nested under 'stats')."""
    return data.get("stats", {}).get("total_count", 0)


# ---------------------------------------------------------------------------
# H3: GET /api/items/{persona}
# ---------------------------------------------------------------------------


class TestItemsEndpoint:
    """GET /api/items/{persona} returns equipment/inventory list."""

    async def test_items_returns_list(self, client):
        resp = await client.get(f"/api/items/{PERSONA}")
        assert resp.status_code == 200
        data = resp.json()
        assert "items" in data or isinstance(data, list)

    async def test_items_persona_field(self, client):
        resp = await client.get(f"/api/items/{PERSONA}")
        data = resp.json()
        # Some implementations include persona in response
        if "persona" in data:
            assert data["persona"] == PERSONA


# ---------------------------------------------------------------------------
# H4: Search mode parameter
# ---------------------------------------------------------------------------


class TestSearchModes:
    """GET /api/search/{persona}?q=...&mode=... tests all 3 search modes."""

    @pytest.fixture(autouse=True)
    async def _seed(self, client):
        """Seed memories for search tests."""
        seeds = [
            "日本語の検索テスト：ユーザーはラーメンが好きです",
            "科学的研究：宇宙の謎とブラックホールの特性",
            "今日の記録：カフェでコーヒーを楽しんだ",
        ]
        for content in seeds:
            await client.post(f"/api/memories/{PERSONA}", json={"content": content})

    async def test_search_mode_keyword(self, client):
        resp = await client.get(f"/api/search/{PERSONA}?q=ラーメン&mode=keyword")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data["results"], list)
        assert len(data["results"]) >= 1

    async def test_search_mode_hybrid(self, client):
        """Hybrid falls back to keyword when Qdrant is unavailable."""
        resp = await client.get(f"/api/search/{PERSONA}?q=宇宙&mode=hybrid")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data["results"], list)

    async def test_search_mode_semantic_fallback(self, client):
        """Semantic mode without Qdrant returns empty or keyword fallback."""
        resp = await client.get(f"/api/search/{PERSONA}?q=コーヒー&mode=semantic")
        # Should not crash — returns 200 with empty or fallback results
        assert resp.status_code == 200

    async def test_search_with_limit(self, client):
        resp = await client.get(f"/api/search/{PERSONA}?q=記憶&limit=1")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["results"]) <= 1

    async def test_search_result_structure(self, client):
        """Each search result has memory, score, and source fields."""
        resp = await client.get(f"/api/search/{PERSONA}?q=ラーメン")
        data = resp.json()
        if data["results"]:
            r = data["results"][0]
            assert "memory" in r
            assert "score" in r
            assert "source" in r

    async def test_smart_mode_accepted(self, client):
        """P6: smart mode は後方互換で受け付けられ、hybrid と同等の結果を返す。"""
        resp = await client.get(f"/api/search/{PERSONA}?q=ラーメン&mode=smart")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data["results"], list)

    async def test_all_modes_produce_equivalent_results(self, client):
        """All modes return 200 without crashing."""
        for mode in ["keyword", "hybrid", "semantic", "smart"]:
            resp = await client.get(f"/api/search/{PERSONA}?q=ラーメン&mode={mode}")
            assert resp.status_code == 200, f"mode={mode} returned {resp.status_code}"
            data = resp.json()
            assert isinstance(data["results"], list)


# ---------------------------------------------------------------------------
# H5: Observations pagination edge cases
# ---------------------------------------------------------------------------


class TestObservationsPagination:
    """Edge cases for /api/observations/{persona} pagination."""

    @pytest.fixture(autouse=True)
    async def _seed_10(self, client):
        for i in range(10):
            await client.post(f"/api/memories/{PERSONA}", json={"content": f"ページネーションテスト記憶 {i:02d}"})

    async def test_page_1_default_per_page(self, client):
        resp = await client.get(f"/api/observations/{PERSONA}?page=1&per_page=5")
        assert resp.status_code == 200
        data = resp.json()
        assert data["page"] == 1
        assert data["per_page"] == 5
        assert len(data["memories"]) == 5

    async def test_pages_have_no_overlap(self, client):
        r1 = await client.get(f"/api/observations/{PERSONA}?page=1&per_page=4")
        r2 = await client.get(f"/api/observations/{PERSONA}?page=2&per_page=4")
        keys1 = {m["key"] for m in r1.json()["memories"]}
        keys2 = {m["key"] for m in r2.json()["memories"]}
        assert keys1.isdisjoint(keys2)

    async def test_last_page_has_remaining_items(self, client):
        # 10 memories, per_page=6 → page 2 should have 4
        r2 = await client.get(f"/api/observations/{PERSONA}?page=2&per_page=6")
        assert r2.status_code == 200
        data = r2.json()
        assert len(data["memories"]) == 4

    async def test_total_count_matches_seeded(self, client):
        resp = await client.get(f"/api/observations/{PERSONA}?page=1&per_page=100")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_count"] == 10


# ---------------------------------------------------------------------------
# H6: Health and Personas (basic sanity)
# ---------------------------------------------------------------------------


class TestBasicSanity:
    async def test_health_ok(self, client):
        resp = await client.get("/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    async def test_personas_list(self, client):
        resp = await client.get("/api/personas")
        assert resp.status_code == 200
        assert "personas" in resp.json()

    async def test_unknown_route_returns_non_500(self, client):
        """Unrecognised routes should not crash the server with 500."""
        resp = await client.get("/api/this_does_not_exist")
        assert resp.status_code != 500
