"""v2 images セクションが v1 の画像情報と完全一致することを固定する。

prompt enrichment は messages 表の走査を filename IN (..) の 20 件に絞る。
表の JSON 整形（空白の有無）に依存しないこと、filename 重複は後勝ちである
ことをここで押さえる。
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
from pathlib import Path
from unittest.mock import patch

import httpx
import pytest

from nous.application.use_cases import AppContextRegistry
from nous.config.runtime_config import RuntimeConfigManager
from nous.infrastructure.persona_layout import persona_media_dir
from nous.main import create_app

PERSONA = "v2img"


@pytest.fixture()
def tmp_data_dir():
    d = tempfile.mkdtemp(prefix="memorymcp_v2img_")
    yield d
    shutil.rmtree(d, ignore_errors=True)


@pytest.fixture()
def _reset_singletons():
    AppContextRegistry.close_all()
    AppContextRegistry._settings = None
    RuntimeConfigManager.reset()
    import nous.config.settings as _s

    _s.get_settings.cache_clear()
    yield
    AppContextRegistry.close_all()
    AppContextRegistry._settings = None
    RuntimeConfigManager.reset()
    _s.get_settings.cache_clear()


@pytest.fixture()
async def client(tmp_data_dir, _auto_persona_dirs):
    env_overrides = {
        "NOUS_DATA_ROOT": tmp_data_dir,
        "NOUS_SERVER__HOST": "127.0.0.1",
        "NOUS_SERVER__PORT": "19999",
        "NOUS_QDRANT__URL": "http://localhost:1",
        "NOUS_LOG_LEVEL": "WARNING",
        "NOUS_IMPORT_DIR": "",
    }
    with patch.dict(os.environ, env_overrides, clear=False):
        starlette_app = create_app().streamable_http_app()
        transport = httpx.ASGITransport(app=starlette_app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as ac:
            yield ac


def _ctx(persona: str = PERSONA):
    return AppContextRegistry.get(persona)


def _images_dir(persona: str = PERSONA) -> Path:
    from nous.config.settings import get_settings

    d = Path(persona_media_dir(get_settings().data_root, persona)) / "images"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _make_images(names: list[str], persona: str = PERSONA) -> None:
    d = _images_dir(persona)
    for i, name in enumerate(names):
        p = d / name
        p.write_bytes(b"\x89PNG\r\n\x1a\n" + bytes([i % 256]))
        os.utime(p, (1_700_000_000 + i, 1_700_000_000 + i))


def _messages_table(persona: str = PERSONA) -> None:
    db = _ctx(persona).connection.get_memory_db()
    db.execute("CREATE TABLE IF NOT EXISTS messages (metadata TEXT)")
    db.commit()


def _add_message_meta(meta: dict | str, persona: str = PERSONA, compact: bool = False) -> None:
    db = _ctx(persona).connection.get_memory_db()
    if isinstance(meta, str):
        raw = meta
    else:
        raw = json.dumps(meta, separators=(",", ":")) if compact else json.dumps(meta)
    db.execute("INSERT INTO messages (metadata) VALUES (?)", (raw,))
    db.commit()


def _triples(images: list[dict]) -> list[tuple]:
    return [(i["filename"], i["revised_prompt"], i["negative_prompt"]) for i in images]


@pytest.mark.asyncio
async def test_images_match_v1_exactly(client):
    _messages_table()
    _make_images(["a.png", "self_0001.png", "b.png"])
    _add_message_meta({"type": "image_generation", "filename": "a.png", "prompt": "revised A", "negative_prompt": "neg A"})
    _add_message_meta({"type": "image_generation", "filename": "b.png", "prompt": "old B", "negative_prompt": "old N"})
    _add_message_meta({"type": "image_generation", "filename": "b.png", "prompt": "new B", "negative_prompt": "new N"}, compact=True)
    _add_message_meta({"type": "text", "filename": "a.png", "prompt": "must be ignored"})
    _add_message_meta("{not json")

    v1 = (await client.get("/api/dashboard/" + PERSONA)).json()
    v2 = (await client.get("/api/v2/images/" + PERSONA)).json()

    assert _triples(v2["generated_images"]) == _triples(v1["generated_images"])
    assert [t[1] for t in _triples(v2["generated_images"]) if t[0] == "b.png"] == ["new B"]
    assert v2["latest_self_portrait"] == v1["latest_self_portrait"]


@pytest.mark.asyncio
async def test_images_are_capped_at_20_and_urls_are_signed_paths(client):
    names = ["img_%02d.png" % i for i in range(25)]
    _make_images(names)
    v2 = (await client.get("/api/v2/images/" + PERSONA)).json()
    assert len(v2["generated_images"]) == 20
    for img in v2["generated_images"]:
        assert img["url"] == "/api/chat/%s/persona/images/%s" % (PERSONA, img["filename"])


@pytest.mark.asyncio
async def test_images_enrichment_only_scans_reported_files(client):
    _messages_table()
    _make_images(["kept.png"])
    # 一覧に出ないファイルの prompt は引かない（20 件限定の IN 走査）
    _add_message_meta({"type": "image_generation", "filename": "not_listed.png", "prompt": "ghost"})
    _add_message_meta({"type": "image_generation", "filename": "kept.png", "prompt": "kept prompt"})
    v2 = (await client.get("/api/v2/images/" + PERSONA)).json()
    assert _triples(v2["generated_images"]) == [("kept.png", "kept prompt", "")]


@pytest.mark.asyncio
async def test_images_status_matches_v1_for_unknown_persona(client):
    v2 = await client.get("/api/v2/images/no_such_persona_xyz")
    v1 = await client.get("/api/dashboard/no_such_persona_xyz")
    assert v2.status_code == v1.status_code
