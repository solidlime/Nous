"""tests/unit/test_expression.py"""

from pathlib import Path

from nous.application.chat.expression import (
    expression_image_path,
    is_valid_emotion_label,
    resolve_expression_url,
    save_expression_image,
)


def test_emotion_label_validation(tmp_path, monkeypatch):
    monkeypatch.setattr("nous.application.chat.expression.get_settings", lambda: _fake_settings(tmp_path))
    assert is_valid_emotion_label("joy") is True
    assert is_valid_emotion_label("happy_joy") is True
    assert is_valid_emotion_label("../etc") is False
    assert is_valid_emotion_label("") is False
    assert is_valid_emotion_label("Joy!") is False


def test_resolve_missing_returns_none(tmp_path, monkeypatch):
    monkeypatch.setattr("nous.application.chat.expression.get_settings", lambda: _fake_settings(tmp_path))
    assert resolve_expression_url("herta", "joy") is None


def test_save_and_resolve_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr("nous.application.chat.expression.get_settings", lambda: _fake_settings(tmp_path))
    url = save_expression_image("herta", "joy", b"PNG")
    assert url == "/api/chat/herta/persona/images/expr_joy.png"
    assert resolve_expression_url("herta", "joy") == url
    assert expression_image_path("herta", "joy").name == "expr_joy.png"


class _FakeSettings:
    data_root = ""  # set in fixture


def _fake_settings(tmp_path: Path):
    s = _FakeSettings()
    s.data_root = str(tmp_path)
    return s
