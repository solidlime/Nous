"""Task 3: extractor hardening — garbage importance/tags fall back, never crash."""

from nous.application.chat.memory_extractor import normalize_importance, normalize_tags


def test_importance_garbage_falls_back():
    assert normalize_importance("high") == 0.6
    assert normalize_importance(None) == 0.6
    assert normalize_importance([]) == 0.6


def test_importance_bounds():
    assert normalize_importance(0.9) == 0.9
    assert normalize_importance(0) == 0.0
    assert normalize_importance(1) == 1.0
    assert normalize_importance(5.0) == 0.6
    assert normalize_importance(-0.1) == 0.6
    assert normalize_importance("0.7") == 0.7
    assert normalize_importance(True) == 0.6


def test_tags_string_does_not_substring_match():
    assert normalize_tags("character_drift,x") == ["auto_extract"]


def test_tags_shapes():
    assert normalize_tags(["a", " b ", "", None, 1]) == ["a", "b"]
    assert normalize_tags([]) == ["auto_extract"]
    assert normalize_tags(None) == ["auto_extract"]
    assert normalize_tags(["character_drift", "shift"]) == ["character_drift", "shift"]
