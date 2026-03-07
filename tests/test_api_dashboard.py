"""
/api/dashboard/* エンドポイントの統合テスト。

lifespan はconftest.py で空に差し替えているため、
AgentLoop / Discord Bot は起動しない。
"""

import sys
sys.path.insert(0, "D:/VSCode/Nous")


def test_dashboard_stats(client):
    response = client.get("/api/dashboard/stats")
    assert response.status_code in (200, 401, 422)


def test_dashboard_all_stats(client):
    response = client.get("/api/dashboard/all_stats")
    assert response.status_code in (200, 401, 422)


def test_dashboard_recent_memories(client):
    response = client.get("/api/dashboard/recent_memories")
    assert response.status_code in (200, 401, 422)


def test_health_endpoint_returns_ok(client):
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data.get("status") == "ok"
    assert "service" in data
