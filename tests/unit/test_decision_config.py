"""Tests for brain_decision_* config keys, resolver, and tier classification (#011)."""

from __future__ import annotations

from nous.api.http.routers.chat.chat_management import _field_section, _field_tier
from nous.domain.chat_config import ChatConfig, ChatConfigFileRepository, resolve_persona_chat_config
from nous.domain.memory.query_service import resolve_decision_config


def _repo(tmp_path, **cfg_kwargs):
    repo = ChatConfigFileRepository(str(tmp_path))
    repo.save(ChatConfig(persona="p", **cfg_kwargs))

    class _Conn:
        data_dir = str(tmp_path)
        persona = "p"

    class _Repo:
        _conn = _Conn()

    return _Repo()


def test_round_trip(tmp_path):
    repo = ChatConfigFileRepository(str(tmp_path))
    repo.save(
        ChatConfig(
            persona="p",
            brain_decision_enabled=True,
            brain_decision_model="gpt-x",
            brain_decision_threshold=0.7,
            brain_decision_max_hops=3,
            brain_decision_time_weight=0.7,
        )
    )
    loaded = repo.get("p")
    assert loaded.brain_decision_enabled is True
    assert loaded.brain_decision_model == "gpt-x"
    assert loaded.brain_decision_threshold == 0.7
    assert loaded.brain_decision_max_hops == 3
    assert loaded.brain_decision_time_weight == 0.7


def test_defaults():
    cfg = ChatConfig(persona="p")
    assert cfg.brain_decision_enabled is False
    assert cfg.brain_decision_model == ""
    assert cfg.brain_decision_threshold == 0.55
    assert cfg.brain_decision_max_hops == 1
    assert cfg.brain_decision_time_weight == 0.0  # 0.0 = 無効 (opt-in、既存挙動と一致)


def test_clamp_validators():
    cfg = ChatConfig(persona="p", brain_decision_threshold=2.0, brain_decision_max_hops=99)
    assert cfg.brain_decision_threshold == 1.0
    assert cfg.brain_decision_max_hops == 5
    cfg2 = ChatConfig(persona="p", brain_decision_threshold=-1.0, brain_decision_max_hops=0)
    assert cfg2.brain_decision_threshold == 0.0
    assert cfg2.brain_decision_max_hops == 1
    cfg3 = ChatConfig(persona="p", brain_decision_time_weight=2.0)
    assert cfg3.brain_decision_time_weight == 1.0
    cfg4 = ChatConfig(persona="p", brain_decision_time_weight=-1.0)
    assert cfg4.brain_decision_time_weight == 0.0


def test_resolve_defaults_without_conn():
    assert resolve_decision_config(object()) == {
        "enabled": False,
        "model": "",
        "threshold": 0.55,
        "max_hops": 1,
        "time_weight": 0.0,
    }


def test_resolve_reads_config(tmp_path):
    repo = _repo(
        tmp_path,
        brain_decision_enabled=True,
        brain_decision_model="m",
        brain_decision_threshold=0.8,
        brain_decision_max_hops=4,
        brain_decision_time_weight=0.6,
    )
    assert resolve_decision_config(repo) == {
        "enabled": True,
        "model": "m",
        "threshold": 0.8,
        "max_hops": 4,
        "time_weight": 0.6,
    }


def test_rest_save_persists_and_resolves_max_hops_clamped(tmp_path, monkeypatch):
    """REST 保存 → JSON ファイル → resolve_decision_config の経路でも hops を 1..5 に clamp (#011)。"""
    import asyncio
    import types

    from nous.api.http.routers.chat import chat_management as cm

    monkeypatch.setattr(cm, "get_settings", lambda: types.SimpleNamespace(data_root=str(tmp_path)))
    result = asyncio.run(
        cm._do_save_chat_config("p", None, {"brain_decision_enabled": True, "brain_decision_max_hops": 99})
    )
    assert result["brain_decision_max_hops"] == 5

    class _Conn:
        data_dir = str(tmp_path)
        persona = "p"

    class _Repo:
        _conn = _Conn()

    resolved = resolve_decision_config(_Repo())
    assert resolved["enabled"] is True
    assert resolved["max_hops"] == 5


def test_resolve_persona_chat_config_without_conn():
    assert resolve_persona_chat_config(object()) is None


def test_resolve_persona_chat_config_reads_config(tmp_path):
    repo = _repo(tmp_path, brain_decision_enabled=True, brain_decision_model="m")
    cfg = resolve_persona_chat_config(repo)
    assert isinstance(cfg, ChatConfig)
    assert cfg.brain_decision_enabled is True
    assert cfg.brain_decision_model == "m"


def test_tier_and_section():
    for key in (
        "brain_decision_enabled",
        "brain_decision_model",
        "brain_decision_threshold",
        "brain_decision_max_hops",
        "brain_decision_time_weight",
    ):
        assert _field_tier(key) == "advanced"
        assert _field_section(key) == "brain_simulation"
