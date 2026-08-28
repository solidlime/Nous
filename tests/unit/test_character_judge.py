"""tests/unit/test_character_judge.py"""

import pytest

from nous.application.chat.character_judge import _parse_judgment, judge_character


def test_parse_judgment_valid():
    assert _parse_judgment('{"violation": "tone", "detail": "口調が崩れている"}') == {
        "violation": "tone",
        "detail": "口調が崩れている",
    }


def test_parse_judgment_code_fence():
    text = '```json\n{"violation": "compliance", "detail": "過剰に従順"}\n```'
    assert _parse_judgment(text)["violation"] == "compliance"


def test_parse_judgment_invalid_violation():
    assert _parse_judgment('{"violation": "unknown_kind", "detail": "x"}') is None


def test_parse_judgment_broken_json():
    assert _parse_judgment("not json at all") is None


def test_parse_judgment_none_violation():
    assert _parse_judgment('{"violation": "none", "detail": ""}') == {"violation": "none", "detail": ""}


@pytest.mark.asyncio
async def test_judge_skips_empty_response():
    assert await judge_character(config=None, persona_identity="x", response="") is None


@pytest.mark.asyncio
async def test_judge_provider_failure_returns_none(monkeypatch):
    class _Config:
        provider = "test"
        extract_model = "m"

        def get_effective_api_key(self):
            return "key"

        def get_effective_model(self):
            return "m"

        def get_effective_base_url(self):
            return ""

    from nous.application.chat import character_judge as cj

    def _boom(*a, **k):
        raise RuntimeError("no provider")

    monkeypatch.setattr(cj, "get_provider", _boom)
    assert await judge_character(_Config(), "persona定義", "応答") is None
