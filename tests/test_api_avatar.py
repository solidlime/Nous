"""
/api/avatar/* エンドポイントの統合テスト。
"""

import sys
sys.path.insert(0, "D:/VSCode/Nous")


def test_avatar_scan(client):
    response = client.get("/api/avatar/scan/test_persona")
    assert response.status_code in (200, 404)


def test_avatar_state(client):
    response = client.get("/api/avatar/state")
    assert response.status_code in (200, 401)


def test_avatar_vrm_info(client):
    response = client.get("/api/avatar/vrm/test_persona/info")
    assert response.status_code in (200, 404)
