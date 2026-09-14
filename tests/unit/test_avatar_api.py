"""Router tests: VRM avatar model API (list / serve / upload)."""

from __future__ import annotations

import io
import os
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from starlette.datastructures import UploadFile
from starlette.responses import FileResponse

from nous.api.http.routers.chat.avatar_models import (
    _safe_model_name,
    _sample_model_path,
    list_avatar_models,
    serve_avatar_model,
    upload_avatar_model,
)

PERSONA = "itest"


@pytest.fixture
def avatar_env(tmp_path, monkeypatch):
    """data_root を tmp_path に向け、resolver をスタブする。"""
    import nous.api.http.routers.chat.avatar_models as avatar_mod
    import nous.config.settings as settings_mod

    monkeypatch.setattr(settings_mod, "get_settings", lambda: SimpleNamespace(data_root=str(tmp_path)))
    monkeypatch.setattr(avatar_mod, "get_settings", lambda: SimpleNamespace(data_root=str(tmp_path)))
    # リポジトリ直下 herta.vrm は実環境依存なので、テストでは常に「存在しない」ことにする
    monkeypatch.setattr(avatar_mod, "_herta_model_path", lambda: tmp_path / "__no_herta__.vrm")
    ctx = MagicMock()
    with (
        patch("nous.api.http.routers.chat.avatar_models._resolve_request", return_value=(PERSONA, ctx)),
        patch("nous.api.http.routers.chat.avatar_models._PERSONA_PATTERN", __import__("re").compile(r".*")),
    ):
        yield tmp_path / "persona" / PERSONA / "avatar"


def _upload_request(filename: str, content: bytes, field: str = "file"):
    upload = UploadFile(file=io.BytesIO(content), filename=filename)

    async def form():
        return {field: upload}

    req = MagicMock()
    req.form = form
    return req


class TestSafeModelName:
    def test_strips_traversal_and_keeps_basename(self):
        assert _safe_model_name("../../etc/passwd.vrm") == "passwd.vrm"

    def test_removes_unsafe_chars(self):
        assert _safe_model_name("my model (1)!.vrm") == "mymodel1.vrm"

    def test_japanese_stripped(self):
        assert _safe_model_name("モデル.vrm") == ".vrm"


class TestListModels:
    @pytest.mark.asyncio
    async def test_empty_when_dir_missing(self, avatar_env):
        resp = await list_avatar_models(MagicMock())
        assert resp.status_code == 200
        assert resp.body == b'{"models":[],"current":null,"default":"sample.vrm"}'

    @pytest.mark.asyncio
    async def test_lists_vrm_files_sorted(self, avatar_env):
        avatar_env.mkdir(parents=True)
        (avatar_env / "b.vrm").write_bytes(b"x")
        (avatar_env / "a.vrm").write_bytes(b"x")
        (avatar_env / "note.txt").write_bytes(b"x")  # VRM以外は除外
        resp = await list_avatar_models(MagicMock())
        assert resp.status_code == 200
        assert resp.body == b'{"models":["a.vrm","b.vrm"],"current":null,"default":"a.vrm"}'

    @pytest.mark.asyncio
    async def test_404_for_unknown_persona(self):
        req = MagicMock()
        with patch("nous.api.http.routers.chat.avatar_models._resolve_request", return_value=(PERSONA, None)):
            resp = await list_avatar_models(req)
        assert resp.status_code == 404


class TestServeModel:
    @pytest.mark.asyncio
    async def test_path_traversal_rejected_falls_back_to_sample(self, avatar_env):
        avatar_env.mkdir(parents=True)
        (avatar_env / "ok.vrm").write_bytes(b"x")
        for bad in ("..", "sub/..%2Fok.vrm", "/etc/passwd", "..%2F..%2Fsecret.vrm"):
            req = MagicMock()
            req.query_params = {"name": bad}
            resp = await serve_avatar_model(req)
            # トラバーサル名はすべて拒否され同梱 sample.vrm へフォールバック
            assert resp.status_code == 200, f"name={bad!r}"
            assert isinstance(resp, FileResponse)
            assert os.path.basename(resp.path) == "sample.vrm", f"name={bad!r}"
        # フォールバックはプロトタイプの sample.vrm を指す
        assert _sample_model_path().name == "sample.vrm"

    @pytest.mark.asyncio
    async def test_serves_existing_model(self, avatar_env):
        avatar_env.mkdir(parents=True)
        (avatar_env / "my.vrm").write_bytes(b"VRMDATA")
        req = MagicMock()
        req.query_params = {"name": "my.vrm"}
        resp = await serve_avatar_model(req)
        assert resp.status_code == 200
        assert isinstance(resp, FileResponse)
        assert os.path.basename(resp.path) == "my.vrm"

    @pytest.mark.asyncio
    async def test_missing_file_falls_back_to_sample(self, avatar_env):
        req = MagicMock()
        req.query_params = {"name": "nonexistent.vrm"}  # 既定解決: アップロード無し → sample

        resp = await serve_avatar_model(req)
        assert resp.status_code == 200
        assert isinstance(resp, FileResponse)
        assert os.path.basename(resp.path) == "sample.vrm"

    @pytest.mark.asyncio
    async def test_no_name_falls_back_to_sample(self, avatar_env):
        req = MagicMock()
        req.query_params = {}
        resp = await serve_avatar_model(req)
        assert resp.status_code == 200
        assert isinstance(resp, FileResponse)
        assert os.path.basename(resp.path) == "sample.vrm"


class TestUploadModel:
    @pytest.mark.asyncio
    async def test_upload_saves_and_overwrites(self, avatar_env):
        avatar_env.mkdir(parents=True)
        (avatar_env / "m.vrm").write_bytes(b"OLD")
        req = _upload_request("m.vrm", b"NEW")
        resp = await upload_avatar_model(req)
        assert resp.status_code == 200
        assert (avatar_env / "m.vrm").read_bytes() == b"NEW"

    @pytest.mark.asyncio
    async def test_upload_rejects_non_vrm(self, avatar_env):
        req = _upload_request("model.gltf", b"x")
        resp = await upload_avatar_model(req)
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_upload_sanitizes_filename(self, avatar_env):
        req = _upload_request("../../evil name!.vrm", b"x")
        resp = await upload_avatar_model(req)
        assert resp.status_code == 200
        names = [p.name for p in avatar_env.iterdir()]
        assert names == ["evilname.vrm"]

    @pytest.mark.asyncio
    async def test_upload_requires_file_field(self, avatar_env):
        async def form():
            return {}

        req = MagicMock()
        req.form = form
        resp = await upload_avatar_model(req)
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_upload_rejects_oversize(self, avatar_env, monkeypatch):
        import nous.api.http.routers.chat.avatar_models as mod

        monkeypatch.setattr(mod, "_MAX_VRM_BYTES", 10)
        req = _upload_request("big.vrm", b"x" * 11)
        resp = await upload_avatar_model(req)
        assert resp.status_code == 413
