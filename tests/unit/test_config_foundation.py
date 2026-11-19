"""Phase 0 基盤テスト（コンフィグ外部化 2026-11-20）。

oracle PLAN 審査指定の3テスト + session_silence_hours 改名の env 互換:
1. RCM.update の setattr が ctx.settings（AppContextRegistry）に届くこと
   — 従来は main.py:187 の Settings() と RCM の get_settings() が別
   インスタンスで、ホットリロードが ctx に届かなかった（審査 #1）。
2. UI の type=text 入力（文字列）がフィールド型へ coerce され、
   不正型は ValidationError → admin が 400（審査 #2）。
3. 非 hot キーの変更が「再起動後も」Settings に反映されること
   — 従来は overrides ファイルに保存されるだけで再起動でも効かなかった。
4. Settings.silence_hours → session_silence_hours 改名で旧 env 名が
   引き続き受理されること（審査 #11 の後方互換）。
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from nous.config.runtime_config import RuntimeConfigManager

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def _reset_singleton():
    RuntimeConfigManager.reset()
    yield
    RuntimeConfigManager.reset()


@pytest.fixture()
def shared_settings(tmp_path, monkeypatch):
    """RCM と AppContextRegistry が同一 Settings を掴む状態（Phase 0 の本番構成を模す）。"""
    from nous.config.settings import Settings, get_settings

    monkeypatch.delenv("NOUS_API_KEY", raising=False)
    get_settings.cache_clear()
    mock = Settings(data_root=str(tmp_path))
    with patch("nous.config.runtime_config.get_settings", return_value=mock):
        yield mock
    get_settings.cache_clear()


def test_hot_reload_reaches_ctx_settings(shared_settings):
    """RCM.update の setattr が configure 済み settings（= 全 ctx.settings の素）に届く。"""
    from nous.application.use_cases import AppContextRegistry

    AppContextRegistry.configure(shared_settings)
    try:
        result = RuntimeConfigManager().update("embedding", "batch_size", 128)
        assert result["success"] is True
        # 全 ctx.settings は configure 渡しのこのオブジェクトから作られる（use_cases.py:120）。
        # ここに届けば全ペルソナの ctx に届く。
        assert AppContextRegistry._settings is shared_settings
        assert shared_settings.embedding.batch_size == 128
    finally:
        AppContextRegistry._settings = None


def test_override_type_coercion(shared_settings):
    """文字列 "128" → int 128 への coerce。不正型は ValidationError（admin が 400 へ変換）。"""
    from pydantic import ValidationError

    result = RuntimeConfigManager().update("embedding", "batch_size", "128")
    assert result["success"] is True
    assert isinstance(shared_settings.embedding.batch_size, int)
    assert shared_settings.embedding.batch_size == 128
    # overrides ファイルにも coerce 後の値が保存される（再起動適用の整合保証）
    assert RuntimeConfigManager()._overrides["embedding"]["batch_size"] == 128

    with pytest.raises(ValidationError):
        RuntimeConfigManager().update("embedding", "batch_size", "not-a-number")
    # 失敗した値は適用も保存もされない
    assert shared_settings.embedding.batch_size == 128
    assert "batch_size" in RuntimeConfigManager()._overrides["embedding"]


def test_restart_applies_overrides(shared_settings, tmp_path):
    """非 hot キー（server.host）が Settings 再構築 + apply_overrides_to_settings で反映される。"""
    from nous.config.settings import Settings, get_settings

    result = RuntimeConfigManager().update("server", "host", "0.0.0.0")
    assert result["restart_required"] is True
    assert (tmp_path / "config" / "config_overrides.json").exists()

    # 再起動をシミュレート: 新 Settings + 新 RCM + 起動時一括適用（main.py create_app の呼び出し）。
    get_settings.cache_clear()
    RuntimeConfigManager.reset()
    fresh = Settings(data_root=str(tmp_path))
    with patch("nous.config.runtime_config.get_settings", return_value=fresh):
        applied, skipped = RuntimeConfigManager().apply_overrides_to_settings()
        assert applied == 1
        assert skipped == 0
        assert fresh.server.host == "0.0.0.0"


def test_session_silence_hours_keeps_legacy_env_name(tmp_path, monkeypatch):
    """旧 env 名 NOUS_SILENCE_HOURS と新名 NOUS_SESSION_SILENCE_HOURS の両方が効く。"""
    from nous.config.settings import Settings

    monkeypatch.setenv("NOUS_SILENCE_HOURS", "9")
    assert Settings(data_root=str(tmp_path)).session_silence_hours == 9.0

    monkeypatch.setenv("NOUS_SESSION_SILENCE_HOURS", "12")
    assert Settings(data_root=str(tmp_path)).session_silence_hours == 12.0


def test_apply_overrides_skips_invalid_values(shared_settings, tmp_path):
    """型が合わない古い override は警告してスキップ（起動を落とさない）。"""
    import json

    overrides_path = tmp_path / "config" / "config_overrides.json"
    overrides_path.parent.mkdir(parents=True, exist_ok=True)
    overrides_path.write_text(
        json.dumps(
            {
                "embedding": {"batch_size": "corrupted"},
                "qdrant": {"url": "http://qdrant.example:6333"},
            }
        )
    )

    from nous.config.settings import Settings, get_settings

    get_settings.cache_clear()
    RuntimeConfigManager.reset()
    fresh = Settings(data_root=str(tmp_path))
    with patch("nous.config.runtime_config.get_settings", return_value=fresh):
        applied, skipped = RuntimeConfigManager().apply_overrides_to_settings()
        assert (applied, skipped) == (1, 1)
        assert fresh.qdrant.url == "http://qdrant.example:6333"
        assert fresh.embedding.batch_size != "corrupted"
