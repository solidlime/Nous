"""Default VRM model resolution order: repo-root herta.vrm → uploaded → sample.vrm."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

import nous.api.http.routers.chat.avatar_models as avatar_mod
from nous.api.http.routers.chat.avatar_models import _do_list_models, _do_resolve_default_model

PERSONA = "itest"


@pytest.fixture
def resolution_env(tmp_path, monkeypatch):
    """data_root を tmp_path に向け、herta.vrm / sample.vrm の所在をスタブする。"""
    monkeypatch.setattr(
        avatar_mod,
        "get_settings",
        lambda: SimpleNamespace(data_root=str(tmp_path / "data")),
    )
    monkeypatch.setattr(avatar_mod, "_herta_model_path", lambda: tmp_path / "herta.vrm")
    monkeypatch.setattr(avatar_mod, "_sample_model_path", lambda: tmp_path / "sample.vrm")
    return tmp_path


def _write(path, content=b"x"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


class TestResolveDefaultModel:
    def test_repo_root_herta_wins(self, resolution_env):
        _write(resolution_env / "herta.vrm", b"HERTA")
        _write(resolution_env / "data" / "persona" / PERSONA / "avatar" / "up.vrm")
        resolved = _do_resolve_default_model(PERSONA)
        assert resolved["filename"] == "herta.vrm"
        assert resolved["file_path"].endswith("herta.vrm")

    def test_uploaded_model_second(self, resolution_env):
        _write(resolution_env / "data" / "persona" / PERSONA / "avatar" / "up.vrm")
        resolved = _do_resolve_default_model(PERSONA)
        assert resolved["filename"] == "up.vrm"

    def test_sample_vrm_last(self, resolution_env):
        resolved = _do_resolve_default_model(PERSONA)
        assert resolved["filename"] == "sample.vrm"
        assert resolved["file_path"].endswith("sample.vrm")

    def test_missing_sample_file_still_returns_sample_entry(self, resolution_env):
        # ファイル実在チェックは serve 側の責務。resolver は解決結果だけ返す。
        resolved = _do_resolve_default_model(PERSONA)
        assert resolved["filename"] == "sample.vrm"


class TestListModels:
    def test_list_includes_served_default(self, resolution_env):
        _write(resolution_env / "herta.vrm")
        _write(resolution_env / "data" / "persona" / PERSONA / "avatar" / "up.vrm")
        result = _do_list_models(PERSONA)
        assert result["models"] == ["up.vrm"]
        assert result["current"] is None
        # 一覧が返す既定名は実際に配信されるモデル（herta.vrm）と一致する
        assert result["default"] == "herta.vrm"

    def test_list_default_follows_fallback(self, resolution_env):
        _write(resolution_env / "data" / "persona" / PERSONA / "avatar" / "up.vrm")
        result = _do_list_models(PERSONA)
        assert result["models"] == ["up.vrm"]
        assert result["default"] == "up.vrm"

    def test_list_empty_dir(self, resolution_env):
        result = _do_list_models(PERSONA)
        assert result == {"models": [], "current": None, "default": "sample.vrm"}
