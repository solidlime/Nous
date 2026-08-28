"""tests/unit/test_expression_batch.py"""

import pytest

from nous.api.http.routers.persona import persona_dashboard as pd


@pytest.mark.asyncio
async def test_batch_generates_missing_only(tmp_path, monkeypatch):
    monkeypatch.setattr("nous.application.chat.expression.get_settings", lambda: _fake_settings(tmp_path))
    generated: list[str] = []

    async def _fake_gen(config, persona, emotion):
        generated.append(emotion)
        return f"/api/chat/{persona}/persona/images/expr_{emotion}.png"

    monkeypatch.setattr(pd, "generate_expression_image", _fake_gen)
    # 既存の joy は skip されるよう事前保存
    (tmp_path / "persona" / "herta" / "images").mkdir(parents=True)
    (tmp_path / "persona" / "herta" / "images" / "expr_joy.png").write_bytes(b"PNG")

    result = await pd._generate_expression_set(config=None, persona="herta")
    assert "joy" in result["skipped"]
    assert set(result["generated"]) == set(generated) - {"joy"}
    assert result["failed"] == []


class _FakeSettings:
    data_root = ""


def _fake_settings(tmp_path):
    s = _FakeSettings()
    s.data_root = str(tmp_path)
    return s
