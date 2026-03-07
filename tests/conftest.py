"""
Nous テスト共通フィクスチャ。

lifespan (AgentLoop / Discord / 忘却ワーカー等の重い初期化) は
テスト環境では不要なため、contextlib.nullcontext で差し替える。
"""

import os
import sys
import tempfile
from contextlib import asynccontextmanager

import pytest

# D:/VSCode/Nous をモジュール検索パスに追加
sys.path.insert(0, "D:/VSCode/Nous")


@pytest.fixture(scope="session")
def tmp_data_dir():
    with tempfile.TemporaryDirectory() as d:
        yield d


@pytest.fixture(scope="session")
def client(tmp_data_dir):
    # テスト用環境変数を設定
    os.environ["NOUS_DATA_DIR"] = tmp_data_dir
    os.environ["PERSONA"] = "test_persona"

    # lifespan を空のコンテキストマネージャに差し替えてテスト用 app を構築
    import main as nous_main

    @asynccontextmanager
    async def _noop_lifespan(app):
        yield

    # create_app() を呼ぶ前に lifespan を差し替え
    original_lifespan = nous_main.lifespan
    nous_main.lifespan = _noop_lifespan

    try:
        from fastapi.testclient import TestClient
        app = nous_main.create_app()
        yield TestClient(app, raise_server_exceptions=False)
    finally:
        nous_main.lifespan = original_lifespan
