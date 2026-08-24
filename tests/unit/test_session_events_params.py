"""session_events ルータのクエリパラメータパース単体テスト。"""

import pytest

from nous.api.http.routers.session_events import _parse_int_param

pytestmark = pytest.mark.unit


def test_valid_int_parsed():
    assert _parse_int_param({"limit": "10"}, "limit", 50) == 10


def test_invalid_value_falls_back_to_default():
    """?limit=abc でも 500 にならずデフォルトにフォールバック"""
    assert _parse_int_param({"limit": "abc"}, "limit", 50) == 50
    assert _parse_int_param({"offset": ""}, "offset", 0) == 0


def test_missing_key_uses_default():
    assert _parse_int_param({}, "limit", 50) == 50
