"""tests/unit/test_expression_generation.py"""

import pytest

from nous.application.chat import expression as expr_mod


class _Img:
    def __init__(self, b64: str):
        self.base64 = b64
        self.display = True


class _Config:
    image_gen_enabled = True  # 生成が有効な persona 設定を最小再現


class _Provider:
    def __init__(self, png: bytes = b"PNGDATA"):
        self._png = png
        self.calls: list[dict] = []

    async def generate(self, **kwargs):
        self.calls.append(kwargs)

        class _R:
            def __init__(self, png):
                self.base64 = "UE5HREFUQQ=="  # b"PNGDATA"
                self.display = True

        return [_R(self._png)]


@pytest.mark.asyncio
async def test_generate_expression_saves_and_returns_url(tmp_path, monkeypatch):
    monkeypatch.setattr("nous.application.chat.expression.get_settings", lambda: _fake_settings(tmp_path))
    monkeypatch.setattr(expr_mod, "_build_provider", lambda config, size: _Provider())

    url = await expr_mod.generate_expression_image(config=_Config(), persona="herta", emotion="joy")
    assert url == "/api/chat/herta/persona/images/expr_joy.png"
    assert (tmp_path / "persona" / "herta" / "images" / "expr_joy.png").read_bytes() == b"PNGDATA"


@pytest.mark.asyncio
async def test_generate_expression_invalid_emotion_returns_none(tmp_path, monkeypatch):
    monkeypatch.setattr("nous.application.chat.expression.get_settings", lambda: _fake_settings(tmp_path))
    assert await expr_mod.generate_expression_image(config=_Config(), persona="herta", emotion="../x") is None


@pytest.mark.asyncio
async def test_generate_expression_provider_failure_returns_none(tmp_path, monkeypatch):
    monkeypatch.setattr("nous.application.chat.expression.get_settings", lambda: _fake_settings(tmp_path))

    class _Bad:
        async def generate(self, **kwargs):
            raise RuntimeError("comfyui down")

    monkeypatch.setattr(expr_mod, "_build_provider", lambda config, size: _Bad())
    assert await expr_mod.generate_expression_image(config=_Config(), persona="herta", emotion="joy") is None


class _FakeSettings:
    data_root = ""


def _fake_settings(tmp_path):
    s = _FakeSettings()
    s.data_root = str(tmp_path)
    return s
